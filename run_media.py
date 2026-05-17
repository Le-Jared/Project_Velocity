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


# =============================================================================
# Logging helpers
# =============================================================================

def format_money(value):
    try:
        number = float(value or 0)
    except Exception:
        number = 0.0

    return f"{number:,.2f}"


def compact_path(path):
    path = Path(path)

    try:
        return f"{path.parent.name}/{path.name}"
    except Exception:
        return str(path)


def log_section(log, title):
    log("")
    log(f"── {title} ──")


def log_metric(log, label, value):
    log(f"   • {label}: {value}")


def partner_summary(values, max_items=12):
    values = sorted({str(value).strip() for value in values if str(value).strip()})

    if not values:
        return "None"

    if len(values) <= max_items:
        return ", ".join(values)

    visible = ", ".join(values[:max_items])
    return f"{visible}, ... plus {len(values) - max_items} more"


def summarize_preview(preview_records):
    matched = [
        row for row in preview_records
        if str(row.get("status", "")).lower().startswith("matched")
    ]

    errors = [
        row for row in preview_records
        if not str(row.get("status", "")).lower().startswith("matched")
    ]

    matched_partners = sorted({
        str(row.get("partner", "")).strip()
        for row in matched
        if row.get("partner")
    })

    error_partners = sorted({
        str(row.get("partner", "")).strip()
        for row in errors
        if row.get("partner")
    })

    return {
        "matched_count": len(matched),
        "error_count": len(errors),
        "matched_partners": matched_partners,
        "error_partners": error_partners,
    }


def summarize_skipped_rows(skipped_rows):
    grouped = {}

    for row in skipped_rows:
        partner = str(row.get("partner", "")).strip() or "UNKNOWN"
        amount = safe_float(row.get("planned_amount", 0))

        if partner not in grouped:
            grouped[partner] = {
                "rows": 0,
                "gross": 0.0,
                "reason": str(row.get("reason", "")).strip(),
            }

        grouped[partner]["rows"] += 1
        grouped[partner]["gross"] += amount

    return grouped


def log_skipped_summary(log, skipped_rows, limit=10):
    if not skipped_rows:
        log("   • Skipped rows: 0")
        return

    grouped = summarize_skipped_rows(skipped_rows)

    log(f"   • Skipped rows: {len(skipped_rows)}")
    log("   • Skipped partners:")

    for index, (partner, info) in enumerate(sorted(grouped.items())):
        if index >= limit:
            log(f"     - ... plus {len(grouped) - limit} more partner(s)")
            break

        log(
            f"     - {partner}: "
            f"{info['rows']} row(s), gross {format_money(info['gross'])}"
        )


def log_action_items(log, warnings, gap_report_path=None, skipped_rows=None):
    skipped_rows = skipped_rows or []

    if not warnings and not skipped_rows:
        log("   • Action needed: None")
        return

    log("   • Action needed:")

    if skipped_rows:
        skipped_partners = sorted({
            str(row.get("partner", "")).strip()
            for row in skipped_rows
            if row.get("partner")
        })

        log(
            "     - Add/approve Buying Guide rows for: "
            + partner_summary(skipped_partners)
        )

    if gap_report_path:
        log(f"     - Review gap report: {compact_path(gap_report_path)}")


