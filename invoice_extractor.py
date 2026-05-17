import os
import re
import sys
import warnings
from time import perf_counter
from datetime import datetime
from calendar import month_name

import pdfplumber
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from gemini_fallback import enrich_extraction, is_available as gemini_available


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")


INPUT_FOLDER = "./Input"
OUTPUT_FOLDER = "./Output"
TRACKER_PATH = os.path.join(INPUT_FOLDER, "ACCT-108 Master Invoice Tracker 2026.xlsx")
OUTPUT_PATH = os.path.join(OUTPUT_FOLDER, "ACCT-108 Master Invoice Tracker 2026 - Updated.xlsx")
INVOICE_FOLDER = "./invoices"

YEAR = 2026
SEP = "=" * 72
SUB_SEP = "-" * 72

WHITE = "FFFFFF"
DARK = "1A1A1A"

COLOURS = {
    "adsjoy": {"header_bg": "1F3864", "row_alt": "DCE6F1"},
    "apple": {"header_bg": "1C1C1E", "row_alt": "E8E8E8"},
    "google": {"header_bg": "1A73E8", "row_alt": "E8F0FE"},
    "meta": {"header_bg": "1877F2", "row_alt": "E7F0FD"},
}

CURRENCY_COLOURS = {
    "IDR": "E8F5E9",
    "MYR": "FFF8E1",
    "SGD": "E3F2FD",
    "USD": "F3E5F5",
}

CURRENCY_HEADER = {
    "IDR": "388E3C",
    "MYR": "F57F17",
    "SGD": "1565C0",
    "USD": "6A1B9A",
}

META_ENTITY_MARKET = {
    "FACEBOOK SINGAPORE": "SG",
    "FACEBOOK UK": "GB",
    "FACEBOOK IRELAND": "IE",
    "FACEBOOK NETHERLANDS": "NL",
    "FACEBOOK AUSTRALIA": "AU",
    "FACEBOOK THAILAND": "TH",
    "FACEBOOK MALAYSIA": "MY",
    "FACEBOOK INDONESIA": "ID",
    "FACEBOOK PHILIPPINES": "PH",
}

META_ACCOUNT_CLIENT = {
    "10472231667355": "BHC",
    "10572631630900": "LGL",
}

SHEET_NAMES = {
    "adsjoy": "Adsjoy",
    "apple": "Apple (ASA)",
    "google": "Google",
    "meta": "Meta (facebook)",
}

SUPPLIER_LABELS = {
    "adsjoy": "AdsJoy",
    "apple": "Apple (ASA)",
    "google": "Google",
    "meta": "Meta",
}

MONTH_ABBR = {m[:3].lower(): m for m in month_name if m}


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def duration_str(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins}m {secs:.1f}s"


def log(level, msg="", indent=0):
    prefix = " " * indent
    print(f"{prefix}[{level}] {msg}" if msg else "")


def print_header():
    print(SEP)
    print("ACCT-108 Invoice Extractor")
    print("Suppliers : AdsJoy | Apple ASA | Google | Meta")
    print("Mode      : PDF-content-first + Gemini fallback")
    print(f"Started   : {now_str()}")
    print(SEP)

    if gemini_available():
        log("GEMINI", "Fallback active — unknown fields resolved via AI")
        log("GEMINI", "Native PDF mode auto-enabled for low-text invoices")
    else:
        log("GEMINI", "Not configured — regex-only mode")


def clean_amount(val):
    if val is None:
        return None

    cleaned = re.sub(r"[^\d.-]", "", str(val).replace(",", "").replace(" ", "").strip())

    try:
        return float(cleaned)
    except ValueError:
        return None


def first_match(patterns, text, flags=re.I, group=1, default=""):
    if isinstance(patterns, str):
        patterns = [patterns]

    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(group).strip()

    return default


def normalize_month(mon, year):
    if not mon or not year:
        return ""

    full = MONTH_ABBR.get(mon[:3].lower(), mon.capitalize())
    year = str(year)

    if len(year) == 2:
        year = f"20{year}"

    return f"{full} {year}"


