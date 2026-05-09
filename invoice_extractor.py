import os
import re
import sys
import warnings
import pdfplumber
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Windows CP1252 fix - force UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")

# -----------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------
INPUT_FOLDER   = "./Input"
OUTPUT_FOLDER  = "./Output"
TRACKER_PATH   = os.path.join(INPUT_FOLDER,  "ACCT-108 Master Invoice Tracker 2026.xlsx")
OUTPUT_PATH    = os.path.join(OUTPUT_FOLDER, "ACCT-108 Master Invoice Tracker 2026 - Updated.xlsx")
INVOICE_FOLDER = "./invoices"

# -----------------------------------------------------------------
# COLOUR PALETTE
# -----------------------------------------------------------------
COLOURS = {
    "adsjoy": {"header_bg": "1F3864", "row_alt": "DCE6F1"},
    "apple":  {"header_bg": "1C1C1E", "row_alt": "E8E8E8"},
    "google": {"header_bg": "1A73E8", "row_alt": "E8F0FE"},
    "meta":   {"header_bg": "1877F2", "row_alt": "E7F0FD"},
}

CURRENCY_COLOURS = {
    "IDR": "E8F5E9", "MYR": "FFF8E1",
    "SGD": "E3F2FD", "USD": "F3E5F5",
}
CURRENCY_HEADER = {
    "IDR": "388E3C", "MYR": "F57F17",
    "SGD": "1565C0", "USD": "6A1B9A",
}
WHITE = "FFFFFF"
DARK  = "1A1A1A"

# -----------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------
def clean_amount(val):
    if val is None:
        return None
    val = re.sub(r"[^\d.-]", "", str(val).replace(",", "").replace(" ", "").strip())
    try:
        return float(val)
    except ValueError:
        return None


def read_pdf_text(pdf_path):
    """Read all text from a PDF, returns (full_text, all_tables)."""
    full_text  = ""
    all_tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            full_text  += page.extract_text() or ""
            all_tables += page.extract_tables() or []
    return full_text, all_tables


def detect_supplier_from_content(text, filename):
    """
    Detect supplier by reading PDF content first.
    Falls back to filename pattern if content is ambiguous.
    """
    t     = text.upper()
    fname = os.path.basename(filename).upper()

    # ── Content-based (most reliable) ────────────────────────────
    if "ADSJOY DIGITAL" in t or "ADSJOY" in t:
        return "adsjoy"

    if "APPLE DISTRIBUTION" in t or "APPLE SERVICES LATAM" in t or "APPLE SEARCH ADS" in t:
        return "apple"

    if "FACEBOOK" in t or "META PLATFORMS" in t:
        return "meta"

    if (
        "GOOGLE ADS" in t
        or "PT GOOGLE" in t
        or "GOOGLE LLC" in t
        or "GOOGLE IRELAND" in t
        or "GOOGLE ASIA PACIFIC" in t
        or "COLLECTIONS@GOOGLE.COM" in t
    ):
        return "google"

    # ── Filename fallback ─────────────────────────────────────────
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
    """
    Walk all subfolders, read each PDF's text, detect supplier from content.
    Returns list of (filepath, supplier, text, tables).
    """
    results = []
    for dirpath, _, files in os.walk(root_folder):
        for f in sorted(files):
            if not f.lower().endswith(".pdf"):
                continue
            fpath = os.path.join(dirpath, f)
            try:
                text, tables = read_pdf_text(fpath)
            except Exception as e:
                print(f"  [ERR] Could not read {f}: {e}")
                text, tables = "", []
            supplier = detect_supplier_from_content(text, fpath)
            results.append((fpath, supplier, text, tables))
    return results


def billing_period_to_str(raw):
    if not raw:
        return ""
    # "Mar-26" → "March 2026"
    m = re.match(r"([A-Za-z]{3})-?(\d{2})$", raw.strip())
    if m:
        from calendar import month_name
        abbr_to_full = {v[:3].lower(): v for v in month_name if v}
        full = abbr_to_full.get(m.group(1).lower(), m.group(1).capitalize())
        return f"{full} 20{m.group(2)}"
    # "March 2026" passthrough
    m2 = re.match(r"([A-Za-z]+)\s+(20\d{2})$", raw.strip())
    if m2:
        return raw.strip()
    return raw.strip()


