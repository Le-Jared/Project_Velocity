import re
from datetime import datetime
import pandas as pd


MONTH_LOOKUP = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}


CHANNEL_COLUMNS = [
    "Channel", "Media Channel", "Product", "Partner", "Supplier", "Platform",
    "Publisher", "Vendor", "Site", "Site Name", "Network", "Media", "Source",
    "Publisher Product/ Site", "Advertising Channel",
]


CAMPAIGN_COLUMNS = [
    "Campaign Name", "Campaign", "Campaign name", "Placement Name", "Placement",
    "Placement name", "Line Item", "Line item", "Line Item Name", "Ad Group",
    "Ad Set", "Adset", "Package", "Package Name", "Campaign/Placement",
    "Campaign Placement", "Campaign Description",
]


START_DATE_COLUMNS = [
    "Start Date", "Start date", "Campaign Start", "Campaign  Start",
    "Campaign Start Date", "Flight Start", "Flight start", "Flight Start Date",
    "Start", "Live Date", "Launch Date", "From", "Date From", "Period Start",
    "Planned Start", "Media Start", "Media Start Date", "Activity Start",
    "Activity Start Date", "Start Time", "Start date/time", "Start Date/Time",
    "Campaign start date", "Placement Start", "Placement Start Date", "開始日",
]


END_DATE_COLUMNS = [
    "End Date", "End date", "Campaign End", "Campaign  End", "Campaign End Date",
    "Flight End", "Flight end", "Flight End Date", "End", "To", "Date To",
    "Period End", "Planned End", "Media End", "Media End Date", "Activity End",
    "Activity End Date", "End Time", "End date/time", "End Date/Time",
    "Campaign end date", "Placement End", "Placement End Date", "終了日",
]


DATE_RANGE_COLUMNS = [
    "Flight", "Flight Dates", "Flight dates", "Date Range", "Date range",
    "Period", "Campaign Period", "Duration", "Dates", "Date", "Timing",
    "Flighting", "Campaign Dates", "Campaign dates",
]


GROSS_MEDIA_COLUMNS = [
    "Gross Media (Budget with Fee)", "Gross media budget (SGD)",
    "Gross media budget", "Gross Media", "Gross", "Gross Cost", "Gross Spend",
    "Gross/Planned Cost", "Budget (USD)", "Budget", "Monthly Budget (USD)",
    "Media Budget", "Media Cost", "Total Media Cost", "Total Cost",
    "Planned Cost", "Cost", "Cost (Spend)", "Amount", "Spend", "Investment",
    "Net Media", "Net Media (Budget excluding fees)", "Estimated Cost",
    "Estimated Spend", "Planned Spend", "Planned Media Spend", "Total Budget",
    "Total Monthly Budget (USD)", "Budget Amount", "Media Spend", "Ad Spend",
    "Spend Amount", "Cost Amount",
]


NET_MEDIA_COLUMNS = [
    "Net Media", "Net Media (Budget excluding fees)", "Net", "Net Cost",
    "Budget", "Monthly Budget (USD)", "Media Budget", "Media Cost",
    "Total Media Cost", "Cost", "Cost (Spend)", "Amount", "Spend",
    "Investment", "Estimated Cost", "Estimated Spend", "Planned Spend",
    "Planned Media Spend", "Media Spend", "Ad Spend",
]


IMPRESSION_COLUMNS = [
    "Estimated Impressions", "Estimated Impression", "Impressions", "Impression",
    "Planned Impressions", "Planned Impression", "Planned unit amount", "Units",
    "Planned Units", "Delivered Impressions", "Total Impressions",
    "Est. Impressions", "Est Impressions", "Est. Impression",
    "Total Impression", "Booked Impressions", "Forecast Impressions",
]