def billing_period_to_str(raw):
    if not raw:
        return ""

    raw = raw.strip()

    m = re.match(r"([A-Za-z]{3})-?(\d{2})$", raw)
    if m:
        return normalize_month(m.group(1), m.group(2))

    m = re.match(r"([A-Za-z]+)\s+(20\d{2})$", raw)
    if m:
        return normalize_month(m.group(1), m.group(2))

    return raw


def extract_month_from_text_or_filename(text, filename):
    patterns = [
        r"([A-Za-z]{3})'(\d{2})",
        r"Summary\s+for\s+\d{1,2}\s+([A-Za-z]+)\s+(\d{4})",
        r"Billing\s*Period\s*[:\s]*\d{1,2}\s+([A-Za-z]+)\s+(\d{4})",
        r"([A-Za-z]{3,})\s+(20\d{2})",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return normalize_month(m.group(1), m.group(2))

    m = re.search(r"_([A-Za-z]{3})_(\d{2})_", filename, re.I)
    if m:
        return normalize_month(m.group(1), m.group(2))

    m = re.search(r"Billing\s*Period[:\s]*([A-Za-z]{3}-\d{2})", text, re.I)
    if m:
        return billing_period_to_str(m.group(1))

    return ""


def extract_currency(text, default="USD"):
    match = re.search(r"\b(USD|SGD|MYR|IDR|AUD|GBP|PHP|INR)\b", text, re.I)
    return match.group(1).upper() if match else default


def read_pdf_text(pdf_path):
    full_text = ""
    all_tables = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            full_text += page.extract_text() or ""
            all_tables += page.extract_tables() or []

    return full_text, all_tables


def detect_supplier_from_content(text, filename):
    t = text.upper()
    fname = os.path.basename(filename).upper()

    content_rules = [
        ("adsjoy", ["ADSJOY DIGITAL", "ADSJOY"]),
        ("apple", ["APPLE DISTRIBUTION", "APPLE SERVICES LATAM", "APPLE SEARCH ADS"]),
        ("meta", ["FACEBOOK", "META PLATFORMS"]),
        ("google", ["GOOGLE ADS", "PT GOOGLE", "GOOGLE LLC", "GOOGLE IRELAND", "GOOGLE ASIA PACIFIC", "COLLECTIONS@GOOGLE.COM"]),
    ]

    for supplier, keywords in content_rules:
        if any(k in t for k in keywords):
            return supplier

    if "ADSJOY" in fname:
        return "adsjoy"
    if re.match(r"Q\d+", fname):
        return "apple"
    if re.match(r"\d{10}(\s|\.|\-|$)", fname):
        return "google"
    if "TRANSACTION" in fname or re.match(r"\d{12,}", fname):
        return "meta"

    return "unknown"


def scan_invoices(root_folder):
    results = []

    for dirpath, _, files in os.walk(root_folder):
        for filename in sorted(files):
            if not filename.lower().endswith(".pdf"):
                continue

            pdf_path = os.path.join(dirpath, filename)

            try:
                text, tables = read_pdf_text(pdf_path)
            except Exception as e:
                log("ERR", f"Could not read {filename}: {e}", indent=2)
                text, tables = "", []

            supplier = detect_supplier_from_content(text, pdf_path)
            results.append((pdf_path, supplier, text, tables))

    return results


def fix_date_columns(df):
    if df.empty:
        return df

    for col in df.columns:
        if any(k in col.lower() for k in ["month", "billing"]):
            try:
                converted = pd.to_datetime(df[col], errors="coerce").dt.strftime("%B %Y")
                mask = converted.notna()
                df.loc[mask, col] = converted[mask]
            except Exception:
                pass

    return df


def invoice_exists(tracker_df, invoice_number):
    if tracker_df is None or tracker_df.empty or not invoice_number:
        return False

    inv_col = next(
        (c for c in tracker_df.columns if "invoice" in c.lower() and "number" in c.lower()),
        None,
    )

    if not inv_col:
        return False

    existing = tracker_df[inv_col].astype(str).str.strip()
    return invoice_number.strip() in existing.values


def enrich_with_gemini(base, text, supplier, pdf_path):
    if not gemini_available():
        return base

    try:
        enriched = enrich_extraction(base, text, supplier, pdf_path=pdf_path) or {}
        result = base.copy()
        result.update({k: v for k, v in enriched.items() if v not in [None, ""]})
        return result
    except Exception as e:
        log("WARN", f"Gemini enrichment failed for {os.path.basename(pdf_path)}: {e}", indent=2)
        return base


def make_row(supplier, **kwargs):
    row = {
        "Year": YEAR,
        "Supplier Name": supplier,
        "Month of Service": kwargs.get("month", ""),
        "Month of Billing": kwargs.get("billing_month", kwargs.get("month", "")),
        "Client": kwargs.get("client", ""),
        "Invoice number": kwargs.get("invoice_number", ""),
        "Currency": kwargs.get("currency", ""),
        "Amount": kwargs.get("amount"),
    }

    optional_fields = [
        "Market",
        "Ad Account ID",
        "Campaign",
        "Campaign ID",
    ]

    for field in optional_fields:
        if field in kwargs:
            row[field] = kwargs.get(field)

    return row


def parse_adsjoy_pdf(pdf_path, text, tables):
    fname = os.path.basename(pdf_path)

    invoice_number = first_match([
        r"Invoice[:\s#]*([0-9]{2}-[0-9]{2}/[A-Za-z]{3}/[0-9]+)",
        r"Invoice\s*(?:No\.?|Number|#)?\s*[:\s]*([0-9\-/A-Za-z]+(?:/[0-9A-Za-z]+)*)",
    ], text)

    client = first_match([
        r"For\s+ADSJOY\s+DIGITAL\s*\n([A-Z]{2,6})\s",
        r"\$[\d,]+\.00\s*\nFor ADSJOY DIGITAL\s*\n([A-Z]{2,6})",
        r"\n([A-Z]{2,6})\s*\nFor\s+ADSJOY\s+DIGITAL",
    ], text)

    if not client:
        client = first_match(r"SAATCHI_([A-Z]+)_", fname).upper() or "UNKNOWN"

    month = extract_month_from_text_or_filename(text, fname)
    currency = extract_currency(text, "USD")
    amount = None

    for table in tables:
        for row in table:
            row_text = " ".join(str(c) for c in row if c)
            if re.search(r"total|grand total|amount due", row_text, re.I):
                candidates = [
                    clean_amount(n)
                    for n in re.findall(r"[\d,]+\.?\d*", row_text)
                    if clean_amount(n) and clean_amount(n) > 100
                ]
                if candidates:
                    amount = max(candidates)
                    break
        if amount:
            break

    if amount is None:
        amount = clean_amount(first_match([
            r"TOTAL\s*\n[^\n]*\n\$?([\d,]+\.?\d*)",
            r"(?:Total|Grand Total|Amount Due)[^\n$]*\$?\s*([\d,]+\.?\d*)",
        ], text))

    enriched = enrich_with_gemini(
        {"client": client, "month": month, "currency": currency, "amount": amount},
        text,
        "adsjoy",
        pdf_path,
    )

    client = enriched.get("client", client)
    month = enriched.get("month", month)
    currency = enriched.get("currency", currency)
    amount = clean_amount(enriched.get("amount")) if amount is None else amount

    log("OK", f"AdsJoy invoice {invoice_number} | Client: {client} | {currency} {amount}", indent=2)

    return [make_row(
        "AdsJoy",
        month=month,
        client=client,
        invoice_number=invoice_number,
        campaign=client,
        campaign_id="",
        currency=currency,
        amount=amount,
    )]


def parse_apple_pdf(pdf_path, text, tables, tracker_df=None):
    fname = os.path.basename(pdf_path)

    invoice_number = first_match(r"(Q\d+)", fname, flags=re.I).upper()
    if not invoice_number:
        invoice_number = first_match(r"Invoice\s*Number\s*[:\s]*([A-Z0-9]+)", text) or "UNKNOWN"

    if invoice_exists(tracker_df, invoice_number):
        log("SKIP", f"Apple invoice {invoice_number} already in tracker", indent=2)
        return None

    client = first_match([
        r"Client\s*[:\s]+([A-Z]{2,6})\b",
        r"Order\s*Number\s*[:\s]*([A-Z]{2,6})\d*",
        r"Description\s*[:\s]*\(S\)[^\n]+\s+([A-Z]{2,6})\s*$",
    ], text, flags=re.I | re.MULTILINE).upper()

    if client in ("NAME", "AND", "ADDRESS", "NUMBER", "ID", "THE", ""):
        client = "UNKNOWN"

    month = extract_month_from_text_or_filename(text, fname)
    currency = first_match(r"Currency\s*[:\s]*(USD|SGD|MYR|IDR|AUD|GBP|PHP)", text).upper()
    currency = currency or extract_currency(text, "USD")

    market = first_match(r"\b(SG|MY|ID|TH|PH|MX|AU|GB|US)\b", text).upper()

    amount = clean_amount(first_match([
        r"Payable\s*Amount\s*\([A-Z]+\)\s*([\d,]+\.\d{2})",
        r"\bTotal\b\s+([\d,]+\.\d{2})",
        r"Subtotal\s+([\d,]+\.\d{2})",
    ], text))

    enriched = enrich_with_gemini(
        {"client": client, "market": market, "month": month, "currency": currency, "amount": amount},
        text,
        "apple",
        pdf_path,
    )

    client = enriched.get("client", client)
    market = enriched.get("market", market)
    month = enriched.get("month", month)
    currency = enriched.get("currency", currency)
    amount = clean_amount(enriched.get("amount")) if amount is None else amount

    log("OK", f"Apple invoice {invoice_number} | Client: {client} | Market: {market} | {currency} {amount}", indent=2)

    return [make_row(
        "Apple (ASA)",
        month=month,
        client=client,
        market=market,
        invoice_number=invoice_number,
        currency=currency,
        amount=amount,
    )]


def parse_google_pdf(pdf_path, text, tables, tracker_df=None):
    fname = os.path.basename(pdf_path)

    invoice_number = first_match(r"Invoice\s*number[:\s.]*(\d+)", text)
    if not invoice_number:
        invoice_number = first_match(r"(\d{10})", fname) or "UNKNOWN"

    if invoice_exists(tracker_df, invoice_number):
        log("SKIP", f"Google invoice {invoice_number} already in tracker", indent=2)
        return None

    month = extract_month_from_text_or_filename(text, fname)
    currency = extract_currency(text, "USD")

    client = first_match(r"(?:MCSP|mcsp)_[A-Z]{2}_([A-Z0-9]+)_", text).upper()
    if not client:
        client = first_match(r"^Account:\s*([A-Za-z0-9]+)", text, flags=re.I | re.MULTILINE).upper()
    if not client:
        client = "UNKNOWN"

    amount = clean_amount(first_match([
        r"Total\s+amount\s+due\s+in\s+[A-Z]{3}\s+[A-Z]{3}\s*([\d,]+)",
        r"Total\s+in\s+[A-Z]{3}\s+[A-Z]{3}\s*([\d,]+)",
    ], text))

    if amount is None:
        candidates = [
            clean_amount(n)
            for n in re.findall(r"[\d,]{4,}", text)
            if clean_amount(n) and clean_amount(n) > 1000
        ]
        amount = max(candidates) if candidates else None

    enriched = enrich_with_gemini(
        {"client": client, "month": month, "currency": currency, "amount": amount},
        text,
        "google",
        pdf_path,
    )

    client = enriched.get("client", client)
    month = enriched.get("month", month)
    currency = enriched.get("currency", currency)
    amount = clean_amount(enriched.get("amount")) if amount is None else amount

    log("OK", f"Google invoice {invoice_number} | Client: {client} | {currency} {amount} | {month}", indent=2)

    return [make_row(
        "Google",
        month=month,
        client=client,
        invoice_number=invoice_number,
        currency=currency,
        amount=amount,
    )]


def parse_meta_pdf(pdf_path, text, tables):
    invoice_number = first_match(r"Invoice\s*#[:\s]*(\d+)", text)

    billing_period = ""
    period = first_match(r"Billing\s*Period[:\s]*([A-Za-z]{3}-\d{2})", text)
    if period:
        billing_period = billing_period_to_str(period)

    currency = first_match(r"Invoice\s*Currency[:\s]*(USD|SGD|MYR|IDR|AUD|GBP)", text).upper()
    currency = currency or extract_currency(text, "")

    client = ""
    market = ""

    campaign_match = re.search(r"MCSP_([A-Z]{2})_([A-Z0-9]+)_", text, re.I)
    if campaign_match:
        market = campaign_match.group(1).upper()
        client = campaign_match.group(2).upper()

    if not client:
        pac_match = re.search(r"mcspapac_([A-Z]{2})_[A-Z0-9]+_[^_]+_[A-Z]+_([A-Z]{2,6})_", text, re.I)
        if pac_match:
            market = market or pac_match.group(1).upper()
            client = pac_match.group(2).upper()

    if not market:
        upper_text = text.upper()
        market = next((v for k, v in META_ENTITY_MARKET.items() if k in upper_text), "")

    if not client:
        account_id = first_match([
            r"Account\s*Id\s*/\s*Group[:\s]*(\d+)",
            r"(?<!\d)(\d{13,15})(?!\d)",
        ], text)
        client = META_ACCOUNT_CLIENT.get(account_id, "")

    if not client:
        client = first_match(r"Advertiser[:\s]*([^\n]+)", text) or "UNKNOWN"
        if re.search(r"saatchi|m&c|mcsaatchi", client, re.I):
            client = "UNKNOWN"

    invoice_total = clean_amount(first_match(r"Invoice\s*Total[:\s]*([\d,]+\.\d{2})", text))
    subtotal = clean_amount(first_match(r"Subtotal[:\s]*([\d,]+\.\d{2})", text))

    enriched = enrich_with_gemini(
        {"client": client, "market": market, "month": billing_period, "currency": currency, "amount": invoice_total},
        text,
        "meta",
        pdf_path,
    )

    client = enriched.get("client", client)
    market = enriched.get("market", market)
    billing_period = enriched.get("month", billing_period)
    currency = enriched.get("currency", currency)
    invoice_total = clean_amount(enriched.get("amount")) if invoice_total is None else invoice_total

    rows = []
    line_pattern = re.compile(r"^\d+\s+(.+?)\s+([\d,]+\.\d{2})\s*$", re.MULTILINE)

    for match in line_pattern.finditer(text):
        campaign_name = match.group(1).strip()
        amount = clean_amount(match.group(2))

        if re.search(r"subtotal|invoice total|freight|vat|gst", campaign_name, re.I):
            continue

        if amount is None:
            continue

        campaign_id = first_match(r"<([A-Z0-9]+)>", campaign_name)

        rows.append(make_row(
            "Meta",
            month=billing_period,
            client=client,
            market=market,
            invoice_number=invoice_number,
            campaign=campaign_name,
            campaign_id=campaign_id,
            currency=currency,
            amount=amount,
            **{"Ad Account ID": ""},
        ))

    if not rows:
        rows.append(make_row(
            "Meta",
            month=billing_period,
            client=client,
            market=market,
            invoice_number=invoice_number,
            campaign="",
            campaign_id="",
            currency=currency,
            amount=subtotal or invoice_total,
            **{"Ad Account ID": ""},
        ))

    log(
        "OK",
        f"Meta invoice {invoice_number} | Client: {client} | Market: {market} | {currency} | {len(rows)} row(s) | Total: {invoice_total}",
        indent=2,
    )

    return rows


def make_border(color="D9D9D9"):
    thin = Side(style="thin", color=color)
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def format_sheet(ws, palette_key, amount_col_names=None):
    pal = COLOURS[palette_key]
    border = make_border()
    amount_col_names = amount_col_names or []

    header_fill = PatternFill("solid", fgColor=pal["header_bg"])
    alt_fill = PatternFill("solid", fgColor=pal["row_alt"])
    white_fill = PatternFill("solid", fgColor=WHITE)

    amount_cols = {
        ci for ci in range(1, ws.max_column + 1)
        if ws.cell(1, ci).value in amount_col_names
    }

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = Font(bold=True, color=WHITE, size=10)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    ws.row_dimensions[1].height = 30

    for ri in range(2, ws.max_row + 1):
        fill = alt_fill if ri % 2 == 0 else white_fill

        for ci in range(1, ws.max_column + 1):
            cell = ws.cell(ri, ci)
            cell.fill = fill
            cell.border = border
            cell.alignment = Alignment(vertical="center", wrap_text=False)

            if ci in amount_cols:
                cell.number_format = "#,##0.00"

    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"

    for ci in range(1, ws.max_column + 1):
        col_letter = get_column_letter(ci)
        max_len = max(
            len(str(ws.cell(r, ci).value or ""))
            for r in range(1, ws.max_row + 1)
        )
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 55)


