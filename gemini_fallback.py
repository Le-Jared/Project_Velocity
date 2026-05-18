import os
import re
import json
import time
import pathlib
from google import genai
from google.genai import types


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_TEXT_CHARS = int(os.environ.get("GEMINI_MAX_TEXT_CHARS", "9000"))
GEMINI_ENABLED = os.environ.get("GEMINI_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}

_client = None

UNKNOWN_VALUES = {"UNKNOWN", "UNKNOWN SUPPLIER", "", None}

FIELD_DESCRIPTIONS = {
    "client": "The short client or advertiser code. Usually 2–10 uppercase letters or a known client name. Examples: BHC, LGL, MF, PD, GT, GU, OG, AMA, AFID, BMYFF, FJPH, CFTH, FSG, PSN, PPTC, SHL, GF, PS PTE LTD. Do not return M&C Saatchi, Saatchi, agency names, billing names, bank names, address words, or legal entity names unless the actual client is PS PTE LTD.",
    "market": "The market/country code for the client or campaign. Usually SG, MY, ID, TH, PH, MX, AU, GB, US, or a currency folder value such as USD if the workflow stores USD invoices under USD.",
    "month": "The full month name of the billing or service period. Example: March. Do not return a number or abbreviation.",
    "year": "The 4-digit year of the billing or service period. Example: 2026.",
    "invoice_number": "The invoice number, transaction number, or reference code exactly as printed. Examples: 2230266840, 5534861618, Q201038855, 26-27/Apr/10.",
    "currency": "The 3-letter ISO currency code. Examples: USD, SGD, IDR, MYR, GBP, AUD, PHP.",
    "amount": "The total invoice amount as a plain decimal number with no currency symbols or commas. Example: 67113.00.",
    "supplier": "The supplier name. Use one of: Meta, Google, Apple, AdsJoy.",
    "campaign": "The campaign or placement name exactly as shown on the invoice line item.",
    "campaign_id": "The campaign ID if shown. For Meta, this may appear inside angle brackets such as <MY24Q3LEFCCACSUSTENANCE>.",
    "ad_account_id": "The ad account ID if shown. For Meta, this is often a 12–15 digit number.",
    "ad_account_name": "The Google or Apple account name if shown.",
}

SUPPLIER_HINTS = {
    "meta": (
        "This is a Meta or Facebook Ads invoice. Client and market are usually inside campaign names. "
        "Patterns include mcspapac_MY_..._LGL_... where MY is market and LGL is client; "
        "MCSP_SG_PSN_... where SG is market and PSN is client; "
        "RKU_TH_FBIG_CFTH where TH is market and CFTH is client. "
        "For Meta invoices, invoice number may appear after Invoice # or in a Transaction filename. "
        "Account IDs may appear as 12 to 15 digit standalone numbers. "
        "Do not confuse Facebook billing entity country with campaign/client market if campaign market is available."
    ),
    "google": (
        "This is a Google Ads invoice. Client and market often appear in campaign names like "
        "MCSP_ID_AMA_, MCSP_MY_BMYFF_, MCSP_PH_FJPH_, or mcsp_AFID_. "
        "Google invoice numbers are usually 10 digits. "
        "For USD Google invoices, the workflow may use market USD if the foldering is currency-based."
    ),
    "apple": (
        "This is an Apple Search Ads invoice. Invoice numbers usually start with Q. "
        "Client may appear near Client, Order Number, or in campaign strings like "
        "1798524137SG-MCSP_ASA_MF_... where SG is market and MF is client, or "
        "1824163624MX-MCSPPD586_... where MX is market and PD is client."
    ),
    "adsjoy": (
        "This is an AdsJoy Digital invoice. The client code may appear in the filename, for example "
        "Adsjoy_MC_SAATCHI_GT_Mar_26_10 means client GT. "
        "It may also appear near For ADSJOY DIGITAL. "
        "Never use BANK as the client. If BANK appears, inspect filename or invoice details for GT, GU, or OG. "
        "Invoice numbers look like 26-27/Apr/10, 26-27/Apr/05, or 26-27/May/12."
    ),
}

SUPPLIER_NORMALIZATION = {
    "META": "Meta",
    "FACEBOOK": "Meta",
    "META FACEBOOK": "Meta",
    "META (FACEBOOK)": "Meta",
    "GOOGLE": "Google",
    "GOOGLE ADS": "Google",
    "APPLE": "Apple",
    "APPLE ASA": "Apple",
    "APPLE SEARCH ADS": "Apple",
    "APPLE (ASA)": "Apple",
    "ADSJOY": "AdsJoy",
    "ADSJOY DIGITAL": "AdsJoy",
}

CLIENT_NORMALIZATION = {
    "AMA PROSPER": "AMA",
    "AMAPROSPER": "AMA",
    "AMA": "AMA",
    "PS PTE. LTD.": "PS PTE LTD",
    "PS PTE LTD": "PS PTE LTD",
    "PS PTE": "PS PTE LTD",
    "BANK": "",
    "ACCOUNT": "",
    "INVOICE": "",
    "TOTAL": "",
    "NAME": "",
    "ADDRESS": "",
    "NUMBER": "",
    "THE": "",
    "AND": "",
    "ID": "",
}

MARKET_NORMALIZATION = {
    "INDONESIA": "ID",
    "MALAYSIA": "MY",
    "SINGAPORE": "SG",
    "THAILAND": "TH",
    "PHILIPPINES": "PH",
    "MEXICO": "MX",
    "AUSTRALIA": "AU",
    "UNITED KINGDOM": "GB",
    "UK": "GB",
    "GREAT BRITAIN": "GB",
    "UNITED STATES": "US",
    "USA": "US",
}


def _get_client():
    global _client

    if not GEMINI_ENABLED:
        raise RuntimeError("[GEMINI] Disabled.")

    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("[GEMINI] GEMINI_API_KEY not set.")

        _client = genai.Client(api_key=GEMINI_API_KEY)

    return _client


def _clean_code_value(value):
    value = str(value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _normalize_supplier(value):
    value = _clean_code_value(value)
    upper = value.upper()
    return SUPPLIER_NORMALIZATION.get(upper, value)


def _normalize_client(value):
    value = _clean_code_value(value)
    upper = value.upper()
    return CLIENT_NORMALIZATION.get(upper, upper)


def _normalize_market(value):
    value = _clean_code_value(value)
    upper = value.upper()
    return MARKET_NORMALIZATION.get(upper, upper)


def _normalize_month(value):
    value = _clean_code_value(value)

    if not value:
        return ""

    month_map = {
        "JAN": "January",
        "JANUARY": "January",
        "FEB": "February",
        "FEBRUARY": "February",
        "MAR": "March",
        "MARCH": "March",
        "APR": "April",
        "APRIL": "April",
        "MAY": "May",
        "JUN": "June",
        "JUNE": "June",
        "JUL": "July",
        "JULY": "July",
        "AUG": "August",
        "AUGUST": "August",
        "SEP": "September",
        "SEPT": "September",
        "SEPTEMBER": "September",
        "OCT": "October",
        "OCTOBER": "October",
        "NOV": "November",
        "NOVEMBER": "November",
        "DEC": "December",
        "DECEMBER": "December",
    }

    return month_map.get(value.upper(), value)


def _normalize_currency(value):
    value = _clean_code_value(value).upper()
    match = re.search(r"\b(USD|SGD|MYR|IDR|AUD|GBP|PHP|INR|MXN)\b", value)
    return match.group(1) if match else value


def _normalize_amount(value):
    if value in UNKNOWN_VALUES:
        return ""

    value = str(value).strip()

    if not value:
        return ""

    negative = value.startswith("(") and value.endswith(")")
    cleaned = re.sub(r"[^\d.-]", "", value.replace(",", ""))

    if cleaned in {"", ".", "-", "-."}:
        return ""

    try:
        amount = float(cleaned)
        if negative:
            amount = -abs(amount)
        return f"{amount:.2f}"
    except ValueError:
        return ""


def _normalize_invoice_number(value):
    value = _clean_code_value(value)
    return value


def _normalize_field(field, value):
    if value in UNKNOWN_VALUES:
        return ""

    if field == "supplier":
        return _normalize_supplier(value)
    if field == "client":
        return _normalize_client(value)
    if field == "market":
        return _normalize_market(value)
    if field == "month":
        return _normalize_month(value)
    if field == "currency":
        return _normalize_currency(value)
    if field == "amount":
        return _normalize_amount(value)
    if field == "invoice_number":
        return _normalize_invoice_number(value)

    return _clean_code_value(value)


def _parse_json(raw: str) -> dict:
    raw = str(raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)

    if match:
        try:
            data = json.loads(match.group())
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            pass

    print(f"  [GEMINI] Could not parse JSON: {raw[:300]}")
    return {}


def _build_prompt(supplier: str, fields: list[str], text: str = "") -> str:
    supplier_key = str(supplier or "").strip().lower()
    supplier_hint = SUPPLIER_HINTS.get(supplier_key, "")

    safe_fields = [field for field in fields if field in FIELD_DESCRIPTIONS]

    field_lines = "\n".join(
        f'- "{field}": {FIELD_DESCRIPTIONS[field]}'
        for field in safe_fields
    )

    text_block = f"""
Extracted invoice text:
---
{text[:MAX_TEXT_CHARS]}
---
""" if text else ""

    return f"""
You are an expert invoice data extractor for an advertising agency.

Supplier context:
{supplier_hint}

Task:
Extract only these fields:
{safe_fields}

Field definitions:
{field_lines}

Rules:
- Return exactly one valid JSON object.
- Return only the JSON object.
- Do not use markdown.
- Do not add explanations.
- Use exactly these keys: {safe_fields}
- If a field cannot be determined, return an empty string.
- client must be the advertiser/client code, not the agency, bank, billing entity, or legal address.
- market must be the campaign/client market when available.
- For folder sorting, if the invoice is a USD cross-market invoice and no client market is clear, market may be USD.
- month must be a full English month name.
- year must be 4 digits.
- amount must be a plain decimal string with no comma and no currency symbol.
- invoice_number must preserve slashes and letters if printed that way.

{ text_block }
""".strip()


def _generation_config():
    return types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
    )


def _call_text(prompt: str) -> dict:
    client = _get_client()

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=_generation_config(),
            )
            return _parse_json(response.text)
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                wait = 5 * (2 ** attempt)
                print(f"  [GEMINI] Rate limited — retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

    return {}


def _call_pdf(pdf_path: str, prompt: str) -> dict:
    client = _get_client()
    pdf_data = pathlib.Path(pdf_path).read_bytes()

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=pdf_data, mime_type="application/pdf"),
                    prompt,
                ],
                config=_generation_config(),
            )
            return _parse_json(response.text)
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                wait = 5 * (2 ** attempt)
                print(f"  [GEMINI] Rate limited — retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

    return {}


def _is_unknown(value):
    if value is None:
        return True

    value = str(value).strip()

    if not value:
        return True

    return value.upper() in {"UNKNOWN", "NONE", "NULL", "N/A", "NA", "-"}


def _is_weak_value(field, value):
    if _is_unknown(value):
        return True

    value = str(value).strip()
    upper = value.upper()

    if field == "client":
        return upper in {"BANK", "ACCOUNT", "INVOICE", "TOTAL", "NAME", "ADDRESS", "NUMBER", "THE", "AND", "ID", "M&C SAATCHI", "MCSAATCHI", "SAATCHI"}

    if field == "market":
        return upper in {"FACEBOOK", "META", "GOOGLE", "APPLE", "ADSJOY", "UNKNOWN"}

    if field == "month":
        return not bool(re.match(r"^[A-Za-z]+$", value))

    if field == "year":
        return not bool(re.match(r"^20\d{2}$", value))

    if field == "amount":
        return _normalize_amount(value) == ""

    if field == "currency":
        return not bool(re.match(r"^(USD|SGD|MYR|IDR|AUD|GBP|PHP|INR|MXN)$", upper))

    return False


def resolve_unknown_fields(
    text: str,
    supplier: str,
    fields: list[str],
    pdf_path: str = None,
) -> dict:
    fields = [field for field in fields if field in FIELD_DESCRIPTIONS]

    if not fields:
        return {}

    if not GEMINI_ENABLED:
        print("  [GEMINI] Disabled — skipping")
        return {}

    if not GEMINI_API_KEY:
        print("  [GEMINI] API key not configured — skipping")
        return {}

    use_pdf = bool(pdf_path and pathlib.Path(pdf_path).exists())
    mode = "PDF + text" if use_pdf and text else "PDF" if use_pdf else "text"
    prompt = _build_prompt(supplier, fields, text or "")

    print(f"  [GEMINI] Resolving {fields} via {mode} for [{str(supplier).upper()}]...")

    try:
        raw = _call_pdf(pdf_path, prompt) if use_pdf else _call_text(prompt)
        out = {}

        for field in fields:
            value = _normalize_field(field, raw.get(field, ""))
            out[field] = value
            print(f"  [GEMINI] {field} = {repr(value)}")

        return out

    except Exception as e:
        print(f"  [GEMINI] Error: {e}")
        return {}


def enrich_extraction(
    result: dict,
    text: str,
    supplier: str,
    pdf_path: str = None,
) -> dict:
    if not isinstance(result, dict):
        result = {}

    resolvable = set(FIELD_DESCRIPTIONS.keys())

    fields = [
        key
        for key, value in result.items()
        if key in resolvable and _is_weak_value(key, value)
    ]

    if not fields:
        cleaned = dict(result)

        for key, value in list(cleaned.items()):
            if key in resolvable:
                cleaned[key] = _normalize_field(key, value)

        return cleaned

    resolved = resolve_unknown_fields(text, supplier, fields, pdf_path=pdf_path)
    merged = dict(result)

    for field, value in resolved.items():
        value = _normalize_field(field, value)
        if value and not _is_weak_value(field, value):
            merged[field] = value

    for key, value in list(merged.items()):
        if key in resolvable:
            merged[key] = _normalize_field(key, value)

    return merged


def extract_with_gemini(
    text: str,
    supplier: str,
    fields: list[str],
    pdf_path: str = None,
) -> dict:
    base = {field: "" for field in fields if field in FIELD_DESCRIPTIONS}
    return enrich_extraction(base, text, supplier, pdf_path=pdf_path)


def is_enabled() -> bool:
    return GEMINI_ENABLED


def is_configured() -> bool:
    return bool(GEMINI_API_KEY)


def is_available() -> bool:
    return bool(GEMINI_API_KEY) and GEMINI_ENABLED