CLICK_COLUMNS = ["Clicks", "Click", "Estimated Clicks", "Estimated clicks", "Planned Clicks", "Total Clicks"]
INSTALL_COLUMNS = ["Installs", "Install", "Estimated Installs", "Estimated installs", "Planned Installs", "Total Installs"]
CPM_COLUMNS = ["CPM", "Estimated CPM", "Estimated CPM (USD)", "Avg. CPM", "Unit Rate", "Rate", "Cost Per Mille", "Cost per thousand"]
CPC_COLUMNS = ["CPC", "Estimated CPC", "Estimated CPC (USD)", "Avg. CPC", "CPC (USD)"]
CPI_COLUMNS = ["CPI", "Target CPI", "Estimated Cost Per Installs", "CPI (USD)"]


KPI_COLUMNS = [
    "KPI", "Buy Type", "Buy type", "Buy Model", "Cost Method", "Cost method",
    "Optimization", "Objective", "Pricing Model", "Buying Model",
]


TOTAL_ROW_KEYWORDS = {"total", "subtotal", "grand total"}


DATE_RANGE_SEPARATORS = [" - ", " – ", " — ", " to ", " until ", "–", "—"]


BAD_PARTNER_EXACT = {
    "unknown", "none", "n a", "na", "nan", "total", "subtotal", "grand total",
    "multi channel", "publisher product site", "publisher product",
    "advertising channel", "campaign name", "media plan", "media plan us may",
    "media plan hk apr", "s s media plan us may", "s s media plan us may copy",
    "copy of s s media plan us may", "copy of s s media plan hk apr",
}


BAD_PARTNER_CONTAINS = [
    "copy of", "media plan", "s s media plan", "summary", "subtotal", "grand total",
]


NON_MEDIA_PARTNER_EXACT = {
    "agency fee", "agency fees", "agency fee sgd", "agency fee usd", "fee", "fees",
    "commission", "management fee", "platform fee", "adserving fee",
    "ad serving fee", "tracking fee", "production fee",
}


NON_MEDIA_PARTNER_CONTAINS = [
    "agency fee", "agency fees", "management fee", "platform fee", "adserving fee",
    "ad serving fee", "tracking fee", "production fee",
]


PARTNER_RULES = [
    ("Meta", ["facebook", "meta", "fb", "instagram"]),
    ("TikTok", ["tiktok", "tik tok"]),
    ("Apple Search", ["apple search", "apple search ads", "asa", "iad"]),
    ("Reddit", ["reddit"]),
    ("The Trade Desk", ["trade desk", "ttd"]),
    ("Moloco", ["moloco"]),
    ("Jampp", ["jampp"]),
    ("Google PMAX", ["pmax", "performance max", "performancemax"]),
    ("Google Search", ["sem"]),
    ("Google Youtube", ["youtube", "you tube", "yt"]),
    ("Google Demand Gen", ["demand gen", "demandgen", "discovery"]),
    ("Google Display", ["display", "gdn", "banner"]),
    ("Google Search", ["search"]),
    ("Google", ["google", "uac"]),
]


MONTH_PATTERN = (
    "jan|january|feb|february|mar|march|apr|april|may|jun|june|"
    "jul|july|aug|august|sep|sept|september|oct|october|"
    "nov|november|dec|december"
)


