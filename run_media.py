from pathlib import Path
import pandas as pd

from plan_parser import parse_media_plan, detect_client
from plan_adapters import adapt_media_plan, consolidate_for_prisma
from buying_guide import (
    load_buying_guide,
    enrich_with_buying_guide,
    preview_buying_guide_matches,
)
from prisma_builder import export_prisma_import, export_debug_files

try:
    from gemini_fallback_prisma import (
        enrich_dataframe,
        build_buying_guide_gap_report,
        is_available as gemini_is_available,
    )
except Exception:
    enrich_dataframe = None
    build_buying_guide_gap_report = None

    def gemini_is_available():
        return False


BAD_TEXT_VALUES = {"", "nan", "none", "unknown", "n/a", "na"}


def run_media_plan_to_prisma(
    media_plan_path,
    buying_guide_path,
    output_path,
    client="AUTO",
    debug=False,
    use_gemini=False,
    skip_unmatched_buying_guide=False,
    template_path=None,
    debug_output_dir=None,
    generate_buying_guide_gap_report=True,
):
    logs = []
    warnings = []
    diagnostics = {}

    def log(message):
        text = str(message)
        logs.append(text)
        print(text)

    media_plan_path = Path(media_plan_path)
    buying_guide_path = Path(buying_guide_path)
    output_path = Path(output_path)
    template_path = Path(template_path) if template_path else None

    detected_client = detect_client(media_plan_path)
    client = resolve_client(client, detected_client)

    diagnostics["detected_client"] = detected_client
    diagnostics["client"] = client
    diagnostics["media_plan_path"] = str(media_plan_path)
    diagnostics["buying_guide_path"] = str(buying_guide_path)
    diagnostics["output_path"] = str(output_path)
    diagnostics["template_path"] = str(template_path) if template_path else ""

    log(f"Client: {client}" + (f" detected from file as {detected_client}" if detected_client else ""))
    log("1. Reading media plan...")

    raw_df = parse_media_plan(media_plan_path)
    diagnostics.update(frame_diagnostics(raw_df, "raw"))

    log("2. Normalizing media plan...")
    normalized_df = adapt_media_plan(raw_df, client=client)
    diagnostics.update(frame_diagnostics(normalized_df, "normalized"))
    diagnostics["normalized_gross_total"] = money_sum(normalized_df, "gross_media")
    diagnostics.update(date_diagnostics(normalized_df, "normalized"))

    before_bad_partners = count_bad_values(normalized_df, "partner")
    before_bad_channels = count_bad_values(
        normalized_df,
        "channel" if "channel" in normalized_df.columns else "partner",
    )

    diagnostics["bad_partners_before_gemini"] = before_bad_partners
    diagnostics["bad_channels_before_gemini"] = before_bad_channels

    normalized_df = maybe_apply_gemini(
        normalized_df=normalized_df,
        client=client,
        use_gemini=use_gemini,
        before_bad_partners=before_bad_partners,
        before_bad_channels=before_bad_channels,
        diagnostics=diagnostics,
        warnings=warnings,
        log=log,
    )

    diagnostics.update(date_diagnostics(normalized_df, "normalized_after_gemini"))

    log("4. Consolidating placements...")
    consolidated_df = consolidate_for_prisma(normalized_df)

    diagnostics.update(frame_diagnostics(consolidated_df, "consolidated"))
    diagnostics["consolidated_gross_total"] = money_sum(consolidated_df, "planned_amount")
    diagnostics["partners"] = unique_values(consolidated_df, "partner")
    diagnostics.update(date_diagnostics(consolidated_df, "consolidated"))

    log("5. Loading Buying Guide...")
    guide_df = load_buying_guide(buying_guide_path)

    diagnostics["buying_guide_rows"] = int(len(guide_df))

    log("6. Previewing Buying Guide matches...")
    preview_df = preview_buying_guide_matches(consolidated_df, guide_df)
    preview_records = preview_df.fillna("").to_dict(orient="records")
    preview_errors = [
        row for row in preview_records
        if not str(row.get("status", "")).lower().startswith("matched")
    ]

    diagnostics["preview"] = preview_records
    diagnostics["preview_errors"] = preview_errors

    if preview_errors:
        warnings.append(f"{len(preview_errors)} Buying Guide preview issue(s) found.")

    gap_report_path = None
    gap_report_records = []

    if preview_errors and generate_buying_guide_gap_report:
        gap_report_path = output_path.parent / f"{output_path.stem}_buying_guide_gap_report.xlsx"

        gap_report_records = generate_gap_report(
            preview_errors=preview_errors,
            consolidated_df=consolidated_df,
            client=client,
            output_path=gap_report_path,
            use_gemini=use_gemini,
            warnings=warnings,
            log=log,
        )

        diagnostics["buying_guide_gap_report_path"] = str(gap_report_path)
        diagnostics["buying_guide_gap_report_rows"] = len(gap_report_records)
        diagnostics["buying_guide_gap_report"] = gap_report_records

    log("7. Enriching with Buying Guide...")
    enriched_df = enrich_with_buying_guide(
        consolidated_df,
        guide_df,
        skip_unmatched=skip_unmatched_buying_guide,
    )

    skipped_rows = enriched_df.attrs.get("skipped_buying_guide_rows", [])

    diagnostics.update(frame_diagnostics(enriched_df, "enriched"))
    diagnostics["exported_gross_total"] = money_sum(enriched_df, "planned_amount")
    diagnostics["skipped_buying_guide_rows"] = skipped_rows
    diagnostics["skipped_partners"] = sorted(
        {
            str(row.get("partner", "")).strip()
            for row in skipped_rows
            if row.get("partner")
        }
    )
    diagnostics["skipped_buying_guide_gross_total"] = round(
        sum(safe_float(row.get("planned_amount", 0)) for row in skipped_rows),
        2,
    )
    diagnostics.update(date_diagnostics(enriched_df, "enriched"))

    if skipped_rows:
        warnings.append(f"{len(skipped_rows)} Buying Guide row(s) skipped.")

    diagnostics["unmatched_gross_total"] = round(
        diagnostics.get("consolidated_gross_total", 0.0)
        - diagnostics.get("exported_gross_total", 0.0),
        2,
    )

    if diagnostics["unmatched_gross_total"] > 0:
        warnings.append(f"Unmatched/skipped gross total: {diagnostics['unmatched_gross_total']}")

    if debug:
        if debug_output_dir:
            debug_dir = Path(debug_output_dir)
        else:
            debug_dir = output_path.parent / f"{output_path.stem}_debug"

        export_debug_files(
            raw_df=raw_df,
            normalized_df=normalized_df,
            consolidated_df=consolidated_df,
            enriched_df=enriched_df,
            output_dir=debug_dir,
        )

        diagnostics["debug_output_dir"] = str(debug_dir)
        log(f"Debug files saved to: {debug_dir}")

    log("8. Exporting Prisma import...")

    final_path = export_prisma_import(
        enriched_df=enriched_df,
        output_path=output_path,
        template_path=template_path,
    )

    log(f"Done. Prisma import saved to: {final_path}")

    return {
        "ok": True,
        "output_path": str(final_path),
        "output_file": final_path.name,
        "logs": logs,
        "warnings": warnings,
        "diagnostics": diagnostics,
        "preview": preview_records,
    }


