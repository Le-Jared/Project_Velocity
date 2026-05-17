from pathlib import Path
import re
import pandas as pd


HEADER_KEYWORDS = {
    "channel",
    "partner",
    "supplier",
    "platform",
    "publisher",
    "campaign",
    "campaign name",
    "placement",
    "placement name",
    "start",
    "start date",
    "campaign start",
    "flight start",
    "end",
    "end date",
    "campaign end",
    "flight end",
    "budget",
    "media budget",
    "gross media",
    "net media",
    "impression",
    "impressions",
    "click",
    "clicks",
    "kpi",
    "buy type",
}

ANCHOR_KEYWORDS = {
    "channel",
    "partner",
    "supplier",
    "platform",
    "publisher",
    "campaign",
    "campaign name",
    "placement",
    "placement name",
}

METRIC_KEYWORDS = {
    "budget",
    "gross media",
    "net media",
    "media budget",
    "impression",
    "impressions",
    "click",
    "clicks",
    "start date",
    "end date",
    "flight start",
    "flight end",
    "campaign start",
    "campaign end",
}

BUDGET_KEYWORDS = {
    "budget",
    "media budget",
    "gross media",
    "net media",
    "planned cost",
    "cost",
    "spend",
}

DATE_KEYWORDS = {
    "start",
    "start date",
    "campaign start",
    "flight start",
    "end",
    "end date",
    "campaign end",
    "flight end",
}

PERFORMANCE_NOISE_KEYWORDS = {
    "search impr",
    "search lost",
    "conv rate",
    "conversion rate",
    "quality score",
    "ctr",
    "avg cpc",
    "campaign status",
    "ad group status",
}

TEXT_COLUMNS = [
    "Channel",
    "Partner",
    "Supplier",
    "Platform",
    "Publisher",
    "Campaign Name",
    "Campaign",
    "Placement Name",
    "Placement",
]

CLIENT_RULES = [
    ("GU", lambda name, tokens: "skillignition" in name or ("skill" in tokens and "ignition" in tokens) or "gu" in tokens),
    ("MI", lambda name, tokens: "mi" in tokens),
    ("MCP", lambda name, tokens: "mcp" in tokens or {"2026", "media", "plan"}.issubset(tokens)),
]


def clean_text(value):
    if pd.isna(value):
        return ""

    return re.sub(r"\s+", " ", str(value).replace("\n", " ").strip())


def normalize_text(value):
    return clean_text(value).lower()


def row_values(row):
    return [normalize_text(value) for value in row.tolist() if clean_text(value)]


def row_text(row):
    return " | ".join(row_values(row))


def contains_all(row, terms):
    text = row_text(row)
    return all(str(term).lower() in text for term in terms)


def score_header_row(row):
    values = row_values(row)

    if not values:
        return 0

    text = " | ".join(values)
    score = sum(1 for keyword in HEADER_KEYWORDS if keyword in text)

    has_anchor = any(keyword in text for keyword in ANCHOR_KEYWORDS)
    has_metric = any(keyword in text for keyword in METRIC_KEYWORDS)
    has_budget = any(keyword in text for keyword in BUDGET_KEYWORDS)
    has_date = any(keyword in text for keyword in DATE_KEYWORDS)

    score += 6 if has_anchor else 0
    score += 5 if has_metric else 0
    score += 4 if has_budget else 0
    score += 3 if has_date else 0
    score += 2 if len(values) >= 4 else 0
    score += 2 if len(values) >= 6 else 0
    score -= sum(2 for keyword in PERFORMANCE_NOISE_KEYWORDS if keyword in text)

    return score


def find_header_row(raw_df, required_terms=None):
    if required_terms:
        for idx, row in raw_df.iterrows():
            if contains_all(row, required_terms):
                return idx

    scored = [(idx, score_header_row(row)) for idx, row in raw_df.iterrows()]
    best_idx, best_score = max(scored, key=lambda item: item[1], default=(None, 0))

    return best_idx if best_score >= 12 else None


def dedupe_headers(headers):
    seen = {}
    result = []

    for header in headers:
        clean = clean_text(header)

        if not clean:
            result.append("")
            continue

        seen[clean] = seen.get(clean, 0) + 1
        result.append(clean if seen[clean] == 1 else f"{clean}__{seen[clean]}")

    return result


def looks_like_repeated_header(row):
    text = row_text(row)
    return sum(1 for keyword in ANCHOR_KEYWORDS if keyword in text) >= 2


def remove_total_rows(data):
    text_col = next((col for col in TEXT_COLUMNS if col in data.columns), None)

    if not text_col:
        return data

    mask = data[text_col].astype(str).str.lower().str.contains("total|subtotal|grand total", na=False)

    return data[~mask]


def parse_sheet(raw_df, sheet_name, file_name, required_terms=None):
    header_idx = find_header_row(raw_df, required_terms=required_terms)

    if header_idx is None:
        return None

    data = raw_df.iloc[header_idx + 1:].copy()
    data.columns = dedupe_headers(raw_df.iloc[header_idx].tolist())
    data = data.loc[:, [col for col in data.columns if col]]
    data = data.dropna(how="all")

    if data.empty:
        return None

    data = data[~data.apply(looks_like_repeated_header, axis=1)]
    data = remove_total_rows(data)

    if data.empty:
        return None

    data["source_sheet"] = sheet_name
    data["source_file"] = file_name

    return data


def parse_media_plan(file_path, required_terms=None):
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Media plan not found: {file_path}")

    sheets = pd.read_excel(file_path, sheet_name=None, header=None, engine="openpyxl")

    tables = [
        table
        for sheet_name, raw_df in sheets.items()
        for table in [parse_sheet(raw_df, sheet_name, file_path.name, required_terms)]
        if table is not None and not table.empty
    ]

    if not tables:
        raise ValueError(
            "No media placement table found. "
            "Could not locate a header row containing channel/partner/campaign/placement plus budget/date metrics."
        )

    return pd.concat(tables, ignore_index=True)


def detect_client(file_path):
    name = Path(file_path).stem.lower()
    normalized = re.sub(r"[_\-.]+", " ", name)
    tokens = set(normalized.split())

    for client, rule in CLIENT_RULES:
        if rule(name, tokens):
            return client

    return None