def fix_date_columns(df):
    for col in df.columns:
        if any(k in col.lower() for k in ["month", "billing"]):
            try:
                converted = pd.to_datetime(df[col], errors="coerce").dt.strftime("%B %Y")
                mask = converted.notna()
                df.loc[mask, col] = converted[mask]
            except Exception:
                pass
    return df


def make_border(color="D9D9D9"):
    thin = Side(style="thin", color=color)
    return Border(left=thin, right=thin, top=thin, bottom=thin)


# -----------------------------------------------------------------
# PARSER 1 — ADSJOY
# Reads: invoice#, client code, month, currency, amount from PDF
# -----------------------------------------------------------------
def parse_adsjoy_pdf(pdf_path, text, tables):
    fname = os.path.basename(pdf_path)

    # ── Invoice number ────────────────────────────────────────────
    # Pattern: "26-27/Apr/10" or "Invoice: 26-27/Apr/10"
    inv_m = re.search(
        r"Invoice[:\s#]*([0-9]{2}-[0-9]{2}/[A-Za-z]{3}/[0-9]+)",
        text, re.I
    )
    if not inv_m:
        inv_m = re.search(
            r"Invoice\s*(?:No\.?|Number|#)?\s*[:\s]*([0-9\-/A-Za-z]+(?:/[0-9A-Za-z]+)*)",
            text, re.I
        )
    invoice_number = inv_m.group(1).strip() if inv_m else ""

    # ── Client — from PDF near "For ADSJOY DIGITAL" ───────────────
    # The 2-letter client code appears just before "For ADSJOY DIGITAL"
    # e.g. "GT\nFor ADSJOY DIGITAL" or "TOTAL\nMar'26\n$67,113.00\nFor ADSJOY DIGITAL\nGT"
    client = ""
    client_m = re.search(
        r"For\s+ADSJOY\s+DIGITAL\s*\n([A-Z]{2,6})\s",
        text, re.I
    )
    if client_m:
        client = client_m.group(1).strip().upper()

    # Also try: code appears on its own line right after TOTAL block
    if not client:
        client_m2 = re.search(
            r"\$[\d,]+\.00\s*\nFor ADSJOY DIGITAL\s*\n([A-Z]{2,6})",
            text, re.I
        )
        if client_m2:
            client = client_m2.group(1).strip().upper()

    # Also try: code appears just before "For ADSJOY DIGITAL"
    if not client:
        client_m3 = re.search(
            r"\n([A-Z]{2,6})\s*\nFor\s+ADSJOY\s+DIGITAL",
            text, re.I
        )
        if client_m3:
            client = client_m3.group(1).strip().upper()

    # Fallback: filename  e.g. _GT_
    if not client:
        fn_m = re.search(r"SAATCHI_([A-Z]+)_", fname, re.I)
        client = fn_m.group(1).upper() if fn_m else "UNKNOWN"

    # ── Month of service — from PDF "Mar'26" or filename ──────────
    month_of_svc = ""
    mos_m = re.search(r"([A-Za-z]{3})'(\d{2})", text)
    if mos_m:
        from calendar import month_name
        abbr_to_full = {v[:3].lower(): v for v in month_name if v}
        full = abbr_to_full.get(mos_m.group(1).lower(), mos_m.group(1).capitalize())
        month_of_svc = f"{full} 20{mos_m.group(2)}"

    if not month_of_svc:
        # Fallback: filename _Mar_26_
        fn_m2 = re.search(r"_([A-Za-z]{3})_(\d{2})_", fname)
        if fn_m2:
            from calendar import month_name
            abbr_to_full = {v[:3].lower(): v for v in month_name if v}
            full = abbr_to_full.get(fn_m2.group(1).lower(), fn_m2.group(1).capitalize())
            month_of_svc = f"{full} 20{fn_m2.group(2)}"

    # ── Currency ──────────────────────────────────────────────────
    cur_m    = re.search(r"\b(USD|INR|SGD|IDR|MYR|AUD|GBP)\b", text)
    currency = cur_m.group(1) if cur_m else "USD"

    # ── Amount — from tables first, then text ─────────────────────
    amount = None
    for table in tables:
        for row in table:
            row_text = " ".join(str(c) for c in row if c)
            if re.search(r"total|grand total|amount due", row_text, re.I):
                candidates = [
                    clean_amount(n) for n in re.findall(r"[\d,]+\.?\d*", row_text)
                    if clean_amount(n) and clean_amount(n) > 100
                ]
                if candidates:
                    amount = max(candidates)
                    break
        if amount:
            break

    if not amount:
        # "TOTAL\nMar'26\n$67,113.00"
        tot_m = re.search(r"TOTAL\s*\n[^\n]*\n\$?([\d,]+\.?\d*)", text, re.I)
        if tot_m:
            amount = clean_amount(tot_m.group(1))

    if not amount:
        # "$67,113.00" anywhere after TOTAL keyword
        tot_m2 = re.search(r"(?:Total|Grand Total|Amount Due)[^\n$]*\$?\s*([\d,]+\.?\d*)", text, re.I)
        if tot_m2:
            amount = clean_amount(tot_m2.group(1))

    print(f"  [OK] AdsJoy: invoice {invoice_number} | Client: {client} | {currency} {amount}")
    return [{
        "Month":            2026,
        "Supplier Name":    "AdsJoy",
        "Month of Service": month_of_svc,
        "Month of Billing": month_of_svc,
        "Client":           client,
        "Invoice number":   invoice_number,
        "Campaign":         client,
        "Campaign ID":      "",
        "Currency ":        currency,
        "Amount":           amount,
    }]


