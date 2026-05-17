import os
import re
import json
import time
import pathlib
from typing import Any

import pandas as pd
from google import genai


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_BATCH_SIZE = int(os.environ.get("GEMINI_MAX_BATCH_SIZE", "10"))
MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "3"))
MAX_GEMINI_ROWS = int(os.environ.get("GEMINI_MAX_ROWS", "50"))

UNKNOWN_VALUES = {"UNKNOWN", "", None, 0, 0.0, "0", "0.0", "NONE", "N/A", "NA", "NAN"}

ALLOWED_PARTNERS = [
    "Meta",
    "TikTok",
    "Google",
    "Google Search",
    "Google PMAX",
    "Google Display",
    "Google Demand Gen",
    "Google Youtube",
    "Apple Search",
    "Reddit",
    "The Trade Desk",
    "Moloco",
    "Jampp",
]

_client = None


FIELD_DESCRIPTIONS = {
    "channel": (
        "Canonical channel or publisher name, such as Facebook, Meta, TikTok, "
        "Google Search, Google PMAX, Google Display, Google Demand Gen, "
        "Google Youtube, Apple Search, Reddit, The Trade Desk, Moloco, or Jampp."
    ),
    "partner": (
        "Canonical partner for Buying Guide matching. Use only Meta, TikTok, Google, "
        "Google Search, Google PMAX, Google Display, Google Demand Gen, "
        "Google Youtube, Apple Search, Reddit, The Trade Desk, Moloco, or Jampp."
    ),
    "cost_method": "Billing model. Use one of CPM, CPC, CPI, CPV, CPT.",
    "objective": "Campaign objective, such as Awareness, Traffic, Conversion, App Install, Registration.",
    "currency": "Three-letter ISO currency code, such as USD, SGD, IDR, MYR, HKD, JPY.",
    "flight_start": "Campaign start date in YYYY-MM-DD format.",
    "flight_end": "Campaign end date in YYYY-MM-DD format.",
    "start_date": "Campaign start date in YYYY-MM-DD format.",
    "end_date": "Campaign end date in YYYY-MM-DD format.",
    "gross_media": "Gross media budget or planned cost as a number only.",
    "net_media": "Net media budget as a number only.",
    "impressions": "Planned impressions or planned unit amount as a number only.",
    "cpm": "CPM or unit rate as a number only.",
    "os": "Target operating system: iOS, Android, or empty if not applicable.",
}


PLAN_HINTS = {
    "SkillIgnition": (
        "This is a SkillIgnition media plan for client GU. Channels include Facebook, "
        "TikTok, UAC, Google Search, and similar paid media platforms."
    ),
    "GU": (
        "This is a GU media plan. UAC should usually map to Google. "
        "Facebook should map to Meta. TikTok should map to TikTok."
    ),
    "MCP": (
        "This is an MCP 2026 mobile media plan. Currency is typically SGD. "
        "Partner values should map to Meta, TikTok, Google Search, Google PMAX, "
        "Google Display, Google Demand Gen, Google Youtube, Apple Search, Reddit, "
        "The Trade Desk, Moloco, or Jampp where supported by the row context."
    ),
    "MCP 2026": (
        "This is an MCP 2026 mobile media plan. Currency is typically SGD. "
        "Partner values should map to Meta, TikTok, Google Search, Google PMAX, "
        "Google Display, Google Demand Gen, Google Youtube, Apple Search, Reddit, "
        "The Trade Desk, Moloco, or Jampp where supported by the row context."
    ),
    "MI": (
        "This is a Mercari or MI media plan. Channels may use publisher-product names "
        "such as Google Search, UAC Install iOS, Meta Traffic, Apple Search Ads, "
        "TikTok, Reddit, The Trade Desk, Moloco, or Jampp."
    ),
    "MI / Mercari": (
        "This is a Mercari or MI media plan. Channels may use publisher-product names "
        "such as Google Search, UAC Install iOS, Meta Traffic, Apple Search Ads, "
        "TikTok, Reddit, The Trade Desk, Moloco, or Jampp."
    ),
}