CLIENT_DATE_FALLBACKS = {
    "MI": (pd.Timestamp("2026-05-20"), pd.Timestamp("2026-06-30")),
    "MCP": (pd.Timestamp("2026-05-20"), pd.Timestamp("2026-06-30")),
    "GU": (pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-30")),
}


def normalize_text(value):
    if pd.isna(value):
        return ""

    text = str(value).strip().lower()
    text = re.sub(r"[_\-/|()\[\]:,;]+", " ", text)

    return re.sub(r"\s+", " ", text).strip()


def is_blank(value):
    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except Exception:
        pass

    return str(value).strip().lower() in {"", "nan", "none", "n/a", "na", "-"}


def is_numeric_like(value):
    if is_blank(value):
        return False

    try:
        float(str(value).strip().replace(",", ""))
        return True
    except Exception:
        return False


def is_reasonable_date(value):
    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return False

    return 2020 <= parsed.year <= 2035


def is_non_media_partner(value):
    normalized = normalize_text(value)

    if not normalized:
        return True

    return (
        normalized in NON_MEDIA_PARTNER_EXACT
        or any(token in normalized for token in NON_MEDIA_PARTNER_CONTAINS)
    )


def is_bad_partner_value(value):
    if is_blank(value) or is_numeric_like(value):
        return True

    parsed = pd.to_datetime(value, errors="coerce")

    if not pd.isna(parsed):
        return True

    normalized = normalize_text(value)

    return (
        normalized in BAD_PARTNER_EXACT
        or any(token in normalized for token in BAD_PARTNER_CONTAINS)
        or is_non_media_partner(value)
    )


def clean_number(value):
    if pd.isna(value):
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    if text.lower() in {"", "-", "nan", "none", "n/a", "na"}:
        return 0.0

    negative = text.startswith("(") and text.endswith(")")

    if negative:
        text = text[1:-1]

    text = re.sub(r"\b(SGD|USD|HKD|MYR|THB|IDR|JPY)\b", "", text, flags=re.IGNORECASE)
    text = text.replace("$", "").replace("¥", "").replace(",", "").replace("%", "").strip()

    try:
        number = float(text)
    except ValueError:
        return 0.0

    return -number if negative else number


clean_money = clean_number


def normalize_partner(channel):
    if pd.isna(channel):
        return ""

    raw = str(channel).strip()

    if is_bad_partner_value(raw):
        return ""

    normalized = normalize_text(raw)
    padded = f" {normalized} "

    for partner, needles in PARTNER_RULES:
        for needle in needles:
            needle_norm = normalize_text(needle)

            if f" {needle_norm} " in padded or needle_norm in normalized:
                return partner

    return raw.title()


def get_first_existing(row, possible_columns, default=None):
    row_map = {normalize_text(col): col for col in row.index}

    for col in possible_columns:
        key = normalize_text(col)

        if key in row_map:
            value = row.get(row_map[key])

            if not is_blank(value):
                return value

    for col in possible_columns:
        key = normalize_text(col)

        for row_key, real_col in row_map.items():
            if key and key in row_key:
                value = row.get(real_col)

                if not is_blank(value):
                    return value

    return default


def parse_flexible_date(value, default_year=2026, allow_excel_serial=True):
    if pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value

    if isinstance(value, datetime):
        return pd.Timestamp(value)

    if isinstance(value, (int, float)):
        if not allow_excel_serial:
            return None

        number = float(value)

        if 20000 <= number <= 60000:
            parsed = pd.to_datetime(number, unit="D", origin="1899-12-30", errors="coerce")
            return parsed if not pd.isna(parsed) and is_reasonable_date(parsed) else None

        return None

    text = str(value).strip()

    if not text:
        return None

    numeric_text = text.replace(",", "")

    if re.fullmatch(r"\d+(\.\d+)?", numeric_text):
        if not allow_excel_serial:
            return None

        return parse_flexible_date(float(numeric_text), default_year=default_year, allow_excel_serial=True)

    embedded = re.search(
        rf"(\d{{1,2}}\s+(?:{MONTH_PATTERN})\s+\d{{2,4}})",
        text,
        flags=re.IGNORECASE,
    )

    if embedded:
        text = embedded.group(1)

    parsed = pd.to_datetime(text, errors="coerce", dayfirst=False)

    if not pd.isna(parsed) and is_reasonable_date(parsed):
        return parsed

    patterns = [
        r"^(\d{1,2})\s+([A-Za-z]+)$",
        r"^([A-Za-z]+)\s+(\d{1,2})$",
        r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{2,4})$",
        r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{2,4})$",
    ]

    for pattern in patterns:
        match = re.match(pattern, text)

        if not match:
            continue

        groups = match.groups()

        if groups[0].isdigit():
            day = int(groups[0])
            month = MONTH_LOOKUP.get(groups[1].lower())
            year = int(groups[2]) if len(groups) > 2 else default_year
        else:
            month = MONTH_LOOKUP.get(groups[0].lower())
            day = int(groups[1])
            year = int(groups[2]) if len(groups) > 2 else default_year

        if month:
            parsed = pd.Timestamp(year=year + 2000 if year < 100 else year, month=month, day=day)
            return parsed if is_reasonable_date(parsed) else None

    return None