# -----------------------------------------------------------------
# PARSER 2 — APPLE
# Reads: invoice#, client code, month, currency, amount from PDF
# -----------------------------------------------------------------
def parse_apple_pdf(pdf_path, text, tables, tracker_df=None):
    fname = os.path.basename(pdf_path)

    # ── Invoice number — filename first (most reliable for Apple) ─
    inv_m          = re.search(r"(Q\d+)", fname, re.I)
    invoice_number = inv_m.group(1).upper() if inv_m else ""
    if not invoice_number:
        m = re.search(r"Invoice\s*Number\s*[:\s]*([A-Z0-9]+)", text, re.I)
        invoice_number = m.group(1).strip() if m else "UNKNOWN"

    # ── Dedup check against tracker ───────────────────────────────
    if tracker_df is not None and not tracker_df.empty:
        inv_col = next((c for c in tracker_df.columns
                        if "invoice" in c.lower() and "number" in c.lower()), None)
        if inv_col:
            matched = tracker_df[
                tracker_df[inv_col].astype(str).str.strip() == invoice_number.strip()
            ]
            if not matched.empty:
                print(f"  [SKIP] Apple: invoice {invoice_number} already in tracker")
                return None

    # ── Client — from "Client :" field or Order Number or Description
    client = ""

    # "Client :\nMF" or "Client : MF"
    client_m = re.search(r"Client\s*[:\s]+([A-Z]{2,6})\b", text, re.I)
    if client_m:
        val = client_m.group(1).strip().upper()
        if val not in ("NAME", "AND", "ADDRESS", "NUMBER", "ID", "THE"):
            client = val

    # "Order Number : MF01"  →  strip trailing digits
    if not client:
        order_m = re.search(r"Order\s*Number\s*[:\s]*([A-Z]{2,6})\d*", text, re.I)
        if order_m:
            client = order_m.group(1).strip().upper()

    # "(S)M&C SAATCHI MOBILE ASIA PACIFIC MARC  MF" — last token on Description line
    if not client:
        desc_m = re.search(
            r"Description\s*[:\s]*\(S\)[^\n]+\s+([A-Z]{2,6})\s*$",
            text, re.I | re.MULTILINE
        )
        if desc_m:
            client = desc_m.group(1).strip().upper()

    if not client:
        client = "UNKNOWN"

    # ── Billing period — "01 Mar 2026 - 31 Mar 2026" ─────────────
    month_of_svc = ""
    bp_m = re.search(
        r"Billing\s*Period\s*[:\s]*\d{1,2}\s+([A-Za-z]+)\s+(\d{4})",
        text, re.I
    )
    if bp_m:
        from calendar import month_name
        abbr_to_full = {v[:3].lower(): v for v in month_name if v}
        mon  = bp_m.group(1).capitalize()
        full = abbr_to_full.get(mon[:3].lower(), mon)
        month_of_svc = f"{full} {bp_m.group(2)}"

    if not month_of_svc:
        bp_m2 = re.search(r"([A-Za-z]{3,})\s+(20\d{2})", text)
        if bp_m2:
            from calendar import month_name
            abbr_to_full = {v[:3].lower(): v for v in month_name if v}
            mon  = bp_m2.group(1).capitalize()
            full = abbr_to_full.get(mon[:3].lower(), mon)
            month_of_svc = f"{full} {bp_m2.group(2)}"

    # ── Currency ──────────────────────────────────────────────────
    cur_m    = re.search(r"Currency\s*[:\s]*(USD|SGD|MYR|IDR|AUD|GBP|PHP)", text, re.I)
    currency = cur_m.group(1).upper() if cur_m else ""
    if not currency:
        cur_m2   = re.search(r"\b(USD|SGD|MYR|IDR|AUD|GBP|PHP)\b", text)
        currency = cur_m2.group(1).upper() if cur_m2 else "USD"

    # ── Market — from Region column (SG, MX, etc.) ────────────────
    market_m = re.search(r"\b(SG|MY|ID|TH|PH|MX|AU|GB|US)\b", text)
    market   = market_m.group(1).upper() if market_m else ""

    # ── Amount — "Total  7,819.23" or "Payable Amount (GBP) 242.32"
    amount = None

    # Prefer payable amount in local currency if present
    pay_m = re.search(r"Payable\s*Amount\s*\([A-Z]+\)\s*([\d,]+\.\d{2})", text, re.I)
    if pay_m:
        amount = clean_amount(pay_m.group(1))

    if not amount:
        tot_m = re.search(r"\bTotal\b\s+([\d,]+\.\d{2})", text, re.I)
        if tot_m:
            amount = clean_amount(tot_m.group(1))

    if not amount:
        sub_m = re.search(r"Subtotal\s+([\d,]+\.\d{2})", text, re.I)
        if sub_m:
            amount = clean_amount(sub_m.group(1))

    print(f"  [OK] Apple: invoice {invoice_number} | Client: {client} | Market: {market} | {currency} {amount}")
    return [{
        "Year":             2026,
        "Supplier Name":    "Apple (ASA)",
        "Month of Service": month_of_svc,
        "Month of Billing": month_of_svc,
        "Client":           client,
        "Market":           market,
        "Invoice number":   invoice_number,
        "Currency":         currency,
        "Amount":           amount,
    }]