CANONICAL_PARTNERS = {
    "facebook": "Meta",
    "meta": "Meta",
    "fb": "Meta",
    "instagram": "Meta",
    "threads": "Meta",
    "ig": "Meta",

    "tiktok": "TikTok",
    "tik tok": "TikTok",
    "tik-tok": "TikTok",

    "apple search ads": "Apple Search",
    "apple search": "Apple Search",
    "asa": "Apple Search",
    "iad": "Apple Search",

    "reddit traffic": "Reddit",
    "reddit": "Reddit",

    "the trade desk": "The Trade Desk",
    "trade desk": "The Trade Desk",
    "ttd": "The Trade Desk",

    "moloco": "Moloco",
    "jampp": "Jampp",

    "google demand gen": "Google Demand Gen",
    "demand gen": "Google Demand Gen",
    "demandgen": "Google Demand Gen",
    "discovery": "Google Demand Gen",

    "google youtube": "Google Youtube",
    "google you tube": "Google Youtube",
    "youtube": "Google Youtube",
    "you tube": "Google Youtube",
    "yt": "Google Youtube",

    "google search": "Google Search",
    "paid search": "Google Search",
    "sem": "Google Search",
    "search": "Google Search",

    "google display network": "Google Display",
    "google display": "Google Display",
    "display": "Google Display",
    "gdn": "Google Display",

    "performance max": "Google PMAX",
    "google pmax": "Google PMAX",
    "google p max": "Google PMAX",
    "pmax": "Google PMAX",
    "p max": "Google PMAX",

    "universal app campaign": "Google",
    "uac": "Google",
    "google": "Google",
}


PARTNER_HINTS = list(CANONICAL_PARTNERS.keys())


def _get_client():
    global _client

    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("[GEMINI] GEMINI_API_KEY not set.")

        _client = genai.Client(api_key=GEMINI_API_KEY)

    return _client


def is_available() -> bool:
    return bool(GEMINI_API_KEY)