def parse_date_range(value, default_year=2026, allow_excel_serial=True):
    if pd.isna(value):
        return None, None

    text = str(value).strip()

    for separator in DATE_RANGE_SEPARATORS:
        if separator in text:
            start_text, end_text = text.split(separator, 1)
            start = parse_flexible_date(
                start_text.strip(),
                default_year=default_year,
                allow_excel_serial=allow_excel_serial,
            )
            end = parse_flexible_date(
                end_text.strip(),
                default_year=default_year,
                allow_excel_serial=allow_excel_serial,
            )

            if start is not None and end is not None:
                if end.year == default_year and start.year != default_year:
                    end = end.replace(year=start.year)

                if end < start:
                    end = end.replace(year=start.year + 1)

            return start, end

    parsed = parse_flexible_date(
        value,
        default_year=default_year,
        allow_excel_serial=allow_excel_serial,
    )

    return parsed, parsed


def parse_date_range_from_text(value, default_year=2026):
    if pd.isna(value) or isinstance(value, (int, float)):
        return None, None

    text = str(value).strip().replace("\u2013", "–").replace("\u2014", "—")

    if not text:
        return None, None

    full_date = rf"\d{{1,2}}\s+(?:{MONTH_PATTERN})\s+\d{{2,4}}"
    short_date = rf"\d{{1,2}}\s+(?:{MONTH_PATTERN})"

    full_match = re.search(
        rf"({full_date})\s*(?:-|–|—|to|until)\s*({full_date})",
        text,
        flags=re.IGNORECASE,
    )

    if full_match:
        return (
            parse_flexible_date(full_match.group(1), default_year=default_year, allow_excel_serial=False),
            parse_flexible_date(full_match.group(2), default_year=default_year, allow_excel_serial=False),
        )

    short_match = re.search(
        rf"({short_date})\s*(?:-|–|—|to|until)\s*({short_date})(?:\s+(\d{{2,4}}))?",
        text,
        flags=re.IGNORECASE,
    )

    if short_match:
        year = int(short_match.group(3)) if short_match.group(3) else default_year
        year = year + 2000 if year < 100 else year

        return (
            parse_flexible_date(short_match.group(1), default_year=year, allow_excel_serial=False),
            parse_flexible_date(short_match.group(2), default_year=year, allow_excel_serial=False),
        )

    return None, None


def resolve_dates(row, default_year=2026):
    start = parse_flexible_date(
        get_first_existing(row, START_DATE_COLUMNS),
        default_year=default_year,
        allow_excel_serial=True,
    )
    end = parse_flexible_date(
        get_first_existing(row, END_DATE_COLUMNS),
        default_year=default_year,
        allow_excel_serial=True,
    )

    if start is None or end is None:
        range_start, range_end = parse_date_range(
            get_first_existing(row, DATE_RANGE_COLUMNS),
            default_year=default_year,
            allow_excel_serial=True,
        )

        start = start or range_start
        end = end or range_end

    return start, end


def infer_plan_date_bounds(raw_df, default_year=2026):
    starts = []
    ends = []

    for _, row in raw_df.iterrows():
        start, end = resolve_dates(row, default_year=default_year)

        if start is not None and is_reasonable_date(start):
            starts.append(start)

        if end is not None and is_reasonable_date(end):
            ends.append(end)

        for value in row.tolist():
            text_start, text_end = parse_date_range_from_text(value, default_year=default_year)

            if text_start is not None and is_reasonable_date(text_start):
                starts.append(text_start)

            if text_end is not None and is_reasonable_date(text_end):
                ends.append(text_end)

    return (min(starts) if starts else None, max(ends) if ends else None)


def get_client_date_fallback(client):
    client_key = str(client or "").upper().strip()
    return CLIENT_DATE_FALLBACKS.get(client_key, (None, None))