# -----------------------------------------------------------------
# PARSER 3 — GOOGLE
# Reads: invoice#, client, month, currency, amount from PDF
# -----------------------------------------------------------------
def parse_google_pdf(pdf_path, text, tables, tracker_df=None):
    fname = os.path.basename(pdf_path)

    # ── Invoice number ────────────────────────────────────────────
    inv_m = re.search(r"Invoice\s*number[:\s.]*(\d+)", text, re.I)
    invoice_number = inv_m.group(1).strip() if inv_m else ""
    if not invoice_number:
        fn_m = re.search(r"(\d{10})", fname)
        invoice_number = fn_m.group(1) if fn_m else "UNKNOWN"

    # ── Dedup check ───────────────────────────────────────────────
    if tracker_df is not None and not tracker_df.empty:
        inv_col = next((c for c in tracker_df.columns
                        if "invoice" in c.lower() and "number" in c.lower()), None)
        if inv_col:
            matched = tracker_df[
                tracker_df[inv_col].astype(str).str.strip() == invoice_number.strip()
            ]
            if not matched.empty:
                print(f"  [SKIP] Google: invoice {invoice_number} already in tracker")
                return None

    # ── Billing period — "Summary for 1 Mar 2026 - 31 Mar 2026" ──
    month_of_svc = ""
    sum_m = re.search(
        r"Summary\s+for\s+\d{1,2}\s+([A-Za-z]+)\s+(\d{4})",
        text, re.I
    )
    if sum_m:
        from calendar import month_name
        abbr_to_full = {v[:3].lower(): v for v in month_name if v}
        mon  = sum_m.group(1).capitalize()
        full = abbr_to_full.get(mon[:3].lower(), mon)
        month_of_svc = f"{full} {sum_m.group(2)}"

    if not month_of_svc:
        bp_m = re.search(r"Billing\s*Period[:\s]*([A-Za-z]{3}-\d{2})", text, re.I)
        if bp_m:
            month_of_svc = billing_period_to_str(bp_m.group(1))

    # ── Currency ──────────────────────────────────────────────────
    cur_m    = re.search(r"\b(IDR|MYR|SGD|PHP|USD|GBP|AUD)\b", text)
    currency = cur_m.group(1).upper() if cur_m else "USD"

    # ── Client — from campaign name pattern MCSP_XX_CLIENT_ ───────
    client = "UNKNOWN"
    camp_m = re.search(r"(?:MCSP|mcsp)_[A-Z]{2}_([A-Z0-9]+)_", text, re.I)
    if camp_m:
        client = camp_m.group(1).upper()

    # Fallback: Account name line "Account: Ama"
    if client == "UNKNOWN":
        acc_m = re.search(r"^Account:\s*([A-Za-z0-9]+)", text, re.I | re.MULTILINE)
        if acc_m:
            client = acc_m.group(1).strip().upper()

    # ── Amount — "Total amount due in IDR\nIDR 417,004,255" ───────
    amount = None
    tot_m = re.search(
        r"Total\s+amount\s+due\s+in\s+[A-Z]{3}\s+[A-Z]{3}\s*([\d,]+)",
        text, re.I
    )
    if tot_m:
        amount = clean_amount(tot_m.group(1))

    if not amount:
        # "Total in IDR\nIDR 417,004,255"
        tot_m2 = re.search(r"Total\s+in\s+[A-Z]{3}\s+[A-Z]{3}\s*([\d,]+)", text, re.I)
        if tot_m2:
            amount = clean_amount(tot_m2.group(1))

    if not amount:
        # Last large number in text
        all_amounts = [clean_amount(n) for n in re.findall(r"[\d,]{4,}", text)
                       if clean_amount(n) and clean_amount(n) > 1000]
        if all_amounts:
            amount = max(all_amounts)

    print(f"  [OK] Google: invoice {invoice_number} | Client: {client} | {currency} {amount} | {month_of_svc}")
    return [{
        "Year":             2026,
        "Supplier Name":    "Google",
        "Month of Service": month_of_svc,
        "Month of Billing": month_of_svc,
        "Client":           client,
        "Invoice number":   invoice_number,
        "Currency":         currency,
        "Amount":           amount,
    }]