def _clean_json_text(raw: str) -> str:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json(raw: str):
    text = _clean_json_text(raw)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    candidates = re.findall(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    print(f"  [GEMINI] Could not parse JSON: {text[:500]}")
    return None


def _is_unknown(value: Any) -> bool:
    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except Exception:
        pass

    text = str(value).strip()

    return text.upper() in UNKNOWN_VALUES


def _safe_str(value: Any) -> str:
    if _is_unknown(value):
        return ""

    return str(value).strip()


def _safe_number(value: Any):
    if _is_unknown(value):
        return ""

    text = str(value).strip()
    text = re.sub(r"\b(SGD|USD|HKD|MYR|IDR|JPY)\b", "", text, flags=re.IGNORECASE)
    text = text.replace("$", "").replace(",", "").strip()

    try:
        return float(text)
    except Exception:
        return ""


def _normalize_text(value: Any) -> str:
    text = _safe_str(value).lower()
    text = (
        text.replace("_", " ")
        .replace("-", " ")
        .replace("/", " ")
        .replace("|", " ")
        .replace("(", " ")
        .replace(")", " ")
    )
    return re.sub(r"\s+", " ", text).strip()


def _canonical_partner(value: Any) -> str:
    text = _normalize_text(value)

    if not text:
        return ""

    for key, partner in sorted(CANONICAL_PARTNERS.items(), key=lambda item: len(item[0]), reverse=True):
        key_norm = _normalize_text(key)

        if key_norm and key_norm in text:
            return partner

    raw = _safe_str(value)

    if raw in ALLOWED_PARTNERS:
        return raw

    return raw


def _has_partner_hint(value: Any) -> bool:
    text = _normalize_text(value)

    if not text:
        return False

    return any(hint in text for hint in PARTNER_HINTS)


def _looks_like_bad_partner(value: Any) -> bool:
    if _is_unknown(value):
        return True

    text = _safe_str(value)
    normalized = _normalize_text(text)

    if not normalized:
        return True

    try:
        float(normalized)
        return True
    except Exception:
        pass

    parsed = pd.to_datetime(text, errors="coerce")

    if not pd.isna(parsed):
        return True

    return normalized in {
        "unknown",
        "none",
        "n a",
        "na",
        "nan",
        "total",
        "subtotal",
        "grand total",
    }


def _build_field_lines(fields: list[str]) -> str:
    return "\n".join(
        f'  - "{field}": {FIELD_DESCRIPTIONS[field]}'
        for field in fields
        if field in FIELD_DESCRIPTIONS
    )


def _build_prompt(rows: list[dict], unknown_fields: list[str], plan_label: str = "") -> str:
    field_lines = _build_field_lines(unknown_fields)
    hint = PLAN_HINTS.get(plan_label, "")
    allowed_partners = ", ".join(ALLOWED_PARTNERS)

    return f"""
You are an expert media-planning data normalizer for an advertising agency.

{hint}

You will receive parsed media-plan placement rows.

Resolve only the listed fields when they are empty, invalid, numeric-looking when text is expected, or unclear.

Fields to resolve:
{field_lines}

Rules:
- Return a JSON array with one object per input row, in the same order.
- Each object must contain only these keys: {json.dumps(unknown_fields)}.
- If a field cannot be determined for a row, return "" for it.
- partner must be one of: {allowed_partners}.
- channel should be a readable publisher/channel name, not an ID, date, campaign code, or number.
- cost_method must be one of: CPM, CPC, CPI, CPV, CPT.
- Dates must use YYYY-MM-DD.
- Numeric fields must be numbers only, without currency symbols or commas.
- Do not invent budget values if no cost, spend, budget, impressions, or rate context exists.
- Do not invent supplier codes, supplier names, financial buy types, or Buying Guide data.
- If partner/channel is numeric-like, infer it from campaign_name, placement_name, targeting, source_sheet, or nearby row_context.
- Return only the JSON array.

Input rows:
{json.dumps(rows, indent=2, default=str)}
""".strip()


def _call_gemini(prompt: str) -> list | dict | None:
    client = _get_client()

    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            return _parse_json(response.text)
        except Exception as exc:
            if _should_retry(exc, attempt):
                _sleep_for_retry(attempt)
                continue
            raise

    return None


def _should_retry(exc: Exception, attempt: int) -> bool:
    message = str(exc).lower()

    retryable = (
        "429" in message
        or "rate" in message
        or "quota" in message
        or "timeout" in message
        or "temporarily" in message
        or "503" in message
        or "500" in message
    )

    return retryable and attempt < MAX_RETRIES - 1


def _sleep_for_retry(attempt: int) -> None:
    wait = min(30, 5 * (2 ** attempt))
    print(f"  [GEMINI] Retry in {wait}s...")
    time.sleep(wait)


def enrich_dataframe(
    df: pd.DataFrame,
    fields: list[str] | None = None,
    plan_label: str = "",
    xlsx_path: str | None = None,
    only_bad_rows: bool = True,
) -> pd.DataFrame:
    if df.empty or not is_available():
        return df

    result_df = df.copy()
    fields = fields or ["partner", "channel"]

    row_payloads = []
    row_indices = []
    unknown_union = set()

    for idx, row in result_df.iterrows():
        missing = _detect_missing_dataframe_fields(row, fields)

        if only_bad_rows and not missing:
            continue

        if not only_bad_rows:
            missing = fields

        row_payloads.append(_dataframe_row_to_payload(row, result_df, idx))
        row_indices.append((idx, missing))
        unknown_union.update(missing)

    if not row_payloads:
        return result_df

    if len(row_payloads) > MAX_GEMINI_ROWS:
        print(
            f"  [GEMINI] Skipping fallback: {len(row_payloads)} row(s) need enrichment, "
            f"above MAX_GEMINI_ROWS={MAX_GEMINI_ROWS}"
        )
        return result_df

    unknown_fields = sorted(unknown_union)

    print(f"  [GEMINI] JSON fallback enrichment: {len(row_payloads)} row(s), fields={unknown_fields}")

    resolved = _resolve_via_json(row_payloads, unknown_fields, plan_label)

    if not isinstance(resolved, list):
        return result_df

    for n, (idx, missing) in enumerate(row_indices):
        if n >= len(resolved):
            break

        item = resolved[n]

        if not isinstance(item, dict):
            continue

        for field in missing:
            if field not in item:
                continue

            value = item.get(field)

            if _is_unknown(value):
                continue

            _apply_dataframe_value(result_df, idx, field, value)

    return result_df


def _resolve_via_json(rows: list[dict], unknown_fields: list[str], plan_label: str):
    resolved_all = []

    for start in range(0, len(rows), MAX_BATCH_SIZE):
        batch = rows[start:start + MAX_BATCH_SIZE]
        prompt = _build_prompt(batch, unknown_fields, plan_label)

        try:
            result = _call_gemini(prompt)
        except Exception as exc:
            print(f"  [GEMINI] Batch {start} failed: {exc}")
            result = None

        if not isinstance(result, list) or len(result) != len(batch):
            print(f"  [GEMINI] Batch {start} returned invalid shape")
            resolved_all.extend([{} for _ in batch])
        else:
            resolved_all.extend(result)

    return resolved_all


def _detect_missing_dataframe_fields(row: pd.Series, fields: list[str]) -> list[str]:
    missing = []

    for field in fields:
        value = row.get(field)

        if field in ["channel", "partner"]:
            if _is_unknown(value) or _looks_like_bad_partner(value):
                missing.append(field)

        elif field in ["start_date", "end_date", "flight_start", "flight_end"]:
            if _is_unknown(value) or pd.isna(pd.to_datetime(value, errors="coerce")):
                missing.append(field)

        elif field in ["gross_media", "net_media", "impressions", "cpm"]:
            if _safe_number(value) in ["", 0.0]:
                missing.append(field)

        elif _is_unknown(value):
            missing.append(field)

    return missing


def _dataframe_row_to_payload(row: pd.Series, df: pd.DataFrame | None = None, idx=None) -> dict:
    payload = {
        "client": _safe_str(row.get("client")),
        "channel": _safe_str(row.get("channel")),
        "partner": _safe_str(row.get("partner")),
        "campaign_name": _safe_str(row.get("campaign_name")),
        "placement_name": _safe_str(row.get("placement_name")),
        "targeting": _safe_str(row.get("targeting"))[:300],
        "kpi": _safe_str(row.get("kpi")),
        "buy_type": _safe_str(row.get("buy_type")),
        "start_date": _safe_str(row.get("start_date")),
        "end_date": _safe_str(row.get("end_date")),
        "flight_start": _safe_str(row.get("flight_start")),
        "flight_end": _safe_str(row.get("flight_end")),
        "gross_media": _safe_str(row.get("gross_media")),
        "net_media": _safe_str(row.get("net_media")),
        "planned_amount": _safe_str(row.get("planned_amount")),
        "impressions": _safe_str(row.get("impressions")),
        "planned_units": _safe_str(row.get("planned_units")),
        "cpm": _safe_str(row.get("cpm")),
        "unit_rate": _safe_str(row.get("unit_rate")),
        "currency": _safe_str(row.get("currency")),
        "source_sheet": _safe_str(row.get("source_sheet")),
        "source_file": _safe_str(row.get("source_file")),
    }

    if df is not None and idx is not None:
        payload["row_context"] = _nearby_text_context(df, idx)

    return payload


def _nearby_text_context(df: pd.DataFrame, idx, window: int = 2) -> list[dict]:
    try:
        positions = list(df.index)
        pos = positions.index(idx)
    except Exception:
        return []

    start = max(0, pos - window)
    end = min(len(positions), pos + window + 1)

    context = []

    for nearby_idx in positions[start:end]:
        row = df.loc[nearby_idx]
        text_parts = []

        for col, value in row.items():
            value_text = _safe_str(value)

            if not value_text:
                continue

            if len(value_text) > 120:
                value_text = value_text[:120]

            text_parts.append(f"{col}: {value_text}")

        if text_parts:
            context.append(
                {
                    "row_index": str(nearby_idx),
                    "text": " | ".join(text_parts)[:1000],
                }
            )

    return context


def _apply_dataframe_value(df: pd.DataFrame, idx, field: str, value: Any) -> None:
    if field == "partner":
        value = _canonical_partner(value)

        if value not in ALLOWED_PARTNERS:
            return

    elif field == "channel":
        value = _safe_str(value)

    elif field in ["cost_method", "currency"]:
        value = _safe_str(value).upper()

    elif field in ["start_date", "end_date", "flight_start", "flight_end"]:
        parsed = pd.to_datetime(value, errors="coerce")

        if not pd.isna(parsed):
            value = parsed.strftime("%Y-%m-%d")
        else:
            return

    elif field in ["gross_media", "net_media", "impressions", "cpm"]:
        value = _safe_number(value)

        if value == "":
            return

    if _is_unknown(value):
        return

    if field in ["partner", "channel"] and _looks_like_bad_partner(value):
        return

    if field not in df.columns:
        df[field] = ""

    df.at[idx, field] = value


def enrich_placements(
    placements: list,
    plan_label: str = "",
    xlsx_path: str | None = None,
) -> list:
    if not placements or not is_available():
        return placements

    rows_to_send = []
    indices = []
    unknown_union = set()

    for i, placement in enumerate(placements):
        missing = _detect_missing_placement_fields(placement)

        if missing:
            rows_to_send.append(_placement_to_dict(placement))
            indices.append((i, missing))
            unknown_union.update(missing)

    if not rows_to_send:
        return placements

    if len(rows_to_send) > MAX_GEMINI_ROWS:
        print(
            f"  [GEMINI] Skipping placement fallback: {len(rows_to_send)} row(s), "
            f"above MAX_GEMINI_ROWS={MAX_GEMINI_ROWS}"
        )
        return placements

    unknown_fields = sorted(unknown_union)

    print(f"  [GEMINI] Placement JSON fallback: {len(rows_to_send)} placement(s), fields={unknown_fields}")

    resolved = _resolve_via_json(rows_to_send, unknown_fields, plan_label)

    if not isinstance(resolved, list):
        return placements

    for n, (orig_idx, missing) in enumerate(indices):
        if n >= len(resolved):
            break

        item = resolved[n]

        if not isinstance(item, dict):
            continue

        placement = placements[orig_idx]

        for field in missing:
            value = item.get(field, "")

            if not _is_unknown(value):
                _apply_placement_value(placement, field, value)

    return placements


def _detect_missing_placement_fields(placement) -> list[str]:
    missing = []

    checks = {
        "channel": getattr(placement, "channel", None),
        "cost_method": getattr(placement, "cost_method", None),
        "objective": getattr(placement, "objective", None),
        "currency": getattr(placement, "currency", None),
        "flight_start": getattr(placement, "flight_start", None),
        "flight_end": getattr(placement, "flight_end", None),
    }

    for field, value in checks.items():
        if _is_unknown(value):
            missing.append(field)

    if _looks_like_bad_partner(getattr(placement, "channel", None)) and "channel" not in missing:
        missing.append("channel")

    return missing


def _placement_to_dict(placement) -> dict:
    return {
        "channel": _safe_str(getattr(placement, "channel", "")),
        "partner": _safe_str(getattr(placement, "partner", "")),
        "campaign_name": _safe_str(getattr(placement, "campaign_name", "")),
        "placement_name": _safe_str(getattr(placement, "placement_name", "")),
        "objective": _safe_str(getattr(placement, "objective", "")),
        "cost_method": _safe_str(getattr(placement, "cost_method", "")),
        "currency": _safe_str(getattr(placement, "currency", "")),
        "planned_amount": _safe_str(getattr(placement, "planned_amount", "")),
        "unit_rate": _safe_str(getattr(placement, "unit_rate", "")),
        "flight_start": _safe_str(getattr(placement, "flight_start", "")),
        "flight_end": _safe_str(getattr(placement, "flight_end", "")),
        "os": _safe_str(getattr(placement, "os", "")),
        "ad_format": _safe_str(getattr(placement, "ad_format", "")),
        "targeting": _safe_str(getattr(placement, "targeting", ""))[:300],
    }


def _apply_placement_value(placement, field: str, value: Any) -> None:
    if field == "cost_method":
        value = _safe_str(value).upper()

    elif field == "currency":
        value = _safe_str(value).upper()[:3]

    elif field == "partner":
        value = _canonical_partner(value)

        if value not in ALLOWED_PARTNERS:
            return

    else:
        value = _safe_str(value)

    if _is_unknown(value):
        return

    if field in ["partner", "channel"] and _looks_like_bad_partner(value):
        return

    setattr(placement, field, value)


def build_buying_guide_gap_report(
    preview_errors: list[dict],
    consolidated_records: list[dict] | None = None,
    plan_label: str = "",
) -> list[dict]:
    if not preview_errors or not is_available():
        return _deterministic_gap_report(preview_errors)

    payload = []

    consolidated_records = consolidated_records or []

    for row in preview_errors:
        client = _safe_str(row.get("client"))
        partner = _safe_str(row.get("partner"))
        placement_name = _safe_str(row.get("placement_name"))
        planned_amount = _safe_str(row.get("planned_amount"))
        planned_units = _safe_str(row.get("planned_units"))
        status = _safe_str(row.get("status"))

        related_records = [
            record for record in consolidated_records
            if _safe_str(record.get("client")).upper() == client.upper()
            and _safe_str(record.get("partner")).lower() == partner.lower()
        ]

        evidence = []

        for record in related_records[:5]:
            evidence.append(
                {
                    "placement_name": _safe_str(record.get("placement_name")),
                    "campaign_name": _safe_str(record.get("campaign_name")),
                    "channel": _safe_str(record.get("channel")),
                    "partner": _safe_str(record.get("partner")),
                    "planned_amount": _safe_str(record.get("planned_amount")),
                    "planned_units": _safe_str(record.get("planned_units")),
                }
            )

        payload.append(
            {
                "client": client,
                "missing_partner": partner,
                "placement_name": placement_name,
                "planned_amount": planned_amount,
                "planned_units": planned_units,
                "error": status,
                "evidence": evidence,
            }
        )

    prompt = _build_buying_guide_gap_prompt(payload, plan_label)

    try:
        result = _call_gemini(prompt)
    except Exception as exc:
        print(f"  [GEMINI] Buying Guide gap advisor failed: {exc}")
        return _deterministic_gap_report(preview_errors)

    if not isinstance(result, list):
        return _deterministic_gap_report(preview_errors)

    cleaned = []

    for item in result:
        if not isinstance(item, dict):
            continue

        cleaned.append(_clean_gap_recommendation(item))

    if not cleaned:
        return _deterministic_gap_report(preview_errors)

    return cleaned


def _build_buying_guide_gap_prompt(rows: list[dict], plan_label: str = "") -> str:
    hint = PLAN_HINTS.get(plan_label, "")
    allowed_partners = ", ".join(ALLOWED_PARTNERS)

    return f"""
You are a media operations assistant helping prepare a Buying Guide gap report.

{hint}

You will receive unmatched media-plan partners that failed Buying Guide matching.

Your job:
- Suggest what Buying Guide row may need to be added.
- Do not invent supplier codes.
- Do not invent supplier IDs.
- Do not invent supplier names.
- Do not invent financial buy type.
- Do not invent buy category.
- Do not approve the row.
- This is only a human-review recommendation report.

Allowed canonical partners:
{allowed_partners}

Return a JSON array with one object per input item, in the same order.

Each object must contain exactly these keys:
- client
- missing_partner
- suggested_placement_booking_type
- suggested_aliases
- suggested_cost_method
- suggested_unit_type
- confidence
- evidence_summary
- required_human_action
- do_not_auto_export_reason
- suggested_buying_guide_row_status
- safe_to_auto_export

Rules:
- suggested_cost_method should usually be CPM unless evidence suggests otherwise.
- suggested_unit_type should usually be Impressions unless evidence suggests otherwise.
- confidence must be High, Medium, or Low.
- suggested_aliases must be a short comma-separated string.
- required_human_action must tell the user to add an approved Buying Guide row.
- do_not_auto_export_reason must explain that supplier code/name and finance fields must come from the official Buying Guide.
- suggested_buying_guide_row_status must be "Needs finance approval".
- safe_to_auto_export must be "No".
- Return only JSON.

Input:
{json.dumps(rows, indent=2, default=str)}
""".strip()


def _clean_gap_recommendation(item: dict) -> dict:
    client = _safe_str(item.get("client"))
    missing_partner = _canonical_partner(item.get("missing_partner"))

    if missing_partner not in ALLOWED_PARTNERS:
        missing_partner = _safe_str(item.get("missing_partner"))

    confidence = _safe_str(item.get("confidence")).title()

    if confidence not in {"High", "Medium", "Low"}:
        confidence = "Medium"

    return {
        "client": client,
        "missing_partner": missing_partner,
        "suggested_placement_booking_type": _safe_str(item.get("suggested_placement_booking_type")) or missing_partner,
        "suggested_aliases": _safe_str(item.get("suggested_aliases")) or _default_aliases_for_partner(missing_partner),
        "suggested_cost_method": _safe_str(item.get("suggested_cost_method")).upper() or "CPM",
        "suggested_unit_type": _safe_str(item.get("suggested_unit_type")) or "Impressions",
        "confidence": confidence,
        "evidence_summary": _safe_str(item.get("evidence_summary")),
        "required_human_action": _safe_str(item.get("required_human_action")) or "Add an approved Buying Guide row for this client and partner.",
        "do_not_auto_export_reason": _safe_str(item.get("do_not_auto_export_reason")) or "Supplier code, supplier name, financial buy type, currency, and finance fields must come from the official Buying Guide.",
        "suggested_buying_guide_row_status": "Needs finance approval",
        "safe_to_auto_export": "No",
    }


def _deterministic_gap_report(preview_errors: list[dict]) -> list[dict]:
    rows = []

    for row in preview_errors:
        client = _safe_str(row.get("client"))
        partner = _canonical_partner(row.get("partner"))

        if partner not in ALLOWED_PARTNERS:
            partner = _safe_str(row.get("partner"))

        aliases = _default_aliases_for_partner(partner)

        rows.append(
            {
                "client": client,
                "missing_partner": partner,
                "suggested_placement_booking_type": partner,
                "suggested_aliases": aliases,
                "suggested_cost_method": "CPM",
                "suggested_unit_type": "Impressions",
                "confidence": "Medium",
                "evidence_summary": f"Buying Guide matching failed for client={client}, partner={partner}.",
                "required_human_action": "Add an approved Buying Guide row for this client and partner.",
                "do_not_auto_export_reason": "Supplier code, supplier name, financial buy type, currency, and finance fields must come from the official Buying Guide.",
                "suggested_buying_guide_row_status": "Needs finance approval",
                "safe_to_auto_export": "No",
            }
        )

    return rows


def _default_aliases_for_partner(partner: str) -> str:
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