def build_summary(ws, sheet_map):
    border = make_border("CCCCCC")
    thin_border = make_border("E0E0E0")

    ws.merge_cells("A1:G1")
    title = ws["A1"]
    title.value = "ACCT-108 | Master Invoice Tracker 2026 - Summary"
    title.font = Font(bold=True, color=DARK, size=13)
    title.fill = PatternFill("solid", fgColor="F0F4F8")
    title.alignment = Alignment(horizontal="center", vertical="center")
    title.border = border
    ws.row_dimensions[1].height = 36

    headers = ["Currency", "Supplier", "Sheet", "Clients", "# Invoices", "# Campaigns/Rows", "Total Amount"]

    for ci, header in enumerate(headers, 1):
        cell = ws.cell(2, ci, header)
        cell.fill = PatternFill("solid", fgColor="2E4057")
        cell.font = Font(bold=True, color=WHITE, size=10)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    ws.row_dimensions[2].height = 26

    rows = []

    for sheet_name, df in sheet_map.items():
        if df.empty:
            continue

        amount_col = next((c for c in ["Amount", "Invoice Total", "Subtotal"] if c in df.columns), None)
        currency_col = next((c for c in df.columns if c.strip() == "Currency"), None)

        if not currency_col:
            continue

        for currency, grp in df.groupby(currency_col):
            currency = str(currency).strip()

            if not currency:
                continue

            client_col = "Client" if "Client" in grp.columns else None
            invoice_col = next((c for c in grp.columns if "invoice" in c.lower() and "number" in c.lower()), None)

            clients = "-"
            if client_col:
                clients = ", ".join(sorted(grp[client_col].dropna().astype(str).str.strip().unique()))

            rows.append({
                "currency": currency,
                "supplier": {
                    "Adsjoy": "AdsJoy",
                    "Apple (ASA)": "Apple (ASA)",
                    "Google": "Google",
                    "Meta (facebook)": "Meta (Facebook)",
                }.get(sheet_name, sheet_name),
                "sheet": sheet_name,
                "clients": clients,
                "invoices": grp[invoice_col].nunique() if invoice_col else len(grp),
                "rows": len(grp),
                "total": grp[amount_col].sum() if amount_col else 0,
            })

    currency_order = ["IDR", "MYR", "SGD", "USD"]
    rows.sort(key=lambda r: (
        currency_order.index(r["currency"]) if r["currency"] in currency_order else 99,
        r["supplier"],
    ))

    ri = 3
    last_currency = None
    row_counter = 0

    for row in rows:
        currency = row["currency"]

        if currency != last_currency:
            color = CURRENCY_HEADER.get(currency, "333333")
            ws.merge_cells(f"A{ri}:G{ri}")

            cell = ws.cell(ri, 1, f"  {currency} - {currency} Invoices")
            cell.fill = PatternFill("solid", fgColor=color)
            cell.font = Font(bold=True, color=WHITE, size=10)
            cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
            cell.border = make_border(color)

            ws.row_dimensions[ri].height = 22

            ri += 1
            row_counter = 0
            last_currency = currency

        row_counter += 1
        fill = PatternFill(
            "solid",
            fgColor=CURRENCY_COLOURS.get(currency, "F5F5F5") if row_counter % 2 == 0 else WHITE,
        )

        values = [
            currency,
            row["supplier"],
            row["sheet"],
            row["clients"],
            row["invoices"],
            row["rows"],
            row["total"],
        ]

        for ci, value in enumerate(values, 1):
            cell = ws.cell(ri, ci, value)
            cell.fill = fill
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center", wrap_text=False)
            cell.font = Font(color=DARK, size=10, bold=(ci == 7))

            if ci == 7:
                cell.number_format = "#,##0.00"

        ws.row_dimensions[ri].height = 20
        ri += 1

    for ci, width in enumerate([10, 18, 18, 38, 13, 18, 18], 1):
        ws.column_dimensions[get_column_letter(ci)].width = width

    ws.freeze_panes = "A3"