# -----------------------------------------------------------------
# PARSER 4 — META
# Reads: invoice#, client (from campaign), month, currency, amount
# -----------------------------------------------------------------
def parse_meta_pdf(pdf_path, text, tables):

    # ── Invoice number ────────────────────────────────────────────
    inv_m          = re.search(r"Invoice\s*#[:\s]*(\d+)", text, re.I)
    invoice_number = inv_m.group(1).strip() if inv_m else ""

    # ── Billing period ────────────────────────────────────────────
    period_m       = re.search(r"Billing\s*Period[:\s]*([A-Za-z]{3}-\d{2})", text, re.I)
    billing_period = billing_period_to_str(period_m.group(1)) if period_m else ""

    # ── Account ID ────────────────────────────────────────────────
    acc_m      = re.search(r"Account\s*Id\s*/\s*Group[:\s]*(\d+)", text, re.I)
    account_id = acc_m.group(1).strip() if acc_m else ""

    # ── Currency ──────────────────────────────────────────────────
    cur_m    = re.search(r"Invoice\s*Currency[:\s]*(USD|SGD|MYR|IDR|AUD|GBP)", text, re.I)
    currency = cur_m.group(1).strip() if cur_m else ""
    if not currency:
        cur_m2   = re.search(r"\b(USD|SGD|MYR|IDR|AUD|GBP)\b", text)
        currency = cur_m2.group(1) if cur_m2 else ""

    # ── Client — from campaign label MCSP_TH_CFTH_ ───────────────
    # "MCSP_TH_CFTH_Facebook_LF_..." → market=TH, client=CFTH
    client = ""
    market = ""
    camp_m = re.search(r"MCSP_([A-Z]{2})_([A-Z0-9]+)_", text, re.I)
    if camp_m:
        market = camp_m.group(1).upper()
        client = camp_m.group(2).upper()

    # Fallback: Advertiser field (may be agency name)
    if not client:
        adv_m  = re.search(r"Advertiser[:\s]*([^\n]+)", text, re.I)
        client = adv_m.group(1).strip() if adv_m else "UNKNOWN"
        # If it's the agency name, mark as unknown
        if re.search(r"saatchi|m&c|mcsaatchi", client, re.I):
            client = "UNKNOWN"

    if not client:
        client = "UNKNOWN"

    # ── Invoice total ─────────────────────────────────────────────
    tot_m         = re.search(r"Invoice\s*Total[:\s]*([\d,]+\.\d{2})", text, re.I)
    invoice_total = clean_amount(tot_m.group(1)) if tot_m else None

    # Prefer subtotal (ex-VAT) if available
    sub_m    = re.search(r"Subtotal[:\s]*([\d,]+\.\d{2})", text, re.I)
    subtotal = clean_amount(sub_m.group(1)) if sub_m else None

    # ── Per-campaign rows ─────────────────────────────────────────
    rows = []
    line_pattern = re.compile(r"^\d+\s+(.+?)\s+([\d,]+\.\d{2})\s*$", re.MULTILINE)
    for m in line_pattern.finditer(text):
        campaign_name = m.group(1).strip()
        amount        = clean_amount(m.group(2))
        if re.search(r"subtotal|invoice total|freight|vat|gst", campaign_name, re.I):
            continue
        if amount is None:
            continue
        cid_m       = re.search(r"<([A-Z0-9]+)>", campaign_name)
        campaign_id = cid_m.group(1) if cid_m else ""
        rows.append({
            "Year":             2026,
            "Supplier Name":    "Meta",
            "Ad Account ID":    account_id,
            "Month of Service": billing_period,
            "Month of Billing": billing_period,
            "Client":           client,
            "Market":           market,
            "Invoice number":   invoice_number,
            "Campaign":         campaign_name,
            "Campaign ID":      campaign_id,
            "Currency":         currency,
            "Amount":           amount,
        })

    # Fallback: single summary row
    if not rows:
        rows = [{
            "Year":             2026,
            "Supplier Name":    "Meta",
            "Ad Account ID":    account_id,
            "Month of Service": billing_period,
            "Month of Billing": billing_period,
            "Client":           client,
            "Market":           market,
            "Invoice number":   invoice_number,
            "Campaign":         "",
            "Campaign ID":      "",
            "Currency":         currency,
            "Amount":           subtotal or invoice_total,
        }]

    print(f"  [OK] Meta: invoice {invoice_number} | Client: {client} | Market: {market} | {currency} | {len(rows)} row(s) | Total: {invoice_total}")
    return rows


