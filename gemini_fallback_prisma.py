"""
Gemini fallback for media plan parsing.
Mirrors the design of gemini_fallback.py but with placement-specific prompts.

Used by app.py /api/prisma/convert when adapters leave fields blank.
"""
import os
import re
import json
from typing import Optional
from google import genai

from plan_adapters import Placement


GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL    = "gemini-1.5-flash"
MAX_BATCH_SIZE  = 25         # placements per Gemini call
UNKNOWN_VALUES  = ("UNKNOWN", "", None, 0, 0.0)

_client = None


# ── Client init (matches gemini_fallback.py pattern) ─────────────────────────

def _get_client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("[GEMINI] GEMINI_API_KEY not set.")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def is_available() -> bool:
    return bool(GEMINI_API_KEY)


# ── JSON parsing (identical to gemini_fallback.py) ───────────────────────────

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


# ── Field definitions (Prisma-specific) ──────────────────────────────────────

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


# ── Prompt builder ───────────────────────────────────────────────────────────

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


# ── Core Gemini call ─────────────────────────────────────────────────────────

def _call_gemini(prompt: str):
    client   = _get_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )
    return _parse_json(response.text)


# ── Public API ───────────────────────────────────────────────────────────────

def enrich_placements(
    placements: list[Placement],
    plan_label: str = "",
) -> list[Placement]:
    """
    Enrich placements with Gemini-resolved values for any blank/unknown fields.
    Returns the same list (mutated in place + returned for chaining).
    """
    if not placements or not is_available():
        return placements

    # Build a row-level view of what's missing for each placement
    rows_to_send  = []
    indices       = []
    unknown_union: set[str] = set()

    for i, p in enumerate(placements):
        missing = _detect_missing(p)
        if missing:
            rows_to_send.append(_placement_to_dict(p))
            indices.append((i, missing))
            unknown_union.update(missing)

    if not rows_to_send:
        return placements

    unknown_fields = sorted(unknown_union)
    print(f"  [GEMINI] Enriching {len(rows_to_send)} placement(s) — fields: {unknown_fields}")

    # Batch in chunks of MAX_BATCH_SIZE to keep prompts manageable
    resolved_all: list[dict] = []
    for start in range(0, len(rows_to_send), MAX_BATCH_SIZE):
        batch = rows_to_send[start : start + MAX_BATCH_SIZE]
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

    # Merge resolved values back into the original placements
    for (orig_idx, missing), resolved in zip(indices, resolved_all):
        if not resolved:
            continue
        p = placements[orig_idx]
        for field in missing:
            value = str(resolved.get(field, "")).strip()
            if value and value.upper() not in ("UNKNOWN", "NONE", "N/A"):
                _apply(p, field, value)

    return placements


# ── Helpers ──────────────────────────────────────────────────────────────────

def _detect_missing(p: Placement) -> list[str]:
    """Return the list of fields that look unset/unknown on this placement."""
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
    """Compact view of a placement for the prompt context."""
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
    """Safely write a string value to the placement, coercing where needed."""
    if field == "cost_method":
        p.cost_method = value.upper()
    elif field == "currency":
        p.currency = value.upper()[:3]
    elif field == "os":
        p.os = value
    else:
        setattr(p, field, value)
