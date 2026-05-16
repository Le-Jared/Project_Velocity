import re
from datetime import datetime
import pandas as pd


MONTH_LOOKUP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def clean_money(value):
    if pd.isna(value):
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value)
    text = text.replace("$", "")
    text = text.replace("¥", "")
    text = text.replace("SGD", "")
    text = text.replace("USD", "")
    text = text.replace(",", "")
    text = text.strip()

    if text in ["", "-", "nan", "None"]:
        return 0.0

    try:
        return float(text)
    except ValueError:
        return 0.0


def clean_number(value):
    if pd.isna(value):
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value)
    text = text.replace(",", "")
    text = text.replace("%", "")
    text = text.strip()

    if text in ["", "-", "nan", "None"]:
        return 0.0

    try:
        return float(text)
    except ValueError:
        return 0.0


def normalize_partner(channel):
    if pd.isna(channel):
        return ""

    raw = str(channel).strip()
    text = raw.lower()

    normalized = (
        text.replace("_", " ")
        .replace("-", " ")
        .replace("/", " ")
        .replace("|", " ")
        .replace("(", " ")
        .replace(")", " ")
    )

    normalized = re.sub(r"\s+", " ", normalized).strip()

    if any(keyword in normalized for keyword in ["facebook", " fb ", "meta"]):
        return "Meta"

    if any(keyword in normalized for keyword in ["tiktok", "tik tok"]):
        return "TikTok"

    if any(keyword in normalized for keyword in ["apple search", " asa ", " iad "]):
        return "Apple Search"

    if "google" in normalized:
        if any(keyword in normalized for keyword in ["sem", "search", "keyword", "kw", "enkw"]):
            return "Google Search"

        if any(keyword in normalized for keyword in ["pmax", "performance max", "performance_max"]):
            return "Google PMAX"

        if any(keyword in normalized for keyword in ["youtube", "yt", "video"]):
            return "Google Youtube"

        if any(keyword in normalized for keyword in ["demand gen", "demandgen", "discovery"]):
            return "Google Demand Gen"

        if any(keyword in normalized for keyword in ["display", "gdn", "banner"]):
            return "Google Display"

        if any(keyword in normalized for keyword in ["uac", "app campaign", "app install"]):
            return "Google"

        return "Google"

    if normalized in ["facebook", "fb", "meta"]:
        return "Meta"

    if normalized in ["tiktok", "tik tok"]:
        return "TikTok"

    if normalized in [
        "uac",
        "google uac",
        "google",
        "google search",
        "pmax",
        "google pmax",
        "google pmax",
        "demand gen",
        "google demand gen",
        "youtube",
        "google youtube",
        "google display",
    ]:
        return "Google"

    return raw.title()



def get_first_existing(row, possible_columns, default=None):
    for col in possible_columns:
        if col in row.index:
            value = row.get(col)
            if not pd.isna(value) and str(value).strip() != "":
                return value

    return default


def parse_flexible_date(value, default_year=2026):
    if pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value

    if isinstance(value, datetime):
        return pd.Timestamp(value)

    parsed = pd.to_datetime(value, errors="coerce")

    if not pd.isna(parsed):
        return parsed

    text = str(value).strip()
    match = re.match(r"^(\d{1,2})\s+([A-Za-z]+)$", text)

    if match:
        day = int(match.group(1))
        month_text = match.group(2).lower()
        month = MONTH_LOOKUP.get(month_text)

        if month:
            return pd.Timestamp(year=default_year, month=month, day=day)

    return None