# -----------------------------------------------------------------
# EXCEL FORMATTER
# -----------------------------------------------------------------
def format_sheet(ws, palette_key, amount_col_names=None):
    pal        = COLOURS[palette_key]
    hdr_fill   = PatternFill("solid", fgColor=pal["header_bg"])
    alt_fill   = PatternFill("solid", fgColor=pal["row_alt"])
    white_fill = PatternFill("solid", fgColor=WHITE)
    border     = make_border()
    amount_col_names = amount_col_names or []

    amt_indices = {
        ci for ci in range(1, ws.max_column + 1)
        if ws.cell(1, ci).value in amount_col_names
    }

    for cell in ws[1]:
        cell.fill      = hdr_fill
        cell.font      = Font(bold=True, color=WHITE, size=10)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border    = border
    ws.row_dimensions[1].height = 30

    for ri in range(2, ws.max_row + 1):
        fill = alt_fill if ri % 2 == 0 else white_fill
        for ci in range(1, ws.max_column + 1):
            cell           = ws.cell(ri, ci)
            cell.fill      = fill
            cell.border    = border
            cell.alignment = Alignment(vertical="center", wrap_text=False)
            if ci in amt_indices:
                cell.number_format = "#,##0.00"

    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes    = "A2"

    for ci in range(1, ws.max_column + 1):
        col_letter = get_column_letter(ci)
        max_len    = max(
            (len(str(ws.cell(r, ci).value or "")) for r in range(1, ws.max_row + 1)),
            default=10
        )
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 55)


