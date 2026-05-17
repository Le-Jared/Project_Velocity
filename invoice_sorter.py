import os
import re
import csv
import sys
import shutil
import warnings
from time import perf_counter
from datetime import datetime
from calendar import month_name

import pdfplumber

from gemini_fallback import enrich_extraction, is_available as gemini_available


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")


INVOICE_FOLDER = "./invoices"
OUTPUT_ROOT = "./Clients"
OUTPUT_FOLDER = "./Output"
REPORT_PATH = os.path.join(OUTPUT_FOLDER, "invoice_sort_report.csv")

SEP = "=" * 72
SUB_SEP = "-" * 72

CURRENCY_MARKET = {
    "MYR": "MY",
    "SGD": "SG",
    "IDR": "ID",
    "PHP": "PH",
    "GBP": "GB",
    "AUD": "AU",
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

SUPPLIER_NAMES = {
    "meta": "Meta",
    "google": "Google",
    "apple": "Apple",
    "adsjoy": "AdsJoy",
}

SUPPLIER_ORDER = ["meta", "google", "apple", "adsjoy"]

MONTH_NAMES = {m[:3].lower(): m for m in month_name if m}

REPORT_FIELDS = [
    "original_file",
    "new_filename",
    "destination",
    "supplier",
    "client",
    "market",
    "month",
    "year",
    "status",
]


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
    print("ACCT-108 Invoice Sorter")
    print("Suppliers : Meta | Google | Apple | AdsJoy")
    print("Mode      : PDF-content-first + Gemini fallback")
    print(f"Started   : {now_str()}")
    print(SEP)

    if gemini_available():
        log("GEMINI", "Fallback active — unknown fields resolved via AI")
        log("GEMINI", "Native PDF mode auto-enabled for low-text invoices")
    else:
        log("GEMINI", "Not configured — regex-only mode")


def first_match(patterns, text, flags=re.I, group=1, default=""):
    if isinstance(patterns, str):
        patterns = [patterns]

    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(group).strip()

    return default


def safe_filename(value):
    value = str(value or "").strip()
    value = re.sub(r'[\\/*?:"<>|]', "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip() or "UNKNOWN"


def normalize_month(mon, year):
    if not mon or not year:
        return None, None

    month = MONTH_NAMES.get(mon[:3].lower(), mon.capitalize())
    year = str(year)

    if len(year) == 2:
        year = f"20{year}"

    return month, year


def billing_period_to_parts(raw):
    if not raw:
        return None, None

    raw = raw.strip()

    patterns = [
        r"([A-Za-z]{3})-(\d{2})$",
        r"\d{1,2}\s+([A-Za-z]{3,})\s+(\d{4})",
        r"([A-Za-z]{3,})\s+(\d{4})$",
    ]

    for pattern in patterns:
        match = re.match(pattern, raw)
        if match:
            return normalize_month(match.group(1), match.group(2))

    return None, None


def extract_currency(text, default="USD"):
    currency = first_match(r"\b(USD|SGD|MYR|IDR|AUD|GBP|PHP)\b", text)
    return currency.upper() if currency else default


def market_from_currency(currency):
    return CURRENCY_MARKET.get(currency, currency or "UNKNOWN")


def make_month_tag(month, year):
    month_tag = month[:3].upper() if month and month != "UNKNOWN" else "UNK"
    year_tag = str(year)[-2:] if year and year != "UNKNOWN" else "00"
    return f"{month_tag}{year_tag}"


def read_pdf_text(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        return "".join(page.extract_text() or "" for page in pdf.pages)


def detect_supplier(text, filename):
    text_upper = text.upper()
    filename_upper = os.path.basename(filename).upper()

    content_rules = [
        ("adsjoy", ["ADSJOY DIGITAL", "ADSJOY"]),
        ("apple", ["APPLE DISTRIBUTION", "APPLE SERVICES LATAM", "APPLE SEARCH ADS"]),
        ("meta", ["FACEBOOK", "META PLATFORMS"]),
        ("google", [
            "GOOGLE ADS",
            "PT GOOGLE",
            "GOOGLE LLC",
            "GOOGLE IRELAND",
            "GOOGLE ASIA PACIFIC",
            "COLLECTIONS@GOOGLE.COM",
        ]),
    ]

    for supplier, keywords in content_rules:
        if any(keyword in text_upper for keyword in keywords):
            return supplier

    if "ADSJOY" in filename_upper:
        return "adsjoy"
    if re.match(r"Q\d+", filename_upper):
        return "apple"
    if filename_upper.startswith("TRANSACTION_") or re.match(r"\d{12,}", filename_upper):
        return "meta"
    if re.match(r"\d{10}", filename_upper):
        return "google"

    return "unknown"


def scan_invoices(root_folder):
    invoices = []

    for dirpath, _, files in os.walk(root_folder):
        for filename in sorted(files):
            if not filename.lower().endswith(".pdf"):
                continue

            pdf_path = os.path.join(dirpath, filename)

            try:
                text = read_pdf_text(pdf_path)
            except Exception as e:
                log("ERR", f"Could not read {filename}: {e}", indent=2)
                text = ""

            supplier = detect_supplier(text, pdf_path)
            invoices.append((pdf_path, supplier, text))

    return invoices


def enrich_with_gemini(result, text, supplier, pdf_path):
    if not gemini_available():
        return result

    try:
        enriched = enrich_extraction(result, text, supplier, pdf_path=pdf_path) or {}
        merged = result.copy()
        merged.update({k: v for k, v in enriched.items() if v not in [None, ""]})
        return merged
    except Exception as e:
        log("WARN", f"Gemini enrichment failed for {os.path.basename(pdf_path)}: {e}", indent=2)
        return result


def normalize_info(info):
    normalized = {
        "client": safe_filename(info.get("client") or "UNKNOWN").upper(),
        "supplier": safe_filename(info.get("supplier") or "UNKNOWN"),
        "market": safe_filename(info.get("market") or "UNKNOWN").upper(),
        "month": safe_filename(info.get("month") or "UNKNOWN"),
        "year": safe_filename(info.get("year") or "UNKNOWN"),
        "invoice_number": safe_filename(info.get("invoice_number") or "UNKNOWN"),
    }

    if normalized["market"] in ["", "NONE"]:
        normalized["market"] = "UNKNOWN"

    return normalized


def make_info(client, supplier_key, market, month, year, invoice_number):
    return normalize_info({
        "client": client,
        "supplier": SUPPLIER_NAMES[supplier_key],
        "market": market,
        "month": month or "UNKNOWN",
        "year": year or "UNKNOWN",
        "invoice_number": invoice_number,
    })


def extract_common_month(text, filename=""):
    patterns = [
        r"Summary\s+for\s+\d{1,2}\s+([A-Za-z]+)\s+(\d{4})",
        r"Billing\s*Period\s*[:\s]*\d{1,2}\s+([A-Za-z]+)\s+(\d{4})",
        r"([A-Za-z]{3,})\s+(20\d{2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return normalize_month(match.group(1), match.group(2))

    period = first_match(r"(?:Billing|Invoice)\s*Period[:\s]*([A-Za-z]{3}-\d{2})", text)
    if period:
        return billing_period_to_parts(period)

    file_month = first_match(r"_([A-Za-z]{3})_(\d{2})_", filename, flags=re.I)
    if file_month:
        match = re.search(r"_([A-Za-z]{3})_(\d{2})_", filename, re.I)
        return normalize_month(match.group(1), match.group(2))

    return None, None


def extract_meta(text, filename):
    invoice_number = first_match(r"Invoice\s*#[:\s]*(\d+)", text) or "UNKNOWN"

    period = first_match(r"Billing\s*Period[:\s]*([A-Za-z]{3}-\d{2})", text)
    month, year = billing_period_to_parts(period)

    currency = first_match(r"Invoice\s*Currency[:\s]*(USD|SGD|MYR|IDR|AUD|GBP|PHP)", text).upper()
    currency = currency or extract_currency(text, "USD")

    client = ""
    market = ""

    campaign = re.search(r"MCSP_([A-Z]{2})_([A-Z0-9]+)_", text, re.I)
    if campaign:
        market = campaign.group(1).upper()
        client = campaign.group(2).upper()

    if not client:
        pac = re.search(r"mcspapac_([A-Z]{2})_[A-Z0-9]+_[^_]+_[A-Z]+_([A-Z]{2,6})_", text, re.I)
        if pac:
            market = market or pac.group(1).upper()
            client = pac.group(2).upper()

    if not market:
        text_upper = text.upper()
        market = next((v for k, v in META_ENTITY_MARKET.items() if k in text_upper), "")

    if not client:
        account_id = first_match([
            r"Account\s*Id\s*/\s*Group[:\s]*(\d+)",
            r"(?<!\d)(\d{13,15})(?!\d)",
        ], text)
        client = META_ACCOUNT_CLIENT.get(account_id, "")

    if not client:
        advertiser = first_match(r"Advertiser[:\s]*([^\n]+)", text)
        if advertiser and not re.search(r"saatchi|m&c|mcsaatchi", advertiser, re.I):
            client = advertiser.upper()

    market = market or market_from_currency(currency)
    client = client or "UNKNOWN"

    result = make_info(client, "meta", market, month, year, invoice_number)
    return normalize_info(enrich_with_gemini(result, text, "meta", filename))


def extract_google(text, filename):
    fname = os.path.basename(filename)

    invoice_number = first_match(r"Invoice\s*number[:\s.]*(\d+)", text)
    invoice_number = invoice_number or first_match(r"(\d{10})", fname) or "UNKNOWN"

    month, year = extract_common_month(text, fname)
    currency = extract_currency(text, "USD")

    client = ""
    market = market_from_currency(currency)

    campaign = re.search(r"MCSP_([A-Z]{2})_([A-Z0-9]+)_", text, re.I)
    if campaign:
        market = campaign.group(1).upper()
        client = campaign.group(2).upper()

    if not client:
        client = first_match(r"^Account:\s*([A-Za-z0-9]+)", text, flags=re.I | re.MULTILINE).upper()

    client = client or "UNKNOWN"

    result = make_info(client, "google", market, month, year, invoice_number)
    return normalize_info(enrich_with_gemini(result, text, "google", filename))


def extract_apple(text, filename):
    fname = os.path.basename(filename)

    invoice_number = first_match(r"(Q\d+)", fname, flags=re.I).upper()
    invoice_number = invoice_number or first_match(r"Invoice\s*Number[:\s]*([A-Z0-9]+)", text) or "UNKNOWN"

    client = first_match([
        r"\bClient\s*[:\s]+([A-Z]{2,6})\b",
        r"Order\s*Number\s*[:\s]*([A-Z]{2,6})\d*",
        r"Description\s*[:\s]*\(S\)[^\n]+\s+([A-Z]{2,6})\s*$",
    ], text, flags=re.I | re.MULTILINE).upper()

    if client in ("NAME", "AND", "ADDRESS", "NUMBER", "ID", "THE", ""):
        client = "UNKNOWN"

    month, year = extract_common_month(text, fname)

    currency = first_match(r"Currency\s*[:\s]*(USD|SGD|MYR|IDR|AUD|GBP|PHP)", text).upper()
    currency = currency or extract_currency(text, "USD")

    market = first_match(r"\b(SG|MY|ID|TH|PH|MX|AU|GB|US)\b", text).upper()
    market = market or market_from_currency(currency)

    result = make_info(client, "apple", market, month, year, invoice_number)
    return normalize_info(enrich_with_gemini(result, text, "apple", filename))


def extract_adsjoy(text, filename):
    fname = os.path.basename(filename)

    invoice_number = first_match([
        r"Invoice[:\s#]*([0-9]{2}-[0-9]{2}/[A-Za-z]{3}/[0-9]+)",
        r"Invoice\s*(?:No\.?|Number|#)?\s*[:\s]*([0-9A-Za-z\-/]+)",
    ], text) or "UNKNOWN"

    client = first_match([
        r"\n([A-Z]{2,6})\s*\nFor\s+ADSJOY\s+DIGITAL",
        r"For\s+ADSJOY\s+DIGITAL\s*\n([A-Z]{2,6})\s",
        r"\$[\d,]+\.00\s*\nFor\s+ADSJOY\s+DIGITAL\s*\n([A-Z]{2,6})",
    ], text).upper()

    if not client:
        client = first_match(r"SAATCHI_([A-Z]+)_", fname, flags=re.I).upper()

    month, year = None, None

    service_period = re.search(r"([A-Za-z]{3})'(\d{2})", text)
    if service_period:
        month, year = normalize_month(service_period.group(1), service_period.group(2))

    if not month:
        file_period = re.search(r"_([A-Za-z]{3})_(\d{2})_", fname, re.I)
        if file_period:
            month, year = normalize_month(file_period.group(1), file_period.group(2))

    currency = extract_currency(text, "USD")
    market = market_from_currency(currency)

    result = make_info(client or "UNKNOWN", "adsjoy", market, month, year, invoice_number)
    return normalize_info(enrich_with_gemini(result, text, "adsjoy", filename))


def extract_info(text, filename, supplier):
    extractors = {
        "meta": extract_meta,
        "google": extract_google,
        "apple": extract_apple,
        "adsjoy": extract_adsjoy,
    }

    try:
        extractor = extractors.get(supplier)
        return extractor(text, filename) if extractor else None
    except Exception as e:
        log("ERR", f"Extraction failed: {e}", indent=2)
        return None


def build_destination(info):
    month_tag = make_month_tag(info["month"], info["year"])

    new_filename = safe_filename(
        f"{info['client']}_"
        f"{info['supplier']}_"
        f"{info['market']}_"
        f"{month_tag}_"
        f"{info['invoice_number']}.pdf"
    )

    dest_dir = os.path.join(
        OUTPUT_ROOT,
        safe_filename(info["client"]),
        safe_filename(info["market"]),
        safe_filename(info["year"]),
        safe_filename(info["month"]),
    )

    return new_filename, dest_dir


def make_report_row(
    original_file,
    status,
    new_filename="-",
    destination="-",
    supplier="-",
    client="-",
    market="-",
    month="-",
    year="-",
):
    return {
        "original_file": original_file,
        "new_filename": new_filename,
        "destination": destination,
        "supplier": supplier,
        "client": client,
        "market": market,
        "month": month,
        "year": year,
        "status": status,
    }


def write_report(rows):
    with open(REPORT_PATH, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def init_stats():
    return {
        "scanned": 0,
        "copied": 0,
        "skipped": 0,
        "unknown": 0,
        "errors": 0,
        "suppliers": {
            "meta": {"pdfs": 0, "copied": 0, "skipped": 0},
            "google": {"pdfs": 0, "copied": 0, "skipped": 0},
            "apple": {"pdfs": 0, "copied": 0, "skipped": 0},
            "adsjoy": {"pdfs": 0, "copied": 0, "skipped": 0},
        },
    }


def print_sort_summary(stats, elapsed):
    print()
    print(SUB_SEP)
    print("SORTING SUMMARY")
    print(SUB_SEP)
    print(f"PDFs scanned          : {stats['scanned']}")
    print(f"Files copied          : {stats['copied']}")
    print(f"Files skipped         : {stats['skipped']}")
    print(f"Unknown supplier      : {stats['unknown']}")
    print(f"Extraction/copy errors: {stats['errors']}")
    print()

    for supplier in SUPPLIER_ORDER:
        row = stats["suppliers"][supplier]
        print(
            f"{SUPPLIER_NAMES[supplier]:<20}: "
            f"PDFs {row['pdfs']:<3} | "
            f"Copied {row['copied']:<3} | "
            f"Skipped {row['skipped']}"
        )

    print()
    print(f"Audit report          : {REPORT_PATH}")
    print(f"Duration              : {duration_str(elapsed)}")
    print(f"Result                : {'SUCCESS' if stats['errors'] == 0 else 'COMPLETED WITH WARNINGS'}")
    print(SUB_SEP)


def main():
    start = perf_counter()

    print_header()

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    invoices = scan_invoices(INVOICE_FOLDER)

    stats = init_stats()
    stats["scanned"] = len(invoices)

    print()
    log("SCAN", f"Found {len(invoices)} PDF invoice(s)")
    print()

    report_rows = []

    for pdf_path, supplier, text in invoices:
        filename = os.path.basename(pdf_path)
        print(f"[PDF] {filename} -> [{supplier.upper()}]")

        if supplier == "unknown":
            stats["skipped"] += 1
            stats["unknown"] += 1

            log("WARN", "Could not detect supplier — skipped", indent=2)

            report_rows.append(make_report_row(
                original_file=filename,
                supplier="UNKNOWN",
                status="SKIPPED - unknown supplier",
            ))
            continue

        stats["suppliers"][supplier]["pdfs"] += 1

        info = extract_info(text, pdf_path, supplier)

        if not info:
            stats["skipped"] += 1
            stats["errors"] += 1
            stats["suppliers"][supplier]["skipped"] += 1

            log("ERR", "Extraction failed — skipped", indent=2)

            report_rows.append(make_report_row(
                original_file=filename,
                supplier=SUPPLIER_NAMES.get(supplier, supplier),
                status="SKIPPED - extraction error",
            ))
            continue

        new_filename, dest_dir = build_destination(info)
        dest_path = os.path.join(dest_dir, new_filename)

        try:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(pdf_path, dest_path)

            stats["copied"] += 1
            stats["suppliers"][supplier]["copied"] += 1

            log("OK", f"{info['client']} | {info['market']} | {info['month']} {info['year']}", indent=2)
            log("COPY", dest_path, indent=2)

            report_rows.append(make_report_row(
                original_file=filename,
                new_filename=new_filename,
                destination=dest_path,
                supplier=info["supplier"],
                client=info["client"],
                market=info["market"],
                month=info["month"],
                year=info["year"],
                status="OK - copied",
            ))

        except Exception as e:
            stats["skipped"] += 1
            stats["errors"] += 1
            stats["suppliers"][supplier]["skipped"] += 1

            log("ERR", f"Copy failed: {e}", indent=2)

            report_rows.append(make_report_row(
                original_file=filename,
                new_filename=new_filename,
                destination=dest_path,
                supplier=info.get("supplier", SUPPLIER_NAMES.get(supplier, supplier)),
                client=info.get("client", "-"),
                market=info.get("market", "-"),
                month=info.get("month", "-"),
                year=info.get("year", "-"),
                status=f"SKIPPED - copy error: {e}",
            ))

    write_report(report_rows)

    elapsed = perf_counter() - start

    print()
    log("DONE", "Sorting complete")
    print_sort_summary(stats, elapsed)
    print(SEP)


if __name__ == "__main__":
    main()