# =============================================================================
# Main pipeline
# =============================================================================

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
    verbose=False,
):
    logs = []
    warnings = []
    diagnostics = {}

    def log(message):
        text = str(message)
        logs.append(text)

        if verbose:
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

    log_section(log, "Conversion started")
    log_metric(log, "File", media_plan_path.name)
    log_metric(log, "Client", client)
    log_metric(log, "Detected client", detected_client or "Not detected")
    log_metric(log, "Gemini fallback", "Enabled" if use_gemini else "Disabled")
    log_metric(
        log,
        "Unmatched Buying Guide rows",
        "Skip and report" if skip_unmatched_buying_guide else "Block export",
    )

    # -------------------------------------------------------------------------
    # 1. Read
    # -------------------------------------------------------------------------

    log_section(log, "1. Read media plan")

    raw_df = parse_media_plan(media_plan_path)
    diagnostics.update(frame_diagnostics(raw_df, "raw"))

    log_metric(log, "Raw rows", len(raw_df))
    log_metric(log, "Raw columns", len(raw_df.columns))

    # -------------------------------------------------------------------------
    # 2. Normalize
    # -------------------------------------------------------------------------

    log_section(log, "2. Normalize media plan")

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

    log_metric(log, "Normalized rows", len(normalized_df))
    log_metric(log, "Normalized gross", format_money(diagnostics["normalized_gross_total"]))
    log_metric(log, "Bad partner values", before_bad_partners)
    log_metric(log, "Bad channel values", before_bad_channels)

    # -------------------------------------------------------------------------
    # 3. Gemini fallback
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # 4. Consolidate
    # -------------------------------------------------------------------------

    log_section(log, "4. Consolidate placements")

    consolidated_df = consolidate_for_prisma(normalized_df)

    diagnostics.update(frame_diagnostics(consolidated_df, "consolidated"))
    diagnostics["consolidated_gross_total"] = money_sum(consolidated_df, "planned_amount")
    diagnostics["partners"] = unique_values(consolidated_df, "partner")
    diagnostics.update(date_diagnostics(consolidated_df, "consolidated"))

    log_metric(log, "Consolidated rows", len(consolidated_df))
    log_metric(log, "Consolidated gross", format_money(diagnostics["consolidated_gross_total"]))
    log_metric(log, "Partners detected", partner_summary(diagnostics["partners"]))

    # -------------------------------------------------------------------------
    # 5. Load Buying Guide
    # -------------------------------------------------------------------------

    log_section(log, "5. Load Buying Guide")

    guide_df = load_buying_guide(buying_guide_path)
    diagnostics["buying_guide_rows"] = int(len(guide_df))

    log_metric(log, "Buying Guide rows", len(guide_df))
    log_metric(log, "Buying Guide file", compact_path(buying_guide_path))

    # -------------------------------------------------------------------------
    # 6. Preview Buying Guide
    # -------------------------------------------------------------------------

    log_section(log, "6. Preview Buying Guide matches")

    preview_df = preview_buying_guide_matches(consolidated_df, guide_df)
    preview_records = preview_df.fillna("").to_dict(orient="records")
    preview_errors = [
        row for row in preview_records
        if not str(row.get("status", "")).lower().startswith("matched")
    ]

    preview_summary = summarize_preview(preview_records)

    diagnostics["preview"] = preview_records
    diagnostics["preview_errors"] = preview_errors
    diagnostics["preview_matched_count"] = preview_summary["matched_count"]
    diagnostics["preview_error_count"] = preview_summary["error_count"]
    diagnostics["preview_matched_partners"] = preview_summary["matched_partners"]
    diagnostics["preview_error_partners"] = preview_summary["error_partners"]

    log_metric(log, "Matched preview rows", preview_summary["matched_count"])
    log_metric(log, "Unmatched preview rows", preview_summary["error_count"])
    log_metric(log, "Matched partners", partner_summary(preview_summary["matched_partners"]))
    log_metric(log, "Unmatched partners", partner_summary(preview_summary["error_partners"]))

    if preview_errors:
        warnings.append(f"{len(preview_errors)} Buying Guide preview issue(s) found.")

    # -------------------------------------------------------------------------
    # 6b. Gap report
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # 7. Enrich
    # -------------------------------------------------------------------------

    log_section(log, "7. Enrich with Buying Guide")

    enriched_df = enrich_with_buying_guide(
        consolidated_df,
        guide_df,
        skip_unmatched=skip_unmatched_buying_guide,
    )

    skipped_rows = enriched_df.attrs.get("skipped_buying_guide_rows", [])
    fallback_rows = enriched_df.attrs.get("cross_client_buying_guide_fallback_rows", [])

    diagnostics.update(frame_diagnostics(enriched_df, "enriched"))
    diagnostics["exported_gross_total"] = money_sum(enriched_df, "planned_amount")
    diagnostics["skipped_buying_guide_rows"] = skipped_rows
    diagnostics["cross_client_buying_guide_fallback_rows"] = fallback_rows
    diagnostics["cross_client_buying_guide_fallback_count"] = len(fallback_rows)
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

    diagnostics["unmatched_gross_total"] = round(
        diagnostics.get("consolidated_gross_total", 0.0)
        - diagnostics.get("exported_gross_total", 0.0),
        2,
    )

    log_metric(log, "Rows ready for export", len(enriched_df))
    log_metric(log, "Exported gross", format_money(diagnostics["exported_gross_total"]))
    log_metric(log, "Skipped gross", format_money(diagnostics["skipped_buying_guide_gross_total"]))

    if fallback_rows:
        warnings.append(f"{len(fallback_rows)} Buying Guide row(s) matched via cross-client fallback.")
        log_metric(log, "Cross-client fallback rows", len(fallback_rows))

    if skipped_rows:
        warnings.append(f"{len(skipped_rows)} Buying Guide row(s) skipped.")
        log_skipped_summary(log, skipped_rows)

    if diagnostics["unmatched_gross_total"] > 0:
        warnings.append(f"Unmatched/skipped gross total: {diagnostics['unmatched_gross_total']}")

    # -------------------------------------------------------------------------
    # Debug files
    # -------------------------------------------------------------------------

    if debug:
        log_section(log, "Debug output")

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
        log_metric(log, "Debug folder", debug_dir)

    # -------------------------------------------------------------------------
    # 8. Export
    # -------------------------------------------------------------------------

    log_section(log, "8. Export Prisma import")

    final_path = export_prisma_import(
        enriched_df=enriched_df,
        output_path=output_path,
        template_path=template_path,
    )

    diagnostics["final_output_path"] = str(final_path)

    log_metric(log, "Output file", final_path)
    log_metric(log, "Output rows", len(enriched_df))

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------

    log_section(log, "Conversion summary")

    log_metric(log, "Status", "Completed with warnings" if warnings else "Completed")
    log_metric(log, "Client", client)
    log_metric(log, "Input rows", len(raw_df))
    log_metric(log, "Consolidated rows", len(consolidated_df))
    log_metric(log, "Exported rows", len(enriched_df))
    log_metric(log, "Skipped rows", len(skipped_rows))
    log_metric(log, "Consolidated gross", format_money(diagnostics["consolidated_gross_total"]))
    log_metric(log, "Exported gross", format_money(diagnostics["exported_gross_total"]))
    log_metric(log, "Skipped gross", format_money(diagnostics["skipped_buying_guide_gross_total"]))
    log_metric(log, "Output", compact_path(final_path))

    if gap_report_path:
        log_metric(log, "Gap report", compact_path(gap_report_path))

    log_action_items(
        log=log,
        warnings=warnings,
        gap_report_path=gap_report_path,
        skipped_rows=skipped_rows,
    )

    return {
        "ok": True,
        "output_path": str(final_path),
        "output_file": final_path.name,
        "logs": logs,
        "warnings": warnings,
        "diagnostics": diagnostics,
        "preview": preview_records,
    }


