import os
import re
import csv
import sys
import shutil
import warnings
import pdfplumber

from gemini_fallback import enrich_extraction, is_available as gemini_available

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")

INVOICE_FOLDER = "./invoices"
OUTPUT_ROOT    = "./Clients"
OUTPUT_FOLDER  = "./Output"
REPORT_PATH    = os.path.join(OUTPUT_FOLDER, "invoice_sort_report.csv")

CURRENCY_MARKET = {
    "MYR": "MY", "SGD": "SG", "IDR": "ID",
    "PHP": "PH", "USD": "USD", "GBP": "GB", "AUD": "AU",
}

MONTH_NAMES = {
    "jan": "January",  "feb": "February", "mar": "March",
    "apr": "April",    "may": "May",       "jun": "June",
    "jul": "July",     "aug": "August",    "sep": "September",
    "oct": "October",  "nov": "November",  "dec": "December",
}

META_ACCOUNT_CLIENT = {
    "10472231667355": "BHC",
    "10572631630900": "LGL",
}

SUPPLIER_NAMES = {
    "meta": "Meta", "google": "Google",
    "apple": "Apple", "adsjoy": "AdsJoy",
}


def read_pdf_text(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        return "".join(p.extract_text() or "" for p in pdf.pages)


def detect_supplier(text, filename):
    t     = text.upper()
    fname = os.path.basename(filename).upper()

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
            if not f.lower().endswith(".pdf"):
                continue
            fpath = os.path.join(dirpath, f)
            try:
                text = read_pdf_text(fpath)
            except Exception as e:
                print(f"  [ERR] Could not read {f}: {e}")
                text = ""
            supplier = detect_supplier(text, fpath)
            results.append((fpath, supplier, text))
    return results


def billing_period_to_parts(raw):
    if not raw:
        return None, None
    raw = raw.strip()

    m = re.match(r"([A-Za-z]{3})-(\d{2})$", raw)
    if m:
        return MONTH_NAMES.get(m.group(1).lower(), m.group(1).capitalize()), f"20{m.group(2)}"

    m = re.match(r"\d{1,2}\s+([A-Za-z]{3,})\s+(\d{4})", raw)
    if m:
        mon = m.group(1).capitalize()
        return MONTH_NAMES.get(mon[:3].lower(), mon), m.group(2)

    m = re.match(r"([A-Za-z]{3,})\s+(\d{4})$", raw)
    if m:
        mon = m.group(1).capitalize()
        return MONTH_NAMES.get(mon[:3].lower(), mon), m.group(2)

    return None, None


def make_month_tag(month_name, year):
    abbr = month_name[:3].upper() if month_name else "UNK"
    yr   = year[-2:] if year else "00"
    return f"{abbr}{yr}"


def safe_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()


def extract_meta(text, filename):
    inv_m          = re.search(r"Invoice\s*#[:\s]*(\d+)", text, re.I)
    invoice_number = inv_m.group(1).strip() if inv_m else "UNKNOWN"

    period_m    = re.search(r"Billing\s*Period[:\s]*([A-Za-z]{3}-\d{2})", text, re.I)
    month, year = billing_period_to_parts(period_m.group(1) if period_m else "")

    cur_m    = re.search(r"Invoice\s*Currency[:\s]*(USD|SGD|MYR|IDR|AUD|GBP|PHP)", text, re.I)
    currency = cur_m.group(1).upper() if cur_m else ""
    if not currency:
        cur_m2   = re.search(r"\b(USD|SGD|MYR|IDR|AUD|GBP|PHP)\b", text)
        currency = cur_m2.group(1).upper() if cur_m2 else "USD"

    client = ""
    market = ""
    camp_m = re.search(r"MCSP_([A-Z]{2})_([A-Z0-9]+)_", text, re.I)
    if camp_m:
        market = camp_m.group(1).upper()
        client = camp_m.group(2).upper()

    if not client:
        acc_m      = re.search(r"Account\s*Id\s*/\s*Group[:\s]*(\d+)", text, re.I)
        account_id = acc_m.group(1).strip() if acc_m else ""
        client     = META_ACCOUNT_CLIENT.get(account_id, "")

    if not client:
        adv_m = re.search(r"Advertiser[:\s]*([^\n]+)", text, re.I)
        if adv_m:
            val = adv_m.group(1).strip()
            if not re.search(r"saatchi|m&c|mcsaatchi", val, re.I):
                client = safe_filename(val).upper()

    if not market:
        market = CURRENCY_MARKET.get(currency, currency)

    if not client:
        client = "UNKNOWN"

    result = {
        "client":         client,
        "supplier":       SUPPLIER_NAMES["meta"],
        "market":         market,
        "month":          month or "UNKNOWN",
        "year":           year  or "UNKNOWN",
        "invoice_number": safe_filename(invoice_number),
    }

    if gemini_available():
        result = enrich_extraction(result, text, "meta", pdf_path=filename)

    return result


def extract_google(text, filename):
    fname = os.path.basename(filename)

    inv_m          = re.search(r"Invoice\s*number[:\s.]*(\d+)", text, re.I)
    invoice_number = inv_m.group(1).strip() if inv_m else ""
    if not invoice_number:
        fn_m           = re.search(r"(\d{10})", fname)
        invoice_number = fn_m.group(1) if fn_m else "UNKNOWN"

    month, year = None, None
    sum_m = re.search(r"Summary\s+for\s+\d{1,2}\s+([A-Za-z]+)\s+(\d{4})", text, re.I)
    if sum_m:
        mon   = sum_m.group(1).capitalize()
        month = MONTH_NAMES.get(mon[:3].lower(), mon)
        year  = sum_m.group(2)

    if not month:
        period_m    = re.search(r"(?:Billing|Invoice)\s*Period[:\s]*([A-Za-z]{3}-\d{2})", text, re.I)
        month, year = billing_period_to_parts(period_m.group(1) if period_m else "")

    cur_m    = re.search(r"\b(IDR|MYR|SGD|PHP|USD|GBP|AUD)\b", text)
    currency = cur_m.group(1).upper() if cur_m else "USD"

    client = "UNKNOWN"
    market = CURRENCY_MARKET.get(currency, currency)

    camp_m = re.search(r"MCSP_([A-Z]{2})_([A-Z0-9]+)_", text, re.I)
    if camp_m:
        market = camp_m.group(1).upper()
        client = camp_m.group(2).upper()

    if client == "UNKNOWN":
        acc_m = re.search(r"^Account:\s*([A-Za-z0-9]+)", text, re.I | re.MULTILINE)
        if acc_m:
            client = acc_m.group(1).strip().upper()

    result = {
        "client":         client,
        "supplier":       SUPPLIER_NAMES["google"],
        "market":         market,
        "month":          month or "UNKNOWN",
        "year":           year  or "UNKNOWN",
        "invoice_number": safe_filename(invoice_number),
    }

    if gemini_available():
        result = enrich_extraction(result, text, "google", pdf_path=filename)

    return result


def extract_apple(text, filename):
    fname = os.path.basename(filename)

    inv_m          = re.search(r"(Q\d+)", fname, re.I)
    invoice_number = inv_m.group(1).upper() if inv_m else ""
    if not invoice_number:
        m              = re.search(r"Invoice\s*Number[:\s]*([A-Z0-9]+)", text, re.I)
        invoice_number = m.group(1).strip() if m else "UNKNOWN"

    client   = ""
    client_m = re.search(r"\bClient\s*[:\s]+([A-Z]{2,6})\b", text, re.I)
    if client_m:
        val = client_m.group(1).strip().upper()
        if val not in ("NAME", "AND", "ADDRESS", "NUMBER", "ID", "THE"):
            client = val

    if not client:
        order_m = re.search(r"Order\s*Number\s*[:\s]*([A-Z]{2,6})\d*", text, re.I)
        if order_m:
            client = order_m.group(1).strip().upper()

    if not client:
        desc_m = re.search(
            r"Description\s*[:\s]*\(S\)[^\n]+\s+([A-Z]{2,6})\s*$",
            text, re.I | re.MULTILINE
        )
        if desc_m:
            client = desc_m.group(1).strip().upper()

    if not client:
        client = "UNKNOWN"

    month, year = None, None
    bp_m = re.search(r"Billing\s*Period\s*[:\s]*\d{1,2}\s+([A-Za-z]+)\s+(\d{4})", text, re.I)
    if bp_m:
        mon   = bp_m.group(1).capitalize()
        month = MONTH_NAMES.get(mon[:3].lower(), mon)
        year  = bp_m.group(2)

    if not month:
        m2 = re.search(r"([A-Za-z]{3,})\s+(20\d{2})", text)
        if m2:
            mon   = m2.group(1).capitalize()
            month = MONTH_NAMES.get(mon[:3].lower(), mon)
            year  = m2.group(2)

    cur_m    = re.search(r"Currency\s*[:\s]*(USD|SGD|MYR|IDR|AUD|GBP|PHP)", text, re.I)
    currency = cur_m.group(1).upper() if cur_m else ""
    if not currency:
        cur_m2   = re.search(r"\b(USD|SGD|MYR|IDR|AUD|GBP|PHP)\b", text)
        currency = cur_m2.group(1).upper() if cur_m2 else "USD"

    market_m = re.search(r"\b(SG|MY|ID|TH|PH|MX|AU|GB|US)\b", text)
    market   = market_m.group(1).upper() if market_m else CURRENCY_MARKET.get(currency, currency)

    result = {
        "client":         client,
        "supplier":       SUPPLIER_NAMES["apple"],
        "market":         market,
        "month":          month or "UNKNOWN",
        "year":           year  or "UNKNOWN",
        "invoice_number": safe_filename(invoice_number),
    }

    if gemini_available():
        result = enrich_extraction(result, text, "apple", pdf_path=filename)

    return result


def extract_adsjoy(text, filename):
    fname = os.path.basename(filename)

    inv_m = re.search(r"Invoice[:\s#]*([0-9]{2}-[0-9]{2}/[A-Za-z]{3}/[0-9]+)", text, re.I)
    if not inv_m:
        inv_m = re.search(
            r"Invoice\s*(?:No\.?|Number|#)?\s*[:\s]*([0-9A-Za-z\-/]+)",
            text, re.I
        )
    invoice_number = inv_m.group(1).strip() if inv_m else "UNKNOWN"

    client   = ""
    client_m = re.search(r"\n([A-Z]{2,6})\s*\nFor\s+ADSJOY\s+DIGITAL", text, re.I)
    if client_m:
        client = client_m.group(1).strip().upper()

    if not client:
        client_m2 = re.search(r"For\s+ADSJOY\s+DIGITAL\s*\n([A-Z]{2,6})\s", text, re.I)
        if client_m2:
            client = client_m2.group(1).strip().upper()

    if not client:
        client_m3 = re.search(
            r"\$[\d,]+\.00\s*\nFor\s+ADSJOY\s+DIGITAL\s*\n([A-Z]{2,6})",
            text, re.I
        )
        if client_m3:
            client = client_m3.group(1).strip().upper()

    if not client:
        fn_m   = re.search(r"SAATCHI_([A-Z]+)_", fname, re.I)
        client = fn_m.group(1).upper() if fn_m else "UNKNOWN"

    month, year = None, None
    mos_m = re.search(r"([A-Za-z]{3})'(\d{2})", text)
    if mos_m:
        month = MONTH_NAMES.get(mos_m.group(1).lower(), mos_m.group(1).capitalize())
        year  = f"20{mos_m.group(2)}"

    if not month:
        fn_m2 = re.search(r"_([A-Za-z]{3})_(\d{2})_", fname)
        if fn_m2:
            month = MONTH_NAMES.get(fn_m2.group(1).lower(), fn_m2.group(1).capitalize())
            year  = f"20{fn_m2.group(2)}"

    cur_m    = re.search(r"\b(USD|SGD|MYR|IDR|AUD|GBP|PHP)\b", text)
    currency = cur_m.group(1).upper() if cur_m else "USD"

    result = {
        "client":         client,
        "supplier":       SUPPLIER_NAMES["adsjoy"],
        "market":         CURRENCY_MARKET.get(currency, currency),
        "month":          month or "UNKNOWN",
        "year":           year  or "UNKNOWN",
        "invoice_number": safe_filename(invoice_number),
    }

    if gemini_available():
        result = enrich_extraction(result, text, "adsjoy", pdf_path=filename)

    return result


def extract_info(text, filename, supplier):
    try:
        if supplier == "meta":
            return extract_meta(text, filename)
        elif supplier == "google":
            return extract_google(text, filename)
        elif supplier == "apple":
            return extract_apple(text, filename)
        elif supplier == "adsjoy":
            return extract_adsjoy(text, filename)
        return None
    except Exception as e:
        print(f"  [ERR] Extraction failed: {e}")
        return None


def build_destination(info):
    month_tag = make_month_tag(info["month"], info["year"])
    new_name  = (
        f"{info['client']}_"
        f"{info['supplier']}_"
        f"{info['market']}_"
        f"{month_tag}_"
        f"{info['invoice_number']}.pdf"
    )
    dest_dir = os.path.join(
        OUTPUT_ROOT,
        info["client"],
        info["market"],
        info["year"],
        info["month"],
    )
    return new_name, dest_dir


def main():
    print("=" * 65)
    print("  ACCT-108 Invoice Sorter  ")
    print("  Meta | Google | Apple | AdsJoy")
    print("  [PDF-content-first + Gemini fallback w/ native PDF]")
    print("=" * 65)

    if gemini_available():
        print("  [GEMINI] Fallback active — unknown fields resolved via AI")
        print("  [GEMINI] Native PDF mode auto-enabled for low-text invoices")
    else:
        print("  [GEMINI] Not configured — regex-only mode (set GEMINI_API_KEY to enable)")

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    invoices = scan_invoices(INVOICE_FOLDER)
    print(f"\n[SCAN] Found {len(invoices)} PDF invoice(s)\n")

    report_rows = []

    for fpath, supplier, text in invoices:
        fname = os.path.basename(fpath)
        print(f"[PDF]  {fname}  ->  [{supplier.upper()}]")

        if supplier == "unknown":
            print("  [WARN] Could not detect supplier — skipped")
            report_rows.append({
                "original_file": fname, "new_filename": "-", "destination": "-",
                "supplier": "UNKNOWN", "client": "-", "market": "-",
                "month": "-", "year": "-", "status": "SKIPPED - unknown supplier",
            })
            continue

        info = extract_info(text, fpath, supplier)
        if not info:
            print("  [ERR]  Extraction failed — skipped")
            report_rows.append({
                "original_file": fname, "new_filename": "-", "destination": "-",
                "supplier": supplier, "client": "-", "market": "-",
                "month": "-", "year": "-", "status": "SKIPPED - extraction error",
            })
            continue

        new_name, dest_dir = build_destination(info)
        dest_path          = os.path.join(dest_dir, new_name)

        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(fpath, dest_path)
        print(f"  [OK]  -> {dest_path}")

        report_rows.append({
            "original_file": fname,
            "new_filename":  new_name,
            "destination":   dest_path,
            "supplier":      info["supplier"],
            "client":        info["client"],
            "market":        info["market"],
            "month":         info["month"],
            "year":          info["year"],
            "status":        "OK - copied",
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
    print(f"  [DONE] {ok} file(s) sorted successfully")
    if skipped:
        print(f"  [WARN] {skipped} file(s) skipped — check report")
    print(f"  [RPT]  Audit report -> Output/invoice_sort_report.csv")
    print("=" * 65)


if __name__ == "__main__":
    main()