def apply_plan_date_fallback(plan_start, plan_end, client):
    fallback_start, fallback_end = get_client_date_fallback(client)

    if plan_start is None:
        plan_start = fallback_start

    if plan_end is None:
        plan_end = fallback_end

    return plan_start, plan_end


def is_total_row(channel, campaign_name=""):
    combined = normalize_text(f"{channel} {campaign_name}")
    return any(keyword in combined for keyword in TOTAL_ROW_KEYWORDS)


def is_non_media_row(channel, campaign_name=""):
    combined = normalize_text(f"{channel} {campaign_name}")

    return (
        is_total_row(channel, campaign_name)
        or is_bad_partner_value(channel)
        or any(token in combined for token in NON_MEDIA_PARTNER_CONTAINS)
    )


def derive_gross_media(gross_media, net_media, impressions, cpm):
    if gross_media > 0:
        return gross_media

    if net_media > 0:
        return net_media

    if impressions > 0 and cpm > 0:
        return impressions / 1000 * cpm

    return 0.0


def first_valid_date(values, use_min=True):
    dates = [
        parsed
        for parsed in (
            parse_flexible_date(value, allow_excel_serial=True)
            for value in values
        )
        if parsed is not None and is_reasonable_date(parsed)
    ]

    return None if not dates else min(dates) if use_min else max(dates)


def apply_date_fallbacks(start_date, end_date, plan_start, plan_end):
    start_date = start_date or plan_start
    end_date = end_date or plan_end

    if start_date is None and end_date is not None:
        start_date = end_date

    if end_date is None and start_date is not None:
        end_date = start_date

    return start_date, end_date


def build_normalized_record(
    row,
    client,
    channel,
    campaign_name,
    partner,
    start_date,
    end_date,
    gross_media,
    net_media,
    impressions,
    cpm,
    default_currency="",
):
    kpi = str(get_first_existing(row, KPI_COLUMNS, "CPM")).upper().strip()

    return {
        "client": str(client).upper().strip(),
        "channel": str(channel).strip(),
        "partner": partner,
        "campaign_name": campaign_name,
        "targeting": get_first_existing(row, ["Targeting", "Audience", "Target Audience", "Targeting Details"], ""),
        "kpi": kpi,
        "buy_type": kpi,
        "start_date": start_date,
        "end_date": end_date,
        "flight_start": start_date,
        "flight_end": end_date,
        "net_media": net_media,
        "gross_media": gross_media,
        "impressions": impressions,
        "clicks": clean_number(get_first_existing(row, CLICK_COLUMNS, 0)),
        "installs": clean_number(get_first_existing(row, INSTALL_COLUMNS, 0)),
        "cpm": cpm,
        "cpc": clean_money(get_first_existing(row, CPC_COLUMNS, 0)),
        "cpi": clean_money(get_first_existing(row, CPI_COLUMNS, 0)),
        "currency": default_currency,
    }