def append_new_rows(existing_df, new_rows, key_col):
    stats = {"added": 0, "duplicates": 0}

    if not new_rows:
        return existing_df, stats

    new_df = pd.DataFrame(new_rows)

    if existing_df.empty:
        stats["added"] = len(new_df)
        return new_df, stats

    if key_col not in existing_df.columns or key_col not in new_df.columns:
        stats["added"] = len(new_df)
        return pd.concat([existing_df, new_df], ignore_index=True), stats

    existing_keys = set(existing_df[key_col].astype(str).str.strip())
    mask = ~new_df[key_col].astype(str).str.strip().isin(existing_keys)
    filtered = new_df[mask]

    stats["duplicates"] = len(new_df) - len(filtered)
    stats["added"] = len(filtered)

    return pd.concat([existing_df, filtered], ignore_index=True), stats


def load_tracker():
    log("LOAD", "Loading tracker from Input/...")

    tracker_sheets = pd.read_excel(TRACKER_PATH, sheet_name=None, header=0)

    return {
        "adsjoy": fix_date_columns(tracker_sheets.get(SHEET_NAMES["adsjoy"], pd.DataFrame())),
        "apple": fix_date_columns(tracker_sheets.get(SHEET_NAMES["apple"], pd.DataFrame())),
        "google": fix_date_columns(tracker_sheets.get(SHEET_NAMES["google"], pd.DataFrame())),
        "meta": fix_date_columns(tracker_sheets.get(SHEET_NAMES["meta"], pd.DataFrame())),
    }