def adapt_gu_plan(raw_df, client="GU", default_year=2026):
    records = []

    for _, row in raw_df.iterrows():
        channel = get_first_existing(row, ["Channel"])

        if channel is None or str(channel).strip() == "":
            continue

        partner = normalize_partner(channel)

        start_raw = get_first_existing(
            row,
            [
                "Campaign Start",
                "Campaign  Start",
                "Campaign Start Date",
                "Start Date",
                "Campaign  Start",
            ],
        )

        end_raw = get_first_existing(
            row,
            [
                "Campaign End",
                "Campaign  End",
                "Campaign End Date",
                "End Date",
                "Campaign  End",
            ],
        )

        net_media = clean_money(
            get_first_existing(
                row,
                [
                    "Net Media (Budget excluding fees)",
                    "Net Media",
                    "Media Budget",
                    "Budget",
                ],
                0,
            )
        )

        gross_media = clean_money(
            get_first_existing(
                row,
                [
                    "Gross Media (Budget with Fee)",
                    "Gross Media",
                    "Gross media budget",
                    "Gross media budget (SGD)",
                    "Total Budget",
                ],
                0,
            )
        )

        if gross_media <= 0:
            gross_media = net_media

        kpi = str(get_first_existing(row, ["KPI", "Buy Type", "Buy type"], "CPM"))
        kpi = kpi.strip().upper()

        record = {
            "client": client,
            "channel": str(channel).strip(),
            "partner": partner,
            "campaign_name": get_first_existing(row, ["Campaign Name"], ""),
            "targeting": get_first_existing(row, ["Targeting"], ""),
            "kpi": kpi,
            "buy_type": kpi,
            "start_date": parse_flexible_date(start_raw, default_year=default_year),
            "end_date": parse_flexible_date(end_raw, default_year=default_year),
            "net_media": net_media,
            "gross_media": gross_media,
            "impressions": clean_number(
                get_first_existing(
                    row,
                    [
                        "Estimated Impression",
                        "Estimated Impressions",
                        "Impressions",
                        "Estimated impressions",
                    ],
                    0,
                )
            ),
            "clicks": clean_number(
                get_first_existing(
                    row,
                    [
                        "Click",
                        "Clicks",
                        "Estimated Clicks",
                        "Estimated clicks",
                    ],
                    0,
                )
            ),
            "installs": clean_number(
                get_first_existing(
                    row,
                    [
                        "Install",
                        "Installs",
                        "Estimated Installs",
                        "Estimated installs",
                    ],
                    0,
                )
            ),
            "cpm": clean_money(
                get_first_existing(
                    row,
                    [
                        "Estimated CPM (USD)",
                        "CPM",
                        "Estimated CPM",
                    ],
                    0,
                )
            ),
            "cpc": clean_money(
                get_first_existing(
                    row,
                    [
                        "Estimated CPC (USD)",
                        "CPC",
                        "Estimated CPC",
                    ],
                    0,
                )
            ),
            "cpi": clean_money(
                get_first_existing(
                    row,
                    [
                        "Estimated Cost Per Installs",
                        "Target CPI",
                        "CPI",
                    ],
                    0,
                )
            ),
            "currency": "USD",
        }

        channel_text = str(record["channel"]).lower()

        if "total" in channel_text:
            continue

        records.append(record)

    if not records:
        raise ValueError("No valid GU placement rows found after adaptation.")

    return pd.DataFrame(records)