def adapt_plan(raw_df, client="UNKNOWN", default_year=2026, gu_mode=False):
    records = []
    plan_start, plan_end = infer_plan_date_bounds(raw_df, default_year=default_year)
    plan_start, plan_end = apply_plan_date_fallback(plan_start, plan_end, client)

    for _, row in raw_df.iterrows():
        channel = get_first_existing(row, ["Channel"] if gu_mode else CHANNEL_COLUMNS)
        campaign_name = get_first_existing(row, CAMPAIGN_COLUMNS, "")

        if is_blank(channel):
            channel = campaign_name

        if is_blank(channel) or is_non_media_row(channel, campaign_name):
            continue

        partner = normalize_partner(channel)

        if not partner:
            continue

        start_date, end_date = apply_date_fallbacks(
            *resolve_dates(row, default_year=default_year),
            plan_start,
            plan_end,
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
                ] if gu_mode else GROSS_MEDIA_COLUMNS,
                0,
            )
        )

        net_media = clean_money(
            get_first_existing(
                row,
                ["Net Media (Budget excluding fees)", "Net Media", "Media Budget", "Budget"] if gu_mode else NET_MEDIA_COLUMNS,
                gross_media,
            )
        )

        impressions = clean_number(get_first_existing(row, IMPRESSION_COLUMNS, 0))
        cpm = clean_money(get_first_existing(row, CPM_COLUMNS, 0))
        gross_media = derive_gross_media(gross_media, net_media, impressions, cpm)

        if gross_media > 0 and net_media <= 0:
            net_media = gross_media

        if not gu_mode and gross_media <= 0 and impressions <= 0:
            continue

        records.append(
            build_normalized_record(
                row=row,
                client=client,
                channel=channel,
                campaign_name=campaign_name,
                partner=partner,
                start_date=start_date,
                end_date=end_date,
                gross_media=gross_media,
                net_media=net_media,
                impressions=impressions,
                cpm=cpm,
                default_currency="USD" if gu_mode else "",
            )
        )

    if not records:
        label = "GU " if gu_mode else ""
        raise ValueError(
            f"No valid {label}placement rows found after adaptation. "
            f"Columns found: {list(raw_df.columns)}"
        )

    return pd.DataFrame(records)


def adapt_gu_plan(raw_df, client="GU", default_year=2026):
    return adapt_plan(raw_df, client=client, default_year=default_year, gu_mode=True)


def adapt_generic_plan(raw_df, client="UNKNOWN", default_year=2026):
    return adapt_plan(raw_df, client=client, default_year=default_year, gu_mode=False)


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return 0.0


def consolidate_for_prisma(normalized_df):
    if normalized_df.empty:
        raise ValueError("Cannot consolidate an empty media plan dataframe.")

    required = ["client", "partner", "gross_media", "impressions", "start_date", "end_date"]
    missing = [col for col in required if col not in normalized_df.columns]

    if missing:
        raise ValueError("Missing required column(s) for consolidation: " + ", ".join(missing))

    df = normalized_df[
        normalized_df["partner"].apply(lambda value: not is_bad_partner_value(value))
    ].copy()

    if df.empty:
        raise ValueError("No valid rows remain after removing invalid partner/channel rows.")

    placements = []

    for (client, partner), group in df.groupby(["client", "partner"], dropna=False):
        planned_amount = float(group["gross_media"].sum())
        planned_units = float(group["impressions"].sum())

        if planned_units <= 0:
            planned_units = float(
                group.apply(
                    lambda row: (
                        safe_float(row.get("gross_media", 0)) / safe_float(row.get("cpm", 0)) * 1000
                        if safe_float(row.get("gross_media", 0)) > 0 and safe_float(row.get("cpm", 0)) > 0
                        else 0
                    ),
                    axis=1,
                ).sum()
            )

        flight_start = (
            first_valid_date(group["flight_start"], True)
            if "flight_start" in group.columns
            else None
        ) or first_valid_date(group["start_date"], True)

        flight_end = (
            first_valid_date(group["flight_end"], False)
            if "flight_end" in group.columns
            else None
        ) or first_valid_date(group["end_date"], False)

        flight_start = flight_start or flight_end
        flight_end = flight_end or flight_start

        placements.append(
            {
                "client": client,
                "partner": partner,
                "placement_name": f"{client} - {partner} - CPM",
                "cost_method": "CPM",
                "unit_type": "Impressions",
                "unit_rate": round(planned_amount / planned_units * 1000, 2) if planned_units > 0 else 0.0,
                "planned_units": int(round(planned_units, 0)),
                "planned_amount": round(planned_amount, 2),
                "start_date": flight_start,
                "end_date": flight_end,
                "flight_start": flight_start,
                "flight_end": flight_end,
                "source_rows": len(group),
            }
        )

    return pd.DataFrame(placements)


def adapt_media_plan(raw_df, client="GU", default_year=2026):
    client = str(client).upper().strip()
    return adapt_gu_plan(raw_df, client, default_year) if client == "GU" else adapt_generic_plan(raw_df, client, default_year)