def write_tracker(sheet_map):
    log("WRITE", "Writing updated tracker to Output/...")

    with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
        pd.DataFrame().to_excel(writer, sheet_name="Summary", index=False)

        for sheet_name, df in sheet_map.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    log("FORMAT", "Applying workbook formatting...")

    wb = load_workbook(OUTPUT_PATH)

    format_config = {
        "Adsjoy": ("adsjoy", ["Amount"]),
        "Apple (ASA)": ("apple", ["Amount"]),
        "Google": ("google", ["Amount"]),
        "Meta (facebook)": ("meta", ["Amount"]),
    }

    for sheet_name, config in format_config.items():
        if sheet_name in wb.sheetnames:
            format_sheet(wb[sheet_name], config[0], amount_col_names=config[1])

    build_summary(wb["Summary"], sheet_map)

    if "Summary" in wb.sheetnames:
        wb.move_sheet("Summary", offset=-(len(wb.sheetnames) - 1))

    wb.save(OUTPUT_PATH)


def print_extraction_summary(stats, output_path, elapsed):
    print()
    print(SUB_SEP)
    print("EXTRACTION SUMMARY")
    print(SUB_SEP)
    print(f"PDFs scanned          : {stats['pdfs_scanned']}")
    print(f"Unknown skipped       : {stats['unknown_skipped']}")
    print(f"Rows extracted        : {stats['rows_extracted']}")
    print(f"Rows added            : {stats['rows_added']}")
    print(f"Duplicates skipped    : {stats['duplicates']}")
    print()

    for supplier in ["adsjoy", "apple", "google", "meta"]:
        s = stats["suppliers"][supplier]
        print(f"{SUPPLIER_LABELS[supplier]:<20}: PDFs {s['pdfs']:<3} | Rows {s['rows']:<4} | Added {s['added']:<4} | Duplicates {s['duplicates']}")

    print()
    print(f"Output file           : {output_path}")
    print(f"Duration              : {duration_str(elapsed)}")
    print(f"Result                : SUCCESS")
    print(SUB_SEP)