def resolve_client(client, detected_client):
    text = str(client or "").upper().strip()

    if text in {"", "AUTO", "NONE", "NULL"}:
        return detected_client or "GU"

    return text


def frame_diagnostics(df, prefix):
    return {
        f"{prefix}_rows": int(len(df)),
        f"{prefix}_columns": [str(col) for col in df.columns],
    }


def money_sum(df, column):
    if column not in df.columns:
        return 0.0

    return round(float(df[column].fillna(0).sum()), 2)


def safe_float(value):
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except Exception:
        return 0.0


def unique_values(df, column):
    if column not in df.columns:
        return []

    return df[column].dropna().astype(str).unique().tolist()


def date_diagnostics(df, prefix):
    result = {}

    for col in ["start_date", "end_date", "flight_start", "flight_end"]:
        key_prefix = f"{prefix}_{col}"

        if col not in df.columns:
            result[f"{key_prefix}_min"] = ""
            result[f"{key_prefix}_max"] = ""
            continue

        parsed = df[col].apply(parse_date_safe)
        valid = parsed.dropna()

        result[f"{key_prefix}_min"] = str(valid.min()) if not valid.empty else ""
        result[f"{key_prefix}_max"] = str(valid.max()) if not valid.empty else ""

    return result


def parse_date_safe(value):
    try:
        import pandas as pd

        parsed = pd.to_datetime(value, errors="coerce")

        if pd.isna(parsed):
            return None

        return parsed
    except Exception:
        return None


