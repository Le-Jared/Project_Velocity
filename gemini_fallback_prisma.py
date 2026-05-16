import os
import re
import json
import time
import pathlib
from google import genai
from google.genai import types

from plan_adapters import Placement


GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL    = "gemini-2.5-flash"
MAX_BATCH_SIZE  = 25
UNKNOWN_VALUES  = ("UNKNOWN", "", None, 0, 0.0)

_client = None


def _get_client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("[GEMINI] GEMINI_API_KEY not set.")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def is_available() -> bool:
    return bool(GEMINI_API_KEY)


def _parse_json(raw: str):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    print(f"  [GEMINI] Could not parse JSON:\n  {raw[:300]}")
    return None


FIELD_DESCRIPTIONS = {
    "channel":      "Normalized channel/publisher name (e.g. 'Google Search', 'Meta Traffic', 'TikTok Smart+', 'Apple Search Ads').",
    "cost_method":  "Billing model: one of CPM, CPC, CPI, CPV, CPT.",
    "objective":    "Campaign objective (e.g. Awareness, Traffic, Conversion, App Install, Registration).",
    "currency":     "3-letter ISO currency code (USD, SGD, IDR, MYR, HKD, JPY).",
    "flight_start": "Campaign start date in YYYY-MM-DD format.",
    "flight_end":   "Campaign end date in YYYY-MM-DD format.",
    "os":           "Target OS: iOS, Android, or empty if not applicable.",
}

PLAN_HINTS = {
    "SkillIgnition": "This is a SkillIgnition media plan (client GU). Channels include Facebook, Tiktok, Google Search, etc.",
    "MCP 2026":      "This is an MCP 2026 mobile media plan (client MCP). Currency is typically SGD.",
    "MI / Mercari":  "This is a Mercari/MI media plan. Channels use 'Publisher Product' naming like 'Google Search', 'UAC Install iOS', 'Meta Traffic'.",
}

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_MIME  = "application/vnd.ms-excel"


def _build_prompt(rows: list[dict], unknown_fields: list[str], plan_label: str = "") -> str:
    field_lines = "\n".join(
        f'  - "{f}": {FIELD_DESCRIPTIONS[f]}'
        for f in unknown_fields if f in FIELD_DESCRIPTIONS
    )
    hint = PLAN_HINTS.get(plan_label, "")

    return f"""You are an expert media-planning data normalizer for an advertising agency.

{hint}

You will receive a JSON array of placement rows extracted from a media plan.
For each row, fill in ONLY the fields listed below where they are currently empty or unclear.

Fields to resolve:
{field_lines}

Rules:
- Return a JSON ARRAY with one object per input row, in the same order.
- Each object must contain ONLY the resolved keys: {unknown_fields}
- If a field cannot be determined for a row, return "" for it.
- cost_method must be one of: CPM, CPC, CPI, CPV, CPT.
- Dates must be ISO format YYYY-MM-DD.
- channel must be a clean, canonical name (no extra punctuation or campaign codes).
- Return ONLY the JSON array. No explanation, no markdown.

Input placements:
{json.dumps(rows, indent=2, default=str)}
"""


def _build_xlsx_prompt(unknown_fields: list[str], plan_label: str = "") -> str:
    field_lines = "\n".join(
        f'  - "{f}": {FIELD_DESCRIPTIONS[f]}'
        for f in unknown_fields if f in FIELD_DESCRIPTIONS
    )
    hint = PLAN_HINTS.get(plan_label, "")

    return f"""You are an expert media-planning data normalizer for an advertising agency.

{hint}

The attached file is a media plan spreadsheet. Read ALL rows and sheets carefully,
including merged cells, header rows, and any campaign/flight date context.

For every placement row you can identify, extract the following fields:

Fields to resolve:
{field_lines}

Rules:
- Return a JSON ARRAY — one object per placement row, in sheet order.
- Each object must contain ONLY these keys: {unknown_fields}
- If a field cannot be determined for a row, return "" for it.
- cost_method must be one of: CPM, CPC, CPI, CPV, CPT.
- Dates must be ISO format YYYY-MM-DD.
- channel must be a clean, canonical name (no extra punctuation or campaign codes).
- Return ONLY the JSON array. No explanation, no markdown.
"""