def adapt_generic_plan(raw_df, client="UNKNOWN", default_year=2026):
    records = []

    for _, row in raw_df.iterrows():
        channel = get_first_existing(
            row,
            [
                "Channel",
                "Media Channel",
                "Product",
                "Partner",
                "Supplier",
                "Platform",
                "Publisher",
                "Vendor",
                "Site",
                "Site Name",
                "Network",
            ],
        )

        campaign_name = get_first_existing(
            row,
            [
                "Campaign Name",
                "Campaign",
                "Placement Name",
                "Placement",
                "Line Item",
                "Line item",
                "Ad Group",
                "Ad Set",
            ],
            "",
        )

        if channel is None or str(channel).strip() == "":
            channel = campaign_name

        if channel is None or str(channel).strip() == "":
            continue

        partner = normalize_partner(channel)

        start_raw = get_first_existing(
            row,
            [
                "Start Date",
                "Campaign Start",
                "Campaign  Start",
                "Flight Start",
                "Flight Start Date",
                "Campaign Start Date",
                "Start",
                "Live Date",
            ],
        )

        end_raw = get_first_existing(
            row,
            [
                "End Date",
                "Campaign End",
                "Campaign  End",
                "Flight End",
                "Flight End Date",
                "Campaign End Date",
                "End",
                "End date",
            ],
        )

        gross_media = clean_money(
            get_first_existing(
                row,
                [
                    "Gross Media (Budget with Fee)",
                    "Gross media budget (SGD)",
                    "Gross media budget",
                    "Gross Media",
                    "Budget (USD)",
                    "Budget",
                    "Media Budget",
                    "Net Media",
                    "Net Media (Budget excluding fees)",
                    "Cost",
                    "Amount",
                    "Spend",
                    "Planned Cost",
                    "Gross/Planned Cost",
                ],
                0,
            )
        )

        net_media = clean_money(
            get_first_existing(
                row,
                [
                    "Net Media",
                    "Net Media (Budget excluding fees)",
                    "Budget",
                    "Media Budget",
                    "Cost",
                    "Amount",
                    "Spend",
                ],
                gross_media,
            )
        )

        impressions = clean_number(
            get_first_existing(
                row,
                [
                    "Estimated Impressions",
                    "Estimated Impression",
                    "Impressions",
                    "Impression",
                    "Planned Impressions",
                    "Planned unit amount",
                    "Units",
                ],
                0,
            )
        )

        kpi = str(
            get_first_existing(
                row,
                [
                    "KPI",
                    "Buy Type",
                    "Buy type",
                    "Cost Method",
                    "Cost method",
                    "Optimization",
                    "Objective",
                ],
                "CPM",
            )
        ).upper().strip()

        record = {
            "client": str(client).upper().strip(),
            "channel": str(channel).strip(),
            "partner": partner,
            "campaign_name": campaign_name,
            "targeting": get_first_existing(row, ["Targeting", "Audience", "Target Audience"], ""),
            "kpi": kpi,
            "buy_type": kpi,
            "start_date": parse_flexible_date(start_raw, default_year=default_year),
            "end_date": parse_flexible_date(end_raw, default_year=default_year),
            "net_media": net_media,
            "gross_media": gross_media if gross_media > 0 else net_media,
            "impressions": impressions,
            "clicks": clean_number(get_first_existing(row, ["Clicks", "Estimated Clicks", "Planned Clicks"], 0)),
            "installs": clean_number(get_first_existing(row, ["Installs", "Estimated Installs", "Planned Installs"], 0)),
            "cpm": clean_money(get_first_existing(row, ["CPM", "Estimated CPM", "Unit Rate", "Rate"], 0)),
            "cpc": clean_money(get_first_existing(row, ["CPC", "Estimated CPC"], 0)),
            "cpi": clean_money(get_first_existing(row, ["CPI", "Target CPI"], 0)),
            "currency": "",
        }

        channel_text = str(record["channel"]).lower()

        if "total" in channel_text or "subtotal" in channel_text:
            continue

        if record["gross_media"] <= 0 and record["impressions"] <= 0:
            continue

        records.append(record)

    if not records:
        raise ValueError(
            "No valid placement rows found after generic adaptation. "
            f"Columns found: {list(raw_df.columns)}"
        )

    return pd.DataFrame(records)


def consolidate_for_prisma(normalized_df):
    if normalized_df.empty:
        raise ValueError("Cannot consolidate an empty media plan dataframe.")

    required_cols = ["client", "partner", "gross_media", "impressions"]

    for col in required_cols:
        if col not in normalized_df.columns:
            raise ValueError(f"Missing required column for consolidation: {col}")

    placements = []

    grouped = normalized_df.groupby(["client", "partner"], dropna=False)

    for (client, partner), group in grouped:
        planned_amount = float(group["gross_media"].sum())
        planned_units = float(group["impressions"].sum())

        if planned_units <= 0:
            derived_impressions = []

            for _, row in group.iterrows():
                cost = float(row.get("gross_media", 0))
                cpm = float(row.get("cpm", 0))

                if cost > 0 and cpm > 0:
                    derived_impressions.append(cost / cpm * 1000)

            planned_units = sum(derived_impressions)

        if planned_units > 0:
            unit_rate = planned_amount / planned_units * 1000
        else:
            unit_rate = 0.0

        start_dates = group["start_date"].dropna()
        end_dates = group["end_date"].dropna()

        flight_start = start_dates.min() if not start_dates.empty else None
        flight_end = end_dates.max() if not end_dates.empty else None

        placement_name = f"{client} - {partner} - CPM"

        placements.append(
            {
                "client": client,
                "partner": partner,
                "placement_name": placement_name,
                "cost_method": "CPM",
                "unit_type": "Impressions",
                "unit_rate": round(unit_rate, 2),
                "planned_units": int(round(planned_units, 0)),
                "planned_amount": round(planned_amount, 2),
                "flight_start": flight_start,
                "flight_end": flight_end,
                "source_rows": len(group),
            }
        )

    return pd.DataFrame(placements)


def adapt_media_plan(raw_df, client="GU", default_year=2026):
    client_upper = str(client).upper().strip()

    if client_upper == "GU":
        return adapt_gu_plan(raw_df, client=client_upper, default_year=default_year)

    return adapt_generic_plan(raw_df, client=client_upper, default_year=default_year)