def looks_bad_text_value(value):
    text = str(value).strip()

    if text.lower() in BAD_TEXT_VALUES:
        return True

    try:
        float(text.replace(",", ""))
        return True
    except Exception:
        return False


def count_bad_values(df, column):
    if column not in df.columns:
        return 0

    return int(df[column].apply(looks_bad_text_value).sum())


def bad_values(df, column):
    if column not in df.columns:
        return []

    return sorted(
        {
            str(value).strip()
            for value in df[column].tolist()
            if looks_bad_text_value(value) and str(value).strip()
        }
    )


def maybe_apply_gemini(
    normalized_df,
    client,
    use_gemini,
    before_bad_partners,
    before_bad_channels,
    diagnostics,
    warnings,
    log,
):
    rows_needing_gemini = max(before_bad_partners, before_bad_channels)

    if not use_gemini:
        diagnostics["gemini_used"] = False
        diagnostics["bad_partners_after_gemini"] = before_bad_partners
        diagnostics["bad_channels_after_gemini"] = before_bad_channels
        log("3. Gemini fallback skipped.")
        return normalized_df

    if rows_needing_gemini <= 0:
        diagnostics["gemini_used"] = False
        diagnostics["bad_partners_after_gemini"] = before_bad_partners
        diagnostics["bad_channels_after_gemini"] = before_bad_channels
        log("3. Gemini fallback skipped because no bad partner/channel rows were detected.")
        return normalized_df

    if not enrich_dataframe or not gemini_is_available():
        diagnostics["gemini_used"] = False
        diagnostics["bad_partners_after_gemini"] = before_bad_partners
        diagnostics["bad_channels_after_gemini"] = before_bad_channels
        warnings.append("Gemini fallback requested but unavailable.")
        log("3. Gemini fallback requested but unavailable.")
        return normalized_df

    log("3. Applying Gemini fallback for bad partner/channel rows only...")

    enriched_df = enrich_dataframe(
        normalized_df,
        fields=["partner", "channel"],
        plan_label=str(client).upper(),
        xlsx_path=None,
        only_bad_rows=True,
    )

    after_bad_partners = count_bad_values(enriched_df, "partner")
    after_bad_channels = count_bad_values(
        enriched_df,
        "channel" if "channel" in enriched_df.columns else "partner",
    )

    diagnostics["gemini_used"] = True
    diagnostics["bad_partners_after_gemini"] = after_bad_partners
    diagnostics["bad_channels_after_gemini"] = after_bad_channels

    log(
        "Gemini fallback complete. "
        f"Bad partners: {before_bad_partners} → {after_bad_partners}; "
        f"Bad channels: {before_bad_channels} → {after_bad_channels}"
    )

    remaining_bad = bad_values(enriched_df, "partner")

    if remaining_bad:
        diagnostics["bad_partner_values_after_gemini"] = remaining_bad
        warnings.append("Bad partner values remain after Gemini: " + ", ".join(remaining_bad[:10]))

    return enriched_df


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent

    result = run_media_plan_to_prisma(
        media_plan_path=BASE_DIR / "media_plans" / "Skillignition_Media_plan_sample.xlsx",
        buying_guide_path=BASE_DIR / "Input" / "ACCT 108 BuyingGuide.xlsx",
        output_path=BASE_DIR / "Output" / "GU_prisma_import.xlsx",
        template_path=BASE_DIR / "Input" / "ACCT-108 DIGITAL TEMPLATE MEDIA PLAN IMPORT placements.xlsx",
        client="AUTO",
        debug=True,
        use_gemini=True,
        skip_unmatched_buying_guide=False,
        generate_buying_guide_gap_report=True,
    )

    print(result)