# =============================================================================
# Core helpers
# =============================================================================

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


# =============================================================================
# Gemini fallback
# =============================================================================

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

    log_section(log, "3. Gemini fallback")

    if not use_gemini:
        diagnostics["gemini_used"] = False
        diagnostics["bad_partners_after_gemini"] = before_bad_partners
        diagnostics["bad_channels_after_gemini"] = before_bad_channels
        log_metric(log, "Status", "Skipped")
        log_metric(log, "Reason", "Gemini disabled")
        return normalized_df

    if rows_needing_gemini <= 0:
        diagnostics["gemini_used"] = False
        diagnostics["bad_partners_after_gemini"] = before_bad_partners
        diagnostics["bad_channels_after_gemini"] = before_bad_channels
        log_metric(log, "Status", "Skipped")
        log_metric(log, "Reason", "No bad partner/channel rows detected")
        return normalized_df

    if not enrich_dataframe or not gemini_is_available():
        diagnostics["gemini_used"] = False
        diagnostics["bad_partners_after_gemini"] = before_bad_partners
        diagnostics["bad_channels_after_gemini"] = before_bad_channels
        warnings.append("Gemini fallback requested but unavailable.")
        log_metric(log, "Status", "Unavailable")
        log_metric(log, "Rows needing review", rows_needing_gemini)
        return normalized_df

    log_metric(log, "Status", "Applied")
    log_metric(log, "Scope", "Bad partner/channel rows only")
    log_metric(log, "Rows needing review", rows_needing_gemini)

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

    log_metric(log, "Bad partners", f"{before_bad_partners} → {after_bad_partners}")
    log_metric(log, "Bad channels", f"{before_bad_channels} → {after_bad_channels}")

    remaining_bad = bad_values(enriched_df, "partner")

    if remaining_bad:
        diagnostics["bad_partner_values_after_gemini"] = remaining_bad
        warnings.append("Bad partner values remain after Gemini: " + ", ".join(remaining_bad[:10]))
        log_metric(log, "Remaining bad partners", ", ".join(remaining_bad[:10]))
    else:
        log_metric(log, "Remaining bad partners", "None")

    return enriched_df