# -----------------------------------------------------------------
# SUMMARY BUILDER
# -----------------------------------------------------------------
def build_summary(ws, sheet_map):
    border      = make_border("CCCCCC")
    thin_border = make_border("E0E0E0")

    ws.merge_cells("A1:G1")
    c = ws["A1"]
    c.value     = "ACCT-108  |  Master Invoice Tracker 2026  -  Summary"
    c.font      = Font(bold=True, color=DARK, size=13)
    c.fill      = PatternFill("solid", fgColor="F0F4F8")
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.border    = border
    ws.row_dimensions[1].height = 36

    col_headers = ["Currency", "Supplier", "Sheet", "Clients", "# Invoices", "# Campaigns/Rows", "Total Amount"]
    hdr_fill    = PatternFill("solid", fgColor="2E4057")
    for ci, h in enumerate(col_headers, 1):
        cell = ws.cell(2, ci, h)
        cell.fill      = hdr_fill
        cell.font      = Font(bold=True, color=WHITE, size=10)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border    = border
    ws.row_dimensions[2].height = 26

    sheet_labels = {
        "Adsjoy":          "AdsJoy",
        "Apple (ASA)":     "Apple (ASA)",
        "Google":          "Google",
        "Meta (facebook)": "Meta (Facebook)",
    }

    rows = []
    for sheet_name, df in sheet_map.items():
        if df.empty:
            continue
        amt_col = next((c for c in ["Amount", "Invoice Total", "Subtotal"] if c in df.columns), None)
        cur_col = next((c for c in df.columns if c.strip() == "Currency"), None)
        if not cur_col:
            continue
        for currency, grp in df.groupby(cur_col):
            currency = str(currency).strip()
            if not currency:
                continue
            total      = grp[amt_col].sum() if amt_col else 0
            n_rows     = len(grp)
            client_col = "Client" if "Client" in grp.columns else None
            clients    = ", ".join(sorted(grp[client_col].dropna().astype(str).str.strip().unique())) if client_col else "-"
            inv_col    = next((c for c in grp.columns if "invoice" in c.lower() and "number" in c.lower()), None)
            n_inv      = grp[inv_col].nunique() if inv_col else n_rows
            rows.append({
                "currency": currency,
                "supplier": sheet_labels.get(sheet_name, sheet_name),
                "sheet":    sheet_name,
                "clients":  clients,
                "n_inv":    n_inv,
                "n_rows":   n_rows,
                "total":    total,
            })

    currency_order = ["IDR", "MYR", "SGD", "USD"]
    rows.sort(key=lambda r: (
        currency_order.index(r["currency"]) if r["currency"] in currency_order else 99,
        r["supplier"]
    ))

    ri       = 3
    last_cur = None
    row_ctr  = 0

    for row in rows:
        cur = row["currency"]
        if cur != last_cur:
            cur_fg = CURRENCY_HEADER.get(cur, "333333")
            ws.merge_cells(f"A{ri}:G{ri}")
            cell = ws.cell(ri, 1, f"  {cur}  -  {cur} Invoices")
            cell.fill      = PatternFill("solid", fgColor=cur_fg)
            cell.font      = Font(bold=True, color=WHITE, size=10)
            cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
            cell.border    = make_border(cur_fg)
            ws.row_dimensions[ri].height = 22
            ri      += 1
            last_cur = cur
            row_ctr  = 0

        row_ctr += 1
        fill = (PatternFill("solid", fgColor=CURRENCY_COLOURS.get(cur, "F5F5F5"))
                if row_ctr % 2 == 0
                else PatternFill("solid", fgColor=WHITE))

        values = [cur, row["supplier"], row["sheet"], row["clients"],
                  row["n_inv"], row["n_rows"], row["total"]]
        for ci, val in enumerate(values, 1):
            cell = ws.cell(ri, ci, val)
            cell.fill      = fill
            cell.border    = thin_border
            cell.alignment = Alignment(vertical="center", wrap_text=False)
            cell.font      = Font(color=DARK, size=10, bold=(ci == 7))
            if ci == 7:
                cell.number_format = "#,##0.00"
        ws.row_dimensions[ri].height = 20
        ri += 1

    for i, w in enumerate([10, 18, 18, 38, 13, 18, 18], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "A3"


# -----------------------------------------------------------------
# DEDUP HELPER
# -----------------------------------------------------------------
def append_new_rows(existing_df, new_rows, key_col):
    if not new_rows:
        return existing_df
    new_df = pd.DataFrame(new_rows)
    if existing_df.empty:
        return new_df
    if key_col not in existing_df.columns or key_col not in new_df.columns:
        return pd.concat([existing_df, new_df], ignore_index=True)
    existing_keys = existing_df[key_col].astype(str).str.strip().tolist()
    filtered      = new_df[~new_df[key_col].astype(str).str.strip().isin(existing_keys)]
    skipped       = len(new_df) - len(filtered)
    if skipped:
        print(f"  [SKIP] {skipped} duplicate(s) not re-added")
    if len(filtered):
        print(f"  [ADD]  {len(filtered)} new row(s) added")
    return pd.concat([existing_df, filtered], ignore_index=True)


# -----------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------
def main():
    print("=" * 65)
    print("  ACCT-108 Invoice Extractor  |  v5.0")
    print("  AdsJoy | Apple ASA | Google | Meta (Facebook)")
    print("  [PDF-content-first detection]")
    print("=" * 65)

    os.makedirs(INPUT_FOLDER,  exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    if not os.path.exists(TRACKER_PATH):
        print(f"\n[ERR] Tracker not found: {TRACKER_PATH}")
        print("      Please place your tracker in the Input/ folder and re-run.")
        sys.exit(1)

    # 1. Load tracker
    print(f"\n[LOAD] Loading tracker from Input/...")
    tracker_sheets = pd.read_excel(TRACKER_PATH, sheet_name=None, header=0)
    df_adsjoy = fix_date_columns(tracker_sheets.get("Adsjoy",          pd.DataFrame()))
    df_apple  = fix_date_columns(tracker_sheets.get("Apple (ASA)",     pd.DataFrame()))
    df_google = fix_date_columns(tracker_sheets.get("Google",          pd.DataFrame()))
    df_meta   = fix_date_columns(tracker_sheets.get("Meta (facebook)", pd.DataFrame()))

    new_adsjoy, new_apple, new_google, new_meta = [], [], [], []

    # 2. Scan invoices (reads PDF text once, detects supplier from content)
    invoices = scan_invoices(INVOICE_FOLDER)
    print(f"\n[SCAN] Found {len(invoices)} PDF invoice(s) across all subfolders\n")

    for fpath, supplier, text, tables in invoices:
        fname = os.path.basename(fpath)
        print(f"[PDF]  {fname}  ->  [{supplier.upper()}]")

        if supplier == "adsjoy":
            result = parse_adsjoy_pdf(fpath, text, tables)
            if result:
                new_adsjoy.extend(result)

        elif supplier == "apple":
            result = parse_apple_pdf(fpath, text, tables, df_apple)
            if result:
                new_apple.extend(result)

        elif supplier == "google":
            result = parse_google_pdf(fpath, text, tables, df_google)
            if result:
                new_google.extend(result)

        elif supplier == "meta":
            result = parse_meta_pdf(fpath, text, tables)
            if result:
                new_meta.extend(result)

        else:
            print("  [WARN] Unknown supplier — skipped")

    # 3. Merge
    print("\n[MERGE] Merging into tracker sheets...")
    df_adsjoy = append_new_rows(df_adsjoy, new_adsjoy, "Invoice number")
    df_apple  = append_new_rows(df_apple,  new_apple,  "Invoice number")
    df_google = append_new_rows(df_google, new_google, "Invoice number")
    df_meta   = append_new_rows(df_meta,   new_meta,   "Invoice number")

    sheet_map = {
        "Adsjoy":          df_adsjoy,
        "Apple (ASA)":     df_apple,
        "Google":          df_google,
        "Meta (facebook)": df_meta,
    }

    # 4. Write Excel
    print(f"\n[WRITE] Writing -> Output/...")
    with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
        pd.DataFrame().to_excel(writer, sheet_name="Summary", index=False)
        for sname, df in sheet_map.items():
            df.to_excel(writer, sheet_name=sname, index=False)

    # 5. Format
    print("[FORMAT] Applying formatting...")
    wb = load_workbook(OUTPUT_PATH)

    fmt_cfg = {
        "Adsjoy":          ("adsjoy", ["Amount"]),
        "Apple (ASA)":     ("apple",  ["Amount"]),
        "Google":          ("google", ["Amount"]),
        "Meta (facebook)": ("meta",   ["Amount"]),
    }
    for sname, (pal, amt_cols) in fmt_cfg.items():
        if sname in wb.sheetnames:
            format_sheet(wb[sname], pal, amount_col_names=amt_cols)

    build_summary(wb["Summary"], sheet_map)
    wb.move_sheet("Summary", offset=-(len(wb.sheetnames) - 1))

    wb.save(OUTPUT_PATH)
    print("\n[DONE] Extraction complete!")
    print(f"       Output -> Output/ACCT-108 Master Invoice Tracker 2026 - Updated.xlsx")
    print("=" * 65)


if __name__ == "__main__":
    main()