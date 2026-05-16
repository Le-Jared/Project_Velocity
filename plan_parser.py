# plan_parser.py

from pathlib import Path
import re
import pandas as pd


HEADER_KEYWORDS = [
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
]


ANCHOR_KEYWORDS = [
    "channel",
    "partner",
    "supplier",
    "platform",
    "publisher",
    "campaign",
    "campaign name",
    "placement",
    "placement name",
]


METRIC_KEYWORDS = [
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
]


def _clean_column_name(value):
    """
    Normalize Excel column headers.

    Handles:
    - 'Campaign \\nStart'
    - ' Campaign Start '
    - NaN headers
    - repeated whitespace
    """
    if pd.isna(value):
        return ""

    text = str(value).replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)

    return text


def _normalize_header_text(value):
    return _clean_column_name(value).lower()


def _row_values(row):
    return [
        _normalize_header_text(value)
        for value in row.tolist()
        if not pd.isna(value) and _clean_column_name(value) != ""
    ]


def _row_text(row):
    return " | ".join(_row_values(row))


def _row_contains_terms(row, required_terms):
    row_text = _row_text(row)
    return all(term.lower() in row_text for term in required_terms)


def _score_header_row(row):
    """
    Score a row based on how likely it is to be a media placement header row.

    A valid media table usually has:
    - at least one anchor column like Channel/Partner/Supplier/Campaign/Placement
    - at least one metric/date/budget column
    """
    values = _row_values(row)

    if not values:
        return 0

    joined = " | ".join(values)

    score = 0

    for keyword in HEADER_KEYWORDS:
        if keyword in joined:
            score += 1

    has_anchor = any(keyword in joined for keyword in ANCHOR_KEYWORDS)
    has_metric = any(keyword in joined for keyword in METRIC_KEYWORDS)

    if has_anchor:
        score += 5

    if has_metric:
        score += 5

    # Prefer rows with several non-empty cells.
    if len(values) >= 4:
        score += 2

    if len(values) >= 6:
        score += 2

    return score


def find_header_row(raw_df, required_terms=None):
    """
    Finds the likely placement table header row.

    If required_terms are provided, first try strict matching.
    If strict matching fails, fall back to scored header detection.
    """
    if required_terms:
        for idx, row in raw_df.iterrows():
            if _row_contains_terms(row, required_terms):
                return idx

    best_idx = None
    best_score = 0

    for idx, row in raw_df.iterrows():
        score = _score_header_row(row)

        if score > best_score:
            best_idx = idx
            best_score = score

    # Threshold avoids picking random title rows.
    if best_score >= 10:
        return best_idx

    return None


def _dedupe_headers(headers):
    """
    Deduplicate repeated Excel headers.

    Example:
    ['Channel', 'Budget', 'Budget'] -> ['Channel', 'Budget', 'Budget__2']
    """
    seen = {}
    result = []

    for header in headers:
        clean = _clean_column_name(header)

        if clean == "":
            result.append("")
            continue

        count = seen.get(clean, 0) + 1
        seen[clean] = count

        if count == 1:
            result.append(clean)
        else:
            result.append(f"{clean}__{count}")

    return result


def _looks_like_repeated_header(row):
    values = [_normalize_header_text(value) for value in row.tolist()]
    joined = " | ".join(values)

    hits = sum(1 for keyword in ANCHOR_KEYWORDS if keyword in joined)

    return hits >= 2


def parse_media_plan(file_path, required_terms=None):
    """
    Parse an Excel media plan into a raw dataframe of placement rows.

    This supports GU-style plans and more generic MI/MCP-like layouts by
    using flexible header-row detection.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Media plan not found: {file_path}")

    sheets = pd.read_excel(
        file_path,
        sheet_name=None,
        header=None,
        engine="openpyxl"
    )

    parsed_tables = []

    debug_scores = []

    for sheet_name, raw_df in sheets.items():
        header_idx = find_header_row(raw_df, required_terms=required_terms)

        if header_idx is None:
          continue

        raw_headers = raw_df.iloc[header_idx].tolist()
        headers = _dedupe_headers(raw_headers)

        data = raw_df.iloc[header_idx + 1:].copy()
        data.columns = headers

        # Remove empty columns.
        data = data.loc[:, [col for col in data.columns if col != ""]]

        # Remove fully empty rows.
        data = data.dropna(how="all")

        # Remove repeated header rows.
        data = data[
            ~data.apply(_looks_like_repeated_header, axis=1)
        ]

        # Remove rows that are likely totals/subtotals.
        first_text_col = None

        for candidate in ["Channel", "Partner", "Supplier", "Platform", "Publisher", "Campaign Name", "Campaign"]:
            if candidate in data.columns:
                first_text_col = candidate
                break

        if first_text_col:
            data = data[
                ~data[first_text_col]
                .astype(str)
                .str.lower()
                .str.contains("total|subtotal|grand total", na=False)
            ]

        data["source_sheet"] = sheet_name
        data["source_file"] = file_path.name

        if not data.empty:
            parsed_tables.append(data)

    if not parsed_tables:
        raise ValueError(
            "No media placement table found. "
            "Could not locate a header row containing channel/partner/campaign/placement plus budget/date metrics."
        )

    result = pd.concat(parsed_tables, ignore_index=True)

    return result


def detect_client(file_path):
    """
    Lightweight client detection for UI display and AUTO conversion.

    Uses filename token matching to avoid false matches like:
    - 'campaign' accidentally matching 'mi'
    - 'media' accidentally matching 'mi'
    """
    name = Path(file_path).stem.lower()

    normalized = (
        name.replace("_", " ")
            .replace("-", " ")
            .replace(".", " ")
    )

    tokens = normalized.split()

    if "skillignition" in name or ("skill" in tokens and "ignition" in tokens):
        return "GU"

    if "gu" in tokens:
        return "GU"

    if "mi" in tokens:
        return "MI"

    if "mcp" in tokens:
        return "MCP"

    if "2026" in tokens and "media" in tokens and "plan" in tokens:
        return "MCP"

    return None