# =============================================================================
# Buying Guide gap report
# =============================================================================

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

    log_section(log, "6b. Buying Guide gap report")
    log_metric(log, "Rows needing Buying Guide approval", len(preview_errors))

    partners = sorted({
        str(row.get("partner", "")).strip()
        for row in preview_errors
        if row.get("partner")
    })

    log_metric(log, "Missing partners", partner_summary(partners))

    if use_gemini and build_buying_guide_gap_report and gemini_is_available():
        log_metric(log, "Advisor", "Gemini")
        records = build_buying_guide_gap_report(
            preview_errors=preview_errors,
            consolidated_records=consolidated_records,
            plan_label=str(client).upper(),
        )
    else:
        log_metric(log, "Advisor", "Deterministic fallback")
        records = deterministic_gap_report(preview_errors)

        if use_gemini and not gemini_is_available():
            warnings.append("Gemini Buying Guide gap report requested but Gemini is unavailable.")

    export_gap_report(records, output_path)

    log_metric(log, "Gap report file", output_path)
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
                "suggested_buying_guide_row_status": "Needs finance approval",
                "safe_to_auto_export": "No",
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

    report_columns = [
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
        "suggested_buying_guide_row_status",
        "safe_to_auto_export",
    ]

    df = pd.DataFrame(records)

    for col in report_columns:
        if col not in df.columns:
            df[col] = ""

    df = df[report_columns]

    draft_rows = []

    for _, row in df.iterrows():
        draft_rows.append(
            {
                "Buy type": "Display",
                "Financial buy type": "Display",
                "Buy category": "Mobile",
                "Currency": "SGD",
                "Supplier code": "",
                "Supplier name": "",
                "Positioning": "other",
                "Ad size": "1 x 1",
                "Cost method": row.get("suggested_cost_method", "CPM"),
                "Unit type": row.get("suggested_unit_type", "Impressions"),
                "Unit rate": "",
                "Planned units": "",
                "Planned amount": "",
                "Placement booking type": row.get("suggested_placement_booking_type", ""),
                "Clients that uses these respectively": row.get("client", ""),
                "Approval status": "Needs finance approval",
                "Safe to auto-export": "No",
            }
        )

    draft_df = pd.DataFrame(draft_rows)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Buying Guide Gaps")
        draft_df.to_excel(writer, index=False, sheet_name="Draft Buying Guide Rows")


# =============================================================================
# Local test runner
# =============================================================================

if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent

    result = run_media_plan_to_prisma(
        media_plan_path=BASE_DIR / "media_plans" / "Skillignition_Media_plan_sample.xlsx",
        buying_guide_path=BASE_DIR / "Input" / "ACCT 108 BuyingGuide.xlsx",
        output_path=BASE_DIR / "Output" / "GU_prisma_import.xlsx",
        template_path=BASE_DIR / "Input" / "ACCT-108 DIGITAL TEMPLATE MEDIA PLAN IMPORT placements.xlsx",
        client="AUTO",
        debug=False,
        use_gemini=True,
        skip_unmatched_buying_guide=False,
        generate_buying_guide_gap_report=True,
        verbose=True,
    )

    print(result)

