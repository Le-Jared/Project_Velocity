import os
import re
import json
import time
import pathlib
from google import genai
from google.genai import types

GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL    = "gemini-2.5-flash"
MAX_TEXT_CHARS  = 6000

_client = None


def _get_client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("[GEMINI] GEMINI_API_KEY not set.")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    print(f"  [GEMINI] Could not parse JSON:\n  {raw[:300]}")
    return {}


def _build_prompt(supplier: str, fields: list[str], text: str = "") -> str:
    field_lines   = "\n".join(f'  - "{f}": {FIELD_DESCRIPTIONS[f]}' for f in fields if f in FIELD_DESCRIPTIONS)
    supplier_hint = SUPPLIER_HINTS.get(supplier, "")
    body          = f"Invoice text:\n---\n{text[:MAX_TEXT_CHARS]}\n---" if text else ""

    return f"""You are an expert invoice data extractor for an advertising agency.

{supplier_hint}

Extract ONLY the following fields.
Return a single valid JSON object with exactly these keys: {fields}

Field definitions:
{field_lines}

Rules:
- If a field cannot be determined, return "".
- Return ONLY the JSON object. No explanation, no markdown, no code fences.
- client and market must be UPPERCASE.
- month must be a full month name (e.g. March), not a number or abbreviation.
- year must be 4 digits (e.g. 2026).
- amount must be a plain decimal number with no currency symbols (e.g. 67113.00).

{body}
"""


def _call_text(prompt: str) -> dict:
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
    return {}


def _call_pdf(pdf_path: str, prompt: str) -> dict:
    client   = _get_client()
    pdf_data = pathlib.Path(pdf_path).read_bytes()
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=pdf_data, mime_type="application/pdf"),
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
    return {}


FIELD_DESCRIPTIONS = {
    "client":         "The short client/advertiser code (2–6 uppercase letters, e.g. BHC, MF, GT, CFTH). NOT the agency name (M&C Saatchi).",
    "market":         "The 2-letter country/market code (e.g. SG, MY, ID, TH, PH, AU, GB, US).",
    "month":          "The full month name of the billing/service period (e.g. March, April). NOT a number.",
    "year":           "The 4-digit year of the billing/service period (e.g. 2026).",
    "invoice_number": "The invoice number or reference code exactly as printed.",
    "currency":       "The 3-letter ISO currency code (e.g. SGD, IDR, MYR, USD).",
    "amount":         "The total invoice amount as a plain decimal number (e.g. 67113.00). No currency symbols or commas.",
}

SUPPLIER_HINTS = {
    "meta":   "This is a Meta (Facebook) Ads invoice. Client codes appear in campaign names like mcspapac_MY_F0032_..._LGL_... where MY=market, LGL=client. "
              "Also check for a standalone 13–15 digit Account Id number anywhere on the page — it may appear as a loose line, not in a labelled field.",
    "google":  "This is a Google Ads invoice. Client codes appear in campaign names like MCSP_ID_BHC_ where ID=market, BHC=client.",
    "apple":   "This is an Apple Search Ads invoice. The client code is a 2–4 letter code near 'Client :' or 'Order Number' fields.",
    "adsjoy":  "This is an AdsJoy Digital invoice. The client code is a 2–4 letter code near 'For ADSJOY DIGITAL' in the document.",
}

UNKNOWN_VALUES = ("UNKNOWN", "", None)


def resolve_unknown_fields(
    text:     str,
    supplier: str,
    fields:   list[str],
    pdf_path: str = None,
) -> dict:
    if not fields:
        return {}
    if not GEMINI_API_KEY:
        print("  [GEMINI] API key not configured — skipping")
        return {}

    # ✅ Always use PDF when available — gives Gemini full visual + structural context
    use_pdf = bool(pdf_path and pathlib.Path(pdf_path).exists())
    mode    = "PDF" if use_pdf else "text"
    prompt  = _build_prompt(supplier, fields, text if not use_pdf else "")

    print(f"  [GEMINI] Resolving {fields} via {mode} for [{supplier.upper()}]...")

    try:
        raw = _call_pdf(pdf_path, prompt) if use_pdf else _call_text(prompt)
        out = {}
        for f in fields:
            val = str(raw.get(f, "")).strip()
            out[f] = val
            print(f"  [GEMINI] {f} = {repr(val)}")
        return out
    except Exception as e:
        print(f"  [GEMINI] Error: {e}")
        return {}


def enrich_extraction(
    result:   dict,
    text:     str,
    supplier: str,
    pdf_path: str = None,
) -> dict:
    resolvable = set(FIELD_DESCRIPTIONS.keys())
    unknown    = [k for k, v in result.items() if k in resolvable and v in UNKNOWN_VALUES]

    if not unknown:
        return result

    resolved = resolve_unknown_fields(text, supplier, unknown, pdf_path=pdf_path)

    merged = dict(result)
    for field, value in resolved.items():
        if value and value not in UNKNOWN_VALUES:
            merged[field] = value

    return merged


def is_available() -> bool:
    return bool(GEMINI_API_KEY)