def main():
    start = perf_counter()

    print_header()

    os.makedirs(INPUT_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    if not os.path.exists(TRACKER_PATH):
        print()
        log("ERR", f"Tracker not found: {TRACKER_PATH}")
        log("INFO", "Please place your tracker in the Input/ folder and re-run.")
        sys.exit(1)

    tracker = load_tracker()

    new_rows = {
        "adsjoy": [],
        "apple": [],
        "google": [],
        "meta": [],
    }

    stats = {
        "pdfs_scanned": 0,
        "unknown_skipped": 0,
        "rows_extracted": 0,
        "rows_added": 0,
        "duplicates": 0,
        "suppliers": {
            "adsjoy": {"pdfs": 0, "rows": 0, "added": 0, "duplicates": 0},
            "apple": {"pdfs": 0, "rows": 0, "added": 0, "duplicates": 0},
            "google": {"pdfs": 0, "rows": 0, "added": 0, "duplicates": 0},
            "meta": {"pdfs": 0, "rows": 0, "added": 0, "duplicates": 0},
        },
    }

    invoices = scan_invoices(INVOICE_FOLDER)
    stats["pdfs_scanned"] = len(invoices)

    print()
    log("SCAN", f"Found {len(invoices)} PDF invoice(s) across all subfolders")
    print()

    for pdf_path, supplier, text, tables in invoices:
        filename = os.path.basename(pdf_path)
        print(f"[PDF] {filename} -> [{supplier.upper()}]")

        if supplier == "unknown":
            stats["unknown_skipped"] += 1
            log("WARN", "Unknown supplier — skipped", indent=2)
            continue

        stats["suppliers"][supplier]["pdfs"] += 1

        try:
            if supplier == "adsjoy":
                result = parse_adsjoy_pdf(pdf_path, text, tables)
            elif supplier == "apple":
                result = parse_apple_pdf(pdf_path, text, tables, tracker["apple"])
            elif supplier == "google":
                result = parse_google_pdf(pdf_path, text, tables, tracker["google"])
            elif supplier == "meta":
                result = parse_meta_pdf(pdf_path, text, tables)
            else:
                result = None

            if result:
                new_rows[supplier].extend(result)
                stats["rows_extracted"] += len(result)
                stats["suppliers"][supplier]["rows"] += len(result)

        except Exception as e:
            log("ERR", f"Failed to parse {filename}: {e}", indent=2)

    print()
    log("MERGE", "Merging extracted rows into tracker sheets...")

    sheet_map = {}

    for supplier, sheet_name in SHEET_NAMES.items():
        merged_df, merge_stats = append_new_rows(
            tracker[supplier],
            new_rows[supplier],
            "Invoice number",
        )

        sheet_map[sheet_name] = merged_df

        stats["rows_added"] += merge_stats["added"]
        stats["duplicates"] += merge_stats["duplicates"]
        stats["suppliers"][supplier]["added"] = merge_stats["added"]
        stats["suppliers"][supplier]["duplicates"] = merge_stats["duplicates"]

        label = SUPPLIER_LABELS[supplier]
        log(
            "MERGE",
            f"{label}: {merge_stats['added']} added, {merge_stats['duplicates']} duplicate(s) skipped",
            indent=2,
        )

    write_tracker(sheet_map)

    elapsed = perf_counter() - start

    print()
    log("DONE", "Extraction complete")
    print_extraction_summary(stats, OUTPUT_PATH, elapsed)
    print(SEP)


if __name__ == "__main__":
    main()