def generate_gap_report(
    preview_errors,
    consolidated_df,
    client,
    output_path,
    use_gemini,
    warnings,
    log,
):
    consolidated_records = consolidated_df.fillna("").to_dict(orient="records")

    if use_gemini and build_buying_guide_gap_report and gemini_is_available():
        log("6b. Generating Gemini Buying Guide gap report...")
        records = build_buying_guide_gap_report(
            preview_errors=preview_errors,
            consolidated_records=consolidated_records,
            plan_label=str(client).upper(),
        )
    else:
        log("6b. Generating deterministic Buying Guide gap report...")
        records = deterministic_gap_report(preview_errors)

        if use_gemini and not gemini_is_available():
            warnings.append("Gemini Buying Guide gap report requested but Gemini is unavailable.")

    export_gap_report(records, output_path)

    log(f"Buying Guide gap report saved to: {output_path}")
    warnings.append(f"Buying Guide gap report generated: {output_path}")
    return records


def deterministic_gap_report(preview_errors):
    rows = []

    for row in preview_errors:
        client = str(row.get("client", "")).strip()
        partner = str(row.get("partner", "")).strip()

        rows.append(
            {
                "client": client,
                "missing_partner": partner,
                "suggested_placement_booking_type": partner,
                "suggested_aliases": default_aliases_for_partner(partner),
                "suggested_cost_method": "CPM",
                "suggested_unit_type": "Impressions",
                "confidence": "Medium",
                "evidence_summary": f"Buying Guide matching failed for client={client}, partner={partner}.",
                "required_human_action": "Add an approved Buying Guide row for this client and partner.",
                "do_not_auto_export_reason": "Supplier code, supplier name, currency, financial buy type, and finance fields must come from the official Buying Guide.",
            }
        )

    return rows


def default_aliases_for_partner(partner):
    aliases = {
        "Meta": "Facebook, Meta, FB, Instagram",
        "TikTok": "TikTok, Tiktok, Tik Tok",
        "Google": "Google, UAC, Universal App Campaign",
        "Google Search": "Google Search, Search, SEM, Paid Search",
        "Google PMAX": "Google PMAX, Google - PMAX, PMAX, Performance Max",
        "Google Display": "Google Display, Display, GDN",
        "Google Demand Gen": "Google Demand Gen, Demand Gen, DemandGen, Discovery",
        "Google Youtube": "Google Youtube, YouTube, Youtube, YT",
        "Apple Search": "Apple Search, Apple Search Ads, ASA, IAD",
        "Reddit": "Reddit, Reddit Traffic",
        "The Trade Desk": "The Trade Desk, Trade Desk, TTD",
        "Moloco": "Moloco",
        "Jampp": "Jampp",
    }

    return aliases.get(partner, partner)


def export_gap_report(records, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    columns = [
        "client",
        "missing_partner",
        "suggested_placement_booking_type",
        "suggested_aliases",
        "suggested_cost_method",
        "suggested_unit_type",
        "confidence",
        "evidence_summary",
        "required_human_action",
        "do_not_auto_export_reason",
    ]

    df = pd.DataFrame(records)

    for col in columns:
        if col not in df.columns:
            df[col] = ""

    df = df[columns]

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Buying Guide Gaps")

