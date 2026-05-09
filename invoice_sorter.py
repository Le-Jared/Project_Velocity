import os
import re
import csv
import shutil
import warnings
import pdfplumber

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
INVOICE_FOLDER = "./invoices"
OUTPUT_ROOT    = "./Clients"
REPORT_PATH    = "invoice_sort_report.csv"

# ─────────────────────────────────────────────────────────────
# MAPPINGS
# ─────────────────────────────────────────────────────────────

CURRENCY_MARKET = {
    "MYR": "MY", "SGD": "SG", "IDR": "ID",
    "PHP": "PH", "USD": "USD", "GBP": "GB", "AUD": "AU",
}

MONTH_NAMES = {
    "Jan": "January",  "Feb": "February", "Mar": "March",
    "Apr": "April",    "May": "May",       "Jun": "June",
    "Jul": "July",     "Aug": "August",    "Sep": "September",
    "Oct": "October",  "Nov": "November",  "Dec": "December",
}

# Meta Ad Account ID → Client code
META_ACCOUNT_CLIENT = {
    "10472231667355": "BHC",
    "10572631630900": "LGL",
    # add more: "account_id": "CLIENT_CODE"
}

SUPPLIER_NAMES = {
    "meta": "Meta", "google": "Google",
    "apple": "Apple", "adsjoy": "AdsJoy",
}

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def detect_supplier(filename):
    """
    Order matters:
    1. AdsJoy  — filename contains ADSJOY
    2. Apple   — filename starts with Q + digits
    3. Meta    — filename starts with Transaction_
    4. Google  — filename starts with digits (10+)
    """
    fname = os.path.basename(filename).upper()
    if "ADSJOY" in fname:
        return "adsjoy"
    if re.match(r"Q\d+", fname):
        return "apple"
    if fname.startswith("TRANSACTION_"):
        return "meta"
    if re.match(r"\d{10}", fname):
        return "google"
    return "unknown"


def scan_invoices(root_folder):
    results = []
    for dirpath, _, files in os.walk(root_folder):
        for f in sorted(files):
            if f.lower().endswith(".pdf"):
                results.append(os.path.join(dirpath, f))
    return results


def billing_period_to_parts(raw):
    """
    Accepts:
      'Mar-26'       → ('March', '2026')
      'March 2026'   → ('March', '2026')
      '1 Mar 2026'   → ('March', '2026')
      'Mar 2026'     → ('March', '2026')
    """
    if not raw:
        return None, None
    raw = raw.strip()

    m = re.match(r"([A-Za-z]{3})-(\d{2})$", raw)
    if m:
        return MONTH_NAMES.get(m.group(1).capitalize(), m.group(1).capitalize()), f"20{m.group(2)}"

    m = re.match(r"\d{1,2}\s+([A-Za-z]{3,})\s+(\d{4})", raw)
    if m:
        mon = m.group(1).capitalize()
        return MONTH_NAMES.get(mon[:3], mon), m.group(2)

    m = re.match(r"([A-Za-z]{3,})\s+(\d{4})$", raw)
    if m:
        mon = m.group(1).capitalize()
        return MONTH_NAMES.get(mon[:3], mon), m.group(2)

    return None, None


def make_month_tag(month_name, year):
    abbr = month_name[:3].upper() if month_name else "UNK"
    yr   = year[-2:] if year else "00"
    return f"{abbr}{yr}"


def safe_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()


