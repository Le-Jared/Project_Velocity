"""
ACCT-108 | Invoice Data Extractor → Master Tracker  v4.1
=========================================================
Supports : AdsJoy · Apple (ASA) · Google · Meta (Facebook)

Usage
-----
1. Place this script in your project folder
2. Drop ALL invoice PDFs into ./invoices/
   (subfolders like sgd/ usd/ myr/ are scanned automatically)
3. Confirm TRACKER_PATH and OUTPUT_PATH below
4. Run:  python invoice_extractor.py
"""

import os
import re
import warnings
import pdfplumber
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# ⚙️  CONFIG
# ─────────────────────────────────────────────────────────────
TRACKER_PATH   = "ACCT-108 Master Invoice Tracker 2026.xlsx"
INVOICE_FOLDER = "./invoices"
OUTPUT_PATH    = "ACCT-108 Master Invoice Tracker 2026 - Updated.xlsx"

# ─────────────────────────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────────────────────────
COLOURS = {
    "adsjoy": {"header_bg": "1F3864", "row_alt": "DCE6F1"},
    "apple":  {"header_bg": "1C1C1E", "row_alt": "E8E8E8"},
    "google": {"header_bg": "1A73E8", "row_alt": "E8F0FE"},
    "meta":   {"header_bg": "1877F2", "row_alt": "E7F0FD"},
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
WHITE = "FFFFFF"
DARK  = "1A1A1A"

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def clean_amount(val):
    if val is None:
        return None
    val = re.sub(r"[^\d.-]", "", str(val).replace(",", "").replace(" ", "").strip())
    try:
        return float(val)
    except ValueError:
        return None


def detect_supplier(filename):
    fname = os.path.basename(filename).upper()
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
        for f in sorted(files):
            if f.lower().endswith(".pdf"):
                results.append((os.path.join(dirpath, f), detect_supplier(f)))
    return results


def billing_period_to_str(raw):
    if not raw:
        return ""
    m = re.match(r"([A-Za-z]{3})-?(\d{2})$", raw.strip())
    return f"{m.group(1).capitalize()} 20{m.group(2)}" if m else raw.strip()


def fix_date_columns(df):
    """Convert datetime columns → 'Month YYYY' strings."""
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


# ─────────────────────────────────────────────────────────────
# PARSER 1 — ADSJOY
# Tracker columns: Month | Supplier Name | Month of Service |
#   Month of Billing | Client | Invoice number | Campaign |
#   Campaign ID | Currency  | Amount
# ─────────────────────────────────────────────────────────────
def parse_adsjoy_pdf(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        full_text  = ""
        all_tables = []
        for page in pdf.pages:
            full_text  += page.extract_text() or ""
            all_tables += page.extract_tables() or []

    inv_m = re.search(
        r"Invoice\s*(?:No\.?|Number|#)?\s*[:\s]*([0-9\-/A-Za-z]+(?:/[0-9A-Za-z]+)*)",
        full_text
    )
    invoice_number = inv_m.group(1).strip() if inv_m else ""

    fname    = os.path.basename(pdf_path)
    client_m = re.search(r"SAATCHI_([A-Z]+)_", fname, re.I)
    client   = client_m.group(1) if client_m else ""
    month_m  = re.search(r"_([A-Za-z]{3})_(\d{2})_", fname)
    month_of_svc = f"{month_m.group(1).capitalize()} 20{month_m.group(2)}" if month_m else ""

    cur_m    = re.search(r"\b(USD|INR|SGD|IDR|MYR|AUD|GBP)\b", full_text)
    currency = cur_m.group(1) if cur_m else "USD"

    amount = None
    for table in all_tables:
        for row in table:
            row_text = " ".join(str(c) for c in row if c)
            if re.search(r"total|grand total|amount due", row_text, re.I):
                candidates = [clean_amount(n) for n in re.findall(r"[\d,]+\.?\d*", row_text)
                              if clean_amount(n) and clean_amount(n) > 100]
                if candidates:
                    amount = max(candidates)
                    break
        if amount:
            break
    if not amount:
        m = re.search(r"(?:Total|Grand Total|Amount Due)[^\n$]*\$?\s*([\d,]+\.?\d*)", full_text, re.I)
        if m:
            amount = clean_amount(m.group(1))

    print(f"  ✅ AdsJoy: invoice {invoice_number} | Client: {client} | {currency} {amount}")
    return [{
        "Month":            2026,
        "Supplier Name":    "AdsJoy",
        "Month of Service": month_of_svc,
        "Month of Billing": month_of_svc,
        "Client":           client,
        "Invoice number":   invoice_number,
        "Campaign":         client,
        "Campaign ID":      "",
        "Currency ":        currency,   # trailing space matches tracker header exactly
        "Amount":           amount,
    }]


# ─────────────────────────────────────────────────────────────
# PARSER 2 — APPLE (ASA)  [tracker-first]
# Tracker columns: Month | Supplier Name | Client |
#   Month of Service | Month of Billing | Invoice number |
#   Campaign | Campaign ID | Currency | Amount
# ─────────────────────────────────────────────────────────────
def parse_apple_pdf(pdf_path, tracker_df=None):
    fname = os.path.basename(pdf_path)
    inv_m = re.search(r"(Q\d+)", fname, re.I)
    invoice_number = inv_m.group(1) if inv_m else ""

    if not invoice_number:
        with pdfplumber.open(pdf_path) as pdf:
            text = "".join(p.extract_text() or "" for p in pdf.pages)
        m = re.search(r"Invoice Number\s*[:\s]*([A-Z0-9]+)", text, re.I)
        invoice_number = m.group(1).strip() if m else ""

    if tracker_df is not None and not tracker_df.empty:
        inv_col = next((c for c in tracker_df.columns
                        if "invoice" in c.lower() and "number" in c.lower()), None)
        if inv_col:
            matched = tracker_df[tracker_df[inv_col].astype(str).str.strip() == invoice_number.strip()]
            if not matched.empty:
                print(f"  ↩️  Apple: invoice {invoice_number} already in tracker — keeping {len(matched)} row(s)")
                return None  # skip: already handled

    print(f"  ⚠️  Apple: no tracker match for {invoice_number}")
    return []


# ─────────────────────────────────────────────────────────────
# PARSER 3 — GOOGLE  [tracker-first]
# Tracker columns: Year | Supplier Name | Ad Account Name |
#   Month of Service | Month of Billing | Client |
#   Invoice number | Campaign | Campaign ID | Currency | Amount
# ─────────────────────────────────────────────────────────────
def parse_google_pdf(pdf_path, tracker_df=None):
    fname = os.path.basename(pdf_path)
    inv_m = re.search(r"(\d{10})", fname)
    invoice_number = inv_m.group(1) if inv_m else ""

    if not invoice_number:
        with pdfplumber.open(pdf_path) as pdf:
            text = "".join(p.extract_text() or "" for p in pdf.pages)
        m = re.search(r"Invoice number[:\s.]*(\d+)", text, re.I)
        invoice_number = m.group(1).strip() if m else ""

    if tracker_df is not None and not tracker_df.empty:
        inv_col = next((c for c in tracker_df.columns
                        if "invoice" in c.lower() and "number" in c.lower()), None)
        if inv_col:
            matched = tracker_df[tracker_df[inv_col].astype(str).str.strip() == invoice_number.strip()]
            if not matched.empty:
                print(f"  ↩️  Google: invoice {invoice_number} already in tracker — keeping {len(matched)} row(s)")
                return None  # skip: already handled

    print(f"  ⚠️  Google: no tracker match for {invoice_number}")
    return []


# ─────────────────────────────────────────────────────────────
# PARSER 4 — META (FACEBOOK)
# Tracker columns: Year | Supplier Name | Ad Account ID |
#   Month of Service | Month of Billing | Client |
#   Invoice number | Campaign | Campaign ID | Currency | Amount
# ─────────────────────────────────────────────────────────────
def parse_meta_pdf(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "".join(p.extract_text() or "" for p in pdf.pages)

    inv_m          = re.search(r"Invoice\s*#[:\s]*(\d+)", full_text, re.I)
    invoice_number = inv_m.group(1).strip() if inv_m else ""

    period_m       = re.search(r"Billing Period[:\s]*([A-Za-z]{3}-\d{2})", full_text, re.I)
    billing_period = billing_period_to_str(period_m.group(1)) if period_m else ""

    adv_m      = re.search(r"Advertiser[:\s]*([^\n]+)", full_text, re.I)
    advertiser = adv_m.group(1).strip() if adv_m else ""

    acc_m      = re.search(r"Account Id\s*/\s*Group[:\s]*(\d+)", full_text, re.I)
    account_id = acc_m.group(1).strip() if acc_m else ""

    cur_m    = re.search(r"Invoice Currency[:\s]*(USD|SGD|MYR|IDR|AUD|GBP)", full_text, re.I)
    currency = cur_m.group(1).strip() if cur_m else ""
    if not currency:
        cur_m2 = re.search(r"\b(USD|SGD|MYR|IDR|AUD|GBP)\b", full_text)
        currency = cur_m2.group(1) if cur_m2 else ""

    tot_m         = re.search(r"Invoice Total[:\s]*([\d,]+\.\d{2})", full_text, re.I)
    invoice_total = clean_amount(tot_m.group(1)) if tot_m else None

    # Extract campaign-level line items
    # Pattern: line number, campaign name (with optional <CAMPAIGN_ID> tag), amount
    rows = []
    line_pattern = re.compile(
        r"^\d+\s+(.+?)\s+([\d,]+\.\d{2})\s*$", re.MULTILINE
    )
    for m in line_pattern.finditer(full_text):
        campaign_name = m.group(1).strip()
        amount        = clean_amount(m.group(2))
        # Skip summary/total lines
        if re.search(r"subtotal|invoice total|freight|vat|gst", campaign_name, re.I):
            continue
        if amount is None:
            continue
        # Extract Campaign ID from <TAG> if present
        cid_m       = re.search(r"<([A-Z0-9]+)>", campaign_name)
        campaign_id = cid_m.group(1) if cid_m else ""

        rows.append({
            "Year":             2026,
            "Supplier Name":    "Meta",
            "Ad Account ID":    account_id,
            "Month of Service": billing_period,
            "Month of Billing": billing_period,
            "Client":           advertiser,
            "Invoice number":   invoice_number,
            "Campaign":         campaign_name,
            "Campaign ID":      campaign_id,
            "Currency":         currency,
            "Amount":           amount,
        })

    # Fallback: if no line items extracted, return one summary row
    if not rows:
        rows = [{
            "Year":             2026,
            "Supplier Name":    "Meta",
            "Ad Account ID":    account_id,
            "Month of Service": billing_period,
            "Month of Billing": billing_period,
            "Client":           advertiser,
            "Invoice number":   invoice_number,
            "Campaign":         "",
            "Campaign ID":      "",
            "Currency":         currency,
            "Amount":           invoice_total,
        }]

    print(f"  ✅ Meta: invoice {invoice_number} | Client: {advertiser} | {currency} | {len(rows)} row(s) | Total: {invoice_total}")
    return rows


# ─────────────────────────────────────────────────────────────
# EXCEL FORMATTER — data sheets
# ─────────────────────────────────────────────────────────────
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

    # Header row
    for cell in ws[1]:
        cell.fill      = hdr_fill
        cell.font      = Font(bold=True, color=WHITE, size=10)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border    = border
    ws.row_dimensions[1].height = 30

    # Data rows
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


# ─────────────────────────────────────────────────────────────
# SUMMARY BUILDER — grouped by currency, sorted alphabetically
# ─────────────────────────────────────────────────────────────
def build_summary(ws, sheet_map):
    border      = make_border("CCCCCC")
    thin_border = make_border("E0E0E0")

    # Title
    ws.merge_cells("A1:G1")
    c = ws["A1"]
    c.value     = "ACCT-108  |  Master Invoice Tracker 2026  —  Summary"
    c.font      = Font(bold=True, color=DARK, size=13)
    c.fill      = PatternFill("solid", fgColor="F0F4F8")
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.border    = border
    ws.row_dimensions[1].height = 36

    # Column headers
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

    # Build data rows per supplier × currency
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

    # Sort: defined currency order, then supplier alphabetically
    currency_order = ["IDR", "MYR", "SGD", "USD"]
    rows.sort(key=lambda r: (
        currency_order.index(r["currency"]) if r["currency"] in currency_order else 99,
        r["supplier"]
    ))

    # Write rows with currency section headers
    ri          = 3
    last_cur    = None
    row_counter = 0

    for row in rows:
        cur = row["currency"]

        if cur != last_cur:
            cur_fg = CURRENCY_HEADER.get(cur, "333333")
            ws.merge_cells(f"A{ri}:G{ri}")
            cell = ws.cell(ri, 1, f"  {cur}  —  {cur} Invoices")
            cell.fill      = PatternFill("solid", fgColor=cur_fg)
            cell.font      = Font(bold=True, color=WHITE, size=10)
            cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
            cell.border    = make_border(cur_fg)
            ws.row_dimensions[ri].height = 22
            ri          += 1
            last_cur     = cur
            row_counter  = 0

        row_counter += 1
        fill = (PatternFill("solid", fgColor=CURRENCY_COLOURS.get(cur, "F5F5F5"))
                if row_counter % 2 == 0
                else PatternFill("solid", fgColor=WHITE))

        values = [cur, row["supplier"], row["sheet"], row["clients"],
                  row["n_inv"], row["n_rows"], row["total"]]
        for ci, val in enumerate(values, 1):
            cell = ws.cell(ri, ci, val)
            cell.fill      = fill
            cell.border    = thin_border
            cell.alignment = Alignment(vertical="center", wrap_text=False)
            cell.font      = Font(color=DARK, size=10,
                                  bold=(ci == 7))   # bold totals only
            if ci == 7:
                cell.number_format = "#,##0.00"
        ws.row_dimensions[ri].height = 20
        ri += 1

    # Column widths
    for i, w in enumerate([10, 18, 18, 38, 13, 18, 18], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "A3"
    # No auto-filter on summary


# ─────────────────────────────────────────────────────────────
# DEDUP HELPER
# ─────────────────────────────────────────────────────────────
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
        print(f"  ↩️  Skipped {skipped} duplicate(s)")
    if len(filtered):
        print(f"  ➕ {len(filtered)} new row(s) added")
    return pd.concat([existing_df, filtered], ignore_index=True)


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("  ACCT-108 Invoice Extractor  |  v4.1")
    print("  AdsJoy · Apple ASA · Google · Meta (Facebook)")
    print("=" * 65)

    # 1. Load existing tracker
    print("\n📂 Loading master tracker...")
    tracker_sheets = pd.read_excel(TRACKER_PATH, sheet_name=None, header=0)
    df_adsjoy = fix_date_columns(tracker_sheets.get("Adsjoy",          pd.DataFrame()))
    df_apple  = fix_date_columns(tracker_sheets.get("Apple (ASA)",     pd.DataFrame()))
    df_google = fix_date_columns(tracker_sheets.get("Google",          pd.DataFrame()))
    df_meta   = fix_date_columns(tracker_sheets.get("Meta (facebook)", pd.DataFrame()))

    new_adsjoy, new_meta = [], []

    # 2. Scan all PDFs recursively
    invoices = scan_invoices(INVOICE_FOLDER)
    print(f"\n🔍 Found {len(invoices)} PDF invoice(s) across all subfolders\n")

    for fpath, supplier in invoices:
        fname = os.path.basename(fpath)
        print(f"📄 {fname}  →  [{supplier.upper()}]")

        if supplier == "adsjoy":
            new_adsjoy.extend(parse_adsjoy_pdf(fpath))
        elif supplier == "apple":
            parse_apple_pdf(fpath, df_apple)
        elif supplier == "google":
            parse_google_pdf(fpath, df_google)
        elif supplier == "meta":
            new_meta.extend(parse_meta_pdf(fpath))
        else:
            print("  ⚠️  Unknown supplier — skipped")

    # 3. Merge
    print("\n📊 Merging into tracker sheets...")
    df_adsjoy = append_new_rows(df_adsjoy, new_adsjoy, "Invoice number")
    df_meta   = append_new_rows(df_meta,   new_meta,   "Invoice number")
    # Apple & Google: tracker rows preserved as-is (tracker-first)

    sheet_map = {
        "Adsjoy":          df_adsjoy,
        "Apple (ASA)":     df_apple,
        "Google":          df_google,
        "Meta (facebook)": df_meta,
    }

    # 4. Write Excel
    print(f"\n💾 Writing → {OUTPUT_PATH}")
    with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
        pd.DataFrame().to_excel(writer, sheet_name="📊 Summary", index=False)
        for sname, df in sheet_map.items():
            df.to_excel(writer, sheet_name=sname, index=False)

    # 5. Format
    print("🎨 Applying formatting...")
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

    build_summary(wb["📊 Summary"], sheet_map)
    wb.move_sheet("📊 Summary", offset=-(len(wb.sheetnames) - 1))

    wb.save(OUTPUT_PATH)
    print("\n✅ Done!")
    print(f"   Output saved → {OUTPUT_PATH}")
    print("=" * 65)


if __name__ == "__main__":
    main()
