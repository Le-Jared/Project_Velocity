# buying_guide.py

from pathlib import Path
import pandas as pd


PARTNER_KEYWORDS = {
    "Meta": ["Facebook", "Meta"],
    "Facebook": ["Facebook", "Meta"],
    "TikTok": ["TikTok", "Tiktok", "Tik Tok"],
    "Tiktok": ["TikTok", "Tiktok", "Tik Tok"],
    "Google": ["Google", "UAC", "PMAX", "Search", "Demand Gen", "Youtube"],
    "UAC": ["Google", "UAC"],
    "Apple Search": ["Apple Search", "ASA", "IAD"],
}


REQUIRED_GUIDE_COLUMNS = [
    "Buy type",
    "Financial buy type",
    "Buy category",
    "Currency",
    "Supplier code",
    "Supplier name",
    "Positioning",
    "Ad size",
    "Cost method",
    "Unit type",
    "Placement booking type",
    "Clients that uses these respectively",
]


def _clean_columns(df):
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]
    return df


def load_buying_guide(path, sheet_name="Buying guide 2"):
    """
    Load the client Buying Guide.

    Args:
        path:
            Path to ACCT 108 BuyingGuide.xlsx.

        sheet_name:
            Usually 'Buying guide 2'.

    Returns:
        pandas.DataFrame with cleaned column names.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Buying Guide not found: {path}")

    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    df = _clean_columns(df)

    missing_cols = [
        col for col in REQUIRED_GUIDE_COLUMNS
        if col not in df.columns
    ]

    if missing_cols:
        raise ValueError(
            "Buying Guide is missing required columns: "
            + ", ".join(missing_cols)
        )

    # Remove empty guide rows.
    df = df.dropna(how="all")

    return df


def _normalize_text(value):
    if pd.isna(value):
        return ""

    return str(value).strip()


def _client_matches(value, client):
    """
    Matches the client column.

    The guide may contain exact client values like:
    - GU
    - MCP
    - MI
    - NA
    """
    value_text = _normalize_text(value).upper()
    client_text = _normalize_text(client).upper()

    return value_text == client_text


def _booking_type_contains_partner(booking_type, partner):
    """
    Checks whether the Buying Guide placement booking type matches a partner.
    """
    booking_text = _normalize_text(booking_type).lower()

    partner_keywords = PARTNER_KEYWORDS.get(partner, [partner])

    for keyword in partner_keywords:
        if str(keyword).lower() in booking_text:
            return True

    return False


def match_buying_guide_row(guide_df, client, partner):
    """
    Match a consolidated placement to the correct Buying Guide row.

    Primary match:
    - Clients that uses these respectively == client
    - Placement booking type contains partner keyword

    Returns:
        A dict representing the matched Buying Guide row.

    Raises:
        ValueError if no match is found.
    """
    client_col = "Clients that uses these respectively"
    booking_col = "Placement booking type"

    client_filtered = guide_df[
        guide_df[client_col].apply(lambda value: _client_matches(value, client))
    ].copy()

    if client_filtered.empty:
        raise ValueError(f"No Buying Guide rows found for client: {client}")

    matches = client_filtered[
        client_filtered[booking_col].apply(
            lambda value: _booking_type_contains_partner(value, partner)
        )
    ]

    if matches.empty:
        available = client_filtered[booking_col].dropna().astype(str).unique().tolist()

        raise ValueError(
            f"No Buying Guide match found for client='{client}', partner='{partner}'. "
            f"Available booking types for this client: {available}"
        )

    # Prefer CPM rows if multiple rows match.
    cpm_matches = matches[
        matches["Cost method"].astype(str).str.upper().str.strip() == "CPM"
    ]

    if not cpm_matches.empty:
        return cpm_matches.iloc[0].to_dict()

    return matches.iloc[0].to_dict()


def enrich_with_buying_guide(consolidated_df, guide_df):
    """
    Add Buying Guide fields to consolidated Prisma placement rows.

    Args:
        consolidated_df:
            Output from consolidate_for_prisma().

        guide_df:
            Output from load_buying_guide().

    Returns:
        pandas.DataFrame with supplier and Prisma mapping fields added.
    """
    if consolidated_df.empty:
        raise ValueError("Cannot enrich an empty consolidated dataframe.")

    enriched_rows = []

    for _, row in consolidated_df.iterrows():
        client = row.get("client")
        partner = row.get("partner")

        guide_row = match_buying_guide_row(
            guide_df=guide_df,
            client=client,
            partner=partner,
        )

        enriched = row.to_dict()

        enriched.update(
            {
                "buy_type": guide_row.get("Buy type"),
                "financial_buy_type": guide_row.get("Financial buy type"),
                "buy_category": guide_row.get("Buy category"),
                "currency": guide_row.get("Currency"),
                "supplier_code": guide_row.get("Supplier code"),
                "supplier_name": guide_row.get("Supplier name"),
                "positioning": guide_row.get("Positioning"),
                "ad_size": guide_row.get("Ad size"),
                "guide_cost_method": guide_row.get("Cost method"),
                "guide_unit_type": guide_row.get("Unit type"),
                "placement_booking_type": guide_row.get("Placement booking type"),
            }
        )

        enriched_rows.append(enriched)

    return pd.DataFrame(enriched_rows)


def preview_buying_guide_matches(consolidated_df, guide_df):
    """
    Helper for debugging or UI preview.

    Returns a dataframe showing placement-to-guide matches.
    """
    preview_rows = []

    for _, row in consolidated_df.iterrows():
        client = row.get("client")
        partner = row.get("partner")

        try:
            guide_row = match_buying_guide_row(guide_df, client, partner)
            status = "Matched"
            supplier_name = guide_row.get("Supplier name")
            supplier_code = guide_row.get("Supplier code")
            booking_type = guide_row.get("Placement booking type")
        except Exception as exc:
            status = f"Error: {exc}"
            supplier_name = ""
            supplier_code = ""
            booking_type = ""

        preview_rows.append(
            {
                "client": client,
                "partner": partner,
                "placement_name": row.get("placement_name"),
                "status": status,
                "supplier_name": supplier_name,
                "supplier_code": supplier_code,
                "placement_booking_type": booking_type,
            }
        )

    return pd.DataFrame(preview_rows)

class BuyingGuide:
    """
    Lightweight compatibility wrapper for Flask status/upload routes.

    Allows app.py to call:
    - len(bg)
    - bg.clients()
    """

    def __init__(self, path, sheet_name="Buying guide 2"):
        self.path = path
        self.df = load_buying_guide(path, sheet_name=sheet_name)

    def __len__(self):
        return len(self.df)

    def clients(self):
        col = "Clients that uses these respectively"

        if col not in self.df.columns:
            return []

        clients = (
            self.df[col]
            .dropna()
            .astype(str)
            .str.strip()
        )

        clients = [
            c for c in clients.unique().tolist()
            if c and c.lower() not in ["nan", "none"]
        ]

        return sorted(clients)