def read_pdf_text(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        return "".join(p.extract_text() or "" for p in pdf.pages)


# ─────────────────────────────────────────────────────────────
# EXTRACTORS
# ─────────────────────────────────────────────────────────────

def extract_meta(pdf_path):
    text = read_pdf_text(pdf_path)

    inv_m          = re.search(r"Invoice\s*#[:\s]*(\d+)", text, re.I)
    invoice_number = inv_m.group(1).strip() if inv_m else "UNKNOWN"

    period_m    = re.search(r"Billing Period[:\s]*([A-Za-z]{3}-\d{2})", text, re.I)
    month, year = billing_period_to_parts(period_m.group(1) if period_m else "")

    cur_m    = re.search(r"Invoice Currency[:\s]*(USD|SGD|MYR|IDR|AUD|GBP|PHP)", text, re.I)
    currency = cur_m.group(1).upper() if cur_m else ""
    if not currency:
        cur_m2   = re.search(r"\b(USD|SGD|MYR|IDR|AUD|GBP|PHP)\b", text)
        currency = cur_m2.group(1).upper() if cur_m2 else "USD"

    # Tier 1: Advertiser field — use if it's NOT the agency name
    adv_m  = re.search(r"Advertiser[:\s]*([^\n]+)", text, re.I)
    client = adv_m.group(1).strip() if adv_m else ""

    if not client or "saatchi" in client.lower() or "m&c" in client.lower():

        # Tier 2: Account ID → client map
        acc_m      = re.search(r"Account Id\s*/\s*Group[:\s]*(\d+)", text, re.I)
        account_id = acc_m.group(1).strip() if acc_m else ""
        client     = META_ACCOUNT_CLIENT.get(account_id, "")

        # Tier 3: Campaign label MCSP_[MARKET]_[CLIENT]_ pattern
        if not client:
            camp_m = re.search(r"(?:MCSP|mcsp)_[A-Z]{2}_([A-Z0-9]+)_", text, re.I)
            if camp_m:
                client = camp_m.group(1).upper()

        if not client:
            client = "UNKNOWN"

    return {
        "client":         safe_filename(client).upper(),
        "supplier":       SUPPLIER_NAMES["meta"],
        "market":         CURRENCY_MARKET.get(currency, currency),
        "month":          month or "UNKNOWN",
        "year":           year  or "UNKNOWN",
        "invoice_number": safe_filename(invoice_number),
    }


def extract_google(pdf_path):
    fname = os.path.basename(pdf_path)
    text  = read_pdf_text(pdf_path)

    inv_m          = re.search(r"(\d{10})", fname)
    invoice_number = inv_m.group(1) if inv_m else ""
    if not invoice_number:
        m = re.search(r"Invoice number[:\s.]*(\d+)", text, re.I)
        invoice_number = m.group(1).strip() if m else "UNKNOWN"

    # Month/Year from "Summary for D Mon YYYY"
    month, year = None, None
    sum_m = re.search(r"Summary for\s+\d{1,2}\s+([A-Za-z]{3,})\s+(\d{4})", text, re.I)
    if sum_m:
        mon   = sum_m.group(1).capitalize()
        month = MONTH_NAMES.get(mon[:3], mon)
        year  = sum_m.group(2)

    if not month:
        period_m    = re.search(r"(?:Billing Period|Invoice Period)[:\s]*([A-Za-z]{3}-\d{2})", text, re.I)
        month, year = billing_period_to_parts(period_m.group(1) if period_m else "")

    cur_m    = re.search(r"\b(IDR|MYR|SGD|PHP|USD|GBP|AUD)\b", text)
    currency = cur_m.group(1).upper() if cur_m else "USD"

    # Tier 1: MCSP_[MARKET]_[CLIENT]_ pattern
    client  = "UNKNOWN"
    camp_m  = re.search(r"(?:MCSP|mcsp)_[A-Z]{2}_([A-Z0-9]+)_", text, re.I)
    if camp_m:
        client = camp_m.group(1).upper()

    # Tier 2: mcsp_[CLIENT]_bau_ pattern (IDR invoices)
    if client == "UNKNOWN":
        camp_m2 = re.search(r"(?:MCSP|mcsp)_([A-Z0-9]+)_(?:bau|BAU)_", text, re.I)
        if camp_m2:
            client = camp_m2.group(1).upper()

    # Tier 3: "Account: [NAME]" field e.g. "Account: Ama", "Account: BMYFF"
    if client == "UNKNOWN":
        acc_m = re.search(r"^Account:\s*([A-Z0-9]+)\s*$", text, re.I | re.MULTILINE)
        if acc_m:
            client = acc_m.group(1).strip().upper()

    return {
        "client":         client,
        "supplier":       SUPPLIER_NAMES["google"],
        "market":         CURRENCY_MARKET.get(currency, currency),
        "month":          month or "UNKNOWN",
        "year":           year  or "UNKNOWN",
        "invoice_number": safe_filename(invoice_number),
    }


def extract_apple(pdf_path):
    fname = os.path.basename(pdf_path)
    text  = read_pdf_text(pdf_path)

    inv_m          = re.search(r"(Q\d+)", fname, re.I)
    invoice_number = inv_m.group(1).upper() if inv_m else "UNKNOWN"
    if invoice_number == "UNKNOWN":
        m = re.search(r"Invoice Number[:\s]*([A-Z0-9]+)", text, re.I)
        invoice_number = m.group(1).strip() if m else "UNKNOWN"

    # Month/Year from "Billing Period: 01 Mar 2026 - 31 Mar 2026"
    month, year = None, None
    bp_m = re.search(r"Billing Period\s*[:\s]*(\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})", text, re.I)
    if bp_m:
        month, year = billing_period_to_parts(bp_m.group(1))

    if not month:
        m2 = re.search(r"([A-Za-z]{3,})\s+(20\d{2})", text)
        if m2:
            mon   = m2.group(1).capitalize()
            month = MONTH_NAMES.get(mon[:3], mon)
            year  = m2.group(2)

    cur_m    = re.search(r"Currency\s*[:\s]*(USD|SGD|MYR|IDR|AUD|GBP|PHP)", text, re.I)
    currency = cur_m.group(1).upper() if cur_m else ""
    if not currency:
        cur_m2   = re.search(r"\b(USD|SGD|MYR|IDR|AUD|GBP|PHP)\b", text)
        currency = cur_m2.group(1).upper() if cur_m2 else "USD"

    # Tier 1: "Client : MF" field
    client   = "UNKNOWN"
    client_m = re.search(r"Client\s*[:\s]+([A-Z0-9]{2,10})\b", text, re.I)
    if client_m:
        val = client_m.group(1).strip().upper()
        if val not in ("NAME", "AND", "ADDRESS", "NUMBER", "ID"):
            client = val

    # Tier 2: Description line e.g. "(S)M&C SAATCHI MOBILE ASIA PACIFIC MARC" → last token
    if client == "UNKNOWN":
        desc_m = re.search(r"Description\s*[:\s]*\(S\)[^\n]+\s+([A-Z]{2,6})\s*$", text, re.I | re.MULTILINE)
        if desc_m:
            client = desc_m.group(1).strip().upper()

    return {
        "client":         client,
        "supplier":       SUPPLIER_NAMES["apple"],
        "market":         CURRENCY_MARKET.get(currency, currency),
        "month":          month or "UNKNOWN",
        "year":           year  or "UNKNOWN",
        "invoice_number": safe_filename(invoice_number),
    }


def extract_adsjoy(pdf_path):
    fname = os.path.basename(pdf_path)
    text  = read_pdf_text(pdf_path)

    # Invoice number from PDF e.g. "Invoice: 26-27/Apr/10"
    inv_m = re.search(r"Invoice[:\s#]*([0-9]{2}-[0-9]{2}/[A-Za-z]{3}/[0-9]+)", text, re.I)
    if not inv_m:
        inv_m = re.search(r"Invoice\s*(?:No\.?|Number|#)?\s*[:\s]*([0-9A-Za-z\-/]+)", text, re.I)
    invoice_number = inv_m.group(1).strip() if inv_m else "UNKNOWN"

    client_m = re.search(r"SAATCHI_([A-Z]+)_", fname, re.I)
    client   = client_m.group(1).upper() if client_m else "UNKNOWN"

    month_m = re.search(r"_([A-Za-z]{3})_(\d{2})_", fname)
    if month_m:
        month = MONTH_NAMES.get(month_m.group(1).capitalize(), month_m.group(1).capitalize())
        year  = f"20{month_m.group(2)}"
    else:
        period_m    = re.search(r"(?:From|Period)[:\s]*(\d{2}-[A-Za-z]{3}-\d{2})", text, re.I)
        month, year = billing_period_to_parts(period_m.group(1) if period_m else "")
        month, year = month or "UNKNOWN", year or "UNKNOWN"

    cur_m    = re.search(r"\b(USD|SGD|MYR|IDR|AUD|GBP|PHP)\b", text)
    currency = cur_m.group(1).upper() if cur_m else "USD"

    return {
        "client":         client,
        "supplier":       SUPPLIER_NAMES["adsjoy"],
        "market":         CURRENCY_MARKET.get(currency, currency),
        "month":          month,
        "year":           year,
        "invoice_number": safe_filename(invoice_number),
    }


# ─────────────────────────────────────────────────────────────
# CORE
# ─────────────────────────────────────────────────────────────

def extract_info(pdf_path, supplier):
    try:
        if supplier == "meta":
            return extract_meta(pdf_path)
        elif supplier == "google":
            return extract_google(pdf_path)
        elif supplier == "apple":
            return extract_apple(pdf_path)
        elif supplier == "adsjoy":
            return extract_adsjoy(pdf_path)
        return None
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


def build_destination(info):
    month_tag = make_month_tag(info["month"], info["year"])
    new_name  = f"{info['client']}_{info['supplier']}_{info['market']}_{month_tag}_{info['invoice_number']}.pdf"
    dest_dir  = os.path.join(OUTPUT_ROOT, info["client"], info["market"], info["year"], info["month"])
    return new_name, dest_dir


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  ACCT-108 Invoice Sorter  |  v2.1")
    print("  Meta · Google · Apple · AdsJoy")
    print("=" * 65)

    invoices = scan_invoices(INVOICE_FOLDER)
    print(f"\n🔍 Found {len(invoices)} PDF invoice(s)\n")

    report_rows = []

    for fpath in invoices:
        fname    = os.path.basename(fpath)
        supplier = detect_supplier(fname)
        print(f"📄 {fname}  →  [{supplier.upper()}]")

        if supplier == "unknown":
            print("  ⚠️  Could not detect supplier — skipped")
            report_rows.append({
                "original_file": fname, "new_filename": "-", "destination": "-",
                "supplier": "UNKNOWN", "client": "-", "market": "-",
                "month": "-", "year": "-", "status": "SKIPPED — unknown supplier",
            })
            continue

        info = extract_info(fpath, supplier)
        if not info:
            print("  ❌ Extraction failed — skipped")
            report_rows.append({
                "original_file": fname, "new_filename": "-", "destination": "-",
                "supplier": supplier, "client": "-", "market": "-",
                "month": "-", "year": "-", "status": "SKIPPED — extraction error",
            })
            continue

        new_name, dest_dir = build_destination(info)
        dest_path          = os.path.join(dest_dir, new_name)

        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(fpath, dest_path)
        print(f"  ✅ → {dest_path}")

        report_rows.append({
            "original_file": fname,
            "new_filename":  new_name,
            "destination":   dest_path,
            "supplier":      info["supplier"],
            "client":        info["client"],
            "market":        info["market"],
            "month":         info["month"],
            "year":          info["year"],
            "status":        "OK — copied",
        })

    with open(REPORT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "original_file", "new_filename", "destination",
            "supplier", "client", "market", "month", "year", "status"
        ])
        writer.writeheader()
        writer.writerows(report_rows)

    ok      = sum(1 for r in report_rows if r["status"].startswith("OK"))
    skipped = len(report_rows) - ok
    print("\n" + "=" * 65)
    print(f"  ✅ {ok} file(s) copied successfully")
    if skipped:
        print(f"  ⚠️  {skipped} file(s) skipped — check {REPORT_PATH}")
    print(f"  📋 Audit report → {REPORT_PATH}")
    print("=" * 65)


if __name__ == "__main__":
    main()