def _call_gemini(prompt: str) -> list | None:
    client = _get_client()
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            return _parse_json(response.text)
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                wait = 2 ** attempt * 5
                print(f"  [GEMINI] Rate limited — retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    return None


def _call_gemini_xlsx(xlsx_path: str, prompt: str) -> list | None:
    client    = _get_client()
    xlsx_data = pathlib.Path(xlsx_path).read_bytes()
    mime      = XLSX_MIME if xlsx_path.lower().endswith(".xlsx") else XLS_MIME
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=xlsx_data, mime_type=mime),
                    prompt,
                ],
            )
            return _parse_json(response.text)
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                wait = 2 ** attempt * 5
                print(f"  [GEMINI] Rate limited — retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    return None


def enrich_placements(
    placements: list[Placement],
    plan_label: str = "",
    xlsx_path:  str = None,
) -> list[Placement]:
    """
    Enrich placements with Gemini-resolved values for any blank/unknown fields.

    If xlsx_path is provided, Gemini reads the raw spreadsheet directly for
    full context (merged cells, header rows, flight dates, etc.) before falling
    back to the compact JSON row approach.

    Returns the same list (mutated in place + returned for chaining).
    """
    if not placements or not is_available():
        return placements

    rows_to_send:  list[dict] = []
    indices:       list[tuple] = []
    unknown_union: set[str]   = set()

    for i, p in enumerate(placements):
        missing = _detect_missing(p)
        if missing:
            rows_to_send.append(_placement_to_dict(p))
            indices.append((i, missing))
            unknown_union.update(missing)

    if not rows_to_send:
        return placements

    unknown_fields = sorted(unknown_union)

    if xlsx_path and pathlib.Path(xlsx_path).exists():
        print(f"  [GEMINI] Enriching {len(rows_to_send)} placement(s) via XLSX — fields: {unknown_fields}")
        _enrich_via_xlsx(placements, indices, unknown_fields, plan_label, xlsx_path)
    else:
        print(f"  [GEMINI] Enriching {len(rows_to_send)} placement(s) via JSON — fields: {unknown_fields}")
        _enrich_via_json(placements, rows_to_send, indices, unknown_fields, plan_label)

    return placements


def _enrich_via_xlsx(
    placements:     list[Placement],
    indices:        list[tuple],
    unknown_fields: list[str],
    plan_label:     str,
    xlsx_path:      str,
) -> None:
    """
    Send the raw XLSX to Gemini and map its response back to placements by position.
    Falls back to JSON mode if the XLSX call fails or returns wrong shape.
    """
    prompt = _build_xlsx_prompt(unknown_fields, plan_label)
    try:
        result = _call_gemini_xlsx(xlsx_path, prompt)
    except Exception as e:
        print(f"  [GEMINI] XLSX call failed: {e} — falling back to JSON mode")
        result = None

    if not isinstance(result, list):
        print(f"  [GEMINI] XLSX response invalid — falling back to JSON mode")
        rows_to_send = [_placement_to_dict(placements[i]) for i, _ in indices]
        _enrich_via_json(placements, rows_to_send, indices, unknown_fields, plan_label)
        return

    # Gemini returns one object per placement row in sheet order.
    # Map back by position — indices[n] corresponds to result[n].
    for n, (orig_idx, missing) in enumerate(indices):
        if n >= len(result):
            break
        resolved = result[n]
        if not resolved:
            continue
        p = placements[orig_idx]
        for field in missing:
            value = str(resolved.get(field, "")).strip()
            if value and value.upper() not in ("UNKNOWN", "NONE", "N/A"):
                _apply(p, field, value)


def _enrich_via_json(
    placements:     list[Placement],
    rows_to_send:   list[dict],
    indices:        list[tuple],
    unknown_fields: list[str],
    plan_label:     str,
) -> None:
    """Original compact-JSON batch approach."""
    resolved_all: list[dict] = []

    for start in range(0, len(rows_to_send), MAX_BATCH_SIZE):
        batch  = rows_to_send[start : start + MAX_BATCH_SIZE]
        prompt = _build_prompt(batch, unknown_fields, plan_label=plan_label)
        try:
            result = _call_gemini(prompt)
        except Exception as e:
            print(f"  [GEMINI] Batch failed ({start}): {e}")
            result = None

        if not isinstance(result, list) or len(result) != len(batch):
            print(f"  [GEMINI] Batch {start} returned unexpected shape — skipping")
            resolved_all.extend([{} for _ in batch])
        else:
            resolved_all.extend(result)

    for (orig_idx, missing), resolved in zip(indices, resolved_all):
        if not resolved:
            continue
        p = placements[orig_idx]
        for field in missing:
            value = str(resolved.get(field, "")).strip()
            if value and value.upper() not in ("UNKNOWN", "NONE", "N/A"):
                _apply(p, field, value)


def _detect_missing(p: Placement) -> list[str]:
    missing = []
    if not p.channel or p.channel.strip().upper() in ("UNKNOWN", ""):
        missing.append("channel")
    if not p.cost_method or p.cost_method.upper() in ("UNKNOWN", ""):
        missing.append("cost_method")
    if not p.objective:
        missing.append("objective")
    if not p.currency or p.currency.upper() in ("UNKNOWN", ""):
        missing.append("currency")
    if not p.flight_start:
        missing.append("flight_start")
    if not p.flight_end:
        missing.append("flight_end")
    return missing


def _placement_to_dict(p: Placement) -> dict:
    return {
        "channel":         p.channel,
        "campaign_name":   p.campaign_name,
        "placement_name":  p.placement_name,
        "objective":       p.objective,
        "cost_method":     p.cost_method,
        "currency":        p.currency,
        "planned_amount":  p.planned_amount,
        "unit_rate":       p.unit_rate,
        "flight_start":    p.flight_start,
        "flight_end":      p.flight_end,
        "os":              p.os,
        "ad_format":       p.ad_format,
        "targeting":       (p.targeting or "")[:200],
    }


def _apply(p: Placement, field: str, value: str) -> None:
    if field == "cost_method":
        p.cost_method = value.upper()
    elif field == "currency":
        p.currency = value.upper()[:3]
    elif field == "os":
        p.os = value
    else:
        setattr(p, field, value)