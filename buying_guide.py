from pathlib import Path
import re
import pandas as pd


GUIDE_COLUMNS = [
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


ENRICH_COLUMNS = {
    "buy_type": "Buy type",
    "financial_buy_type": "Financial buy type",
    "buy_category": "Buy category",
    "currency": "Currency",
    "supplier_code": "Supplier code",
    "supplier_name": "Supplier name",
    "positioning": "Positioning",
    "ad_size": "Ad size",
    "guide_cost_method": "Cost method",
    "guide_unit_type": "Unit type",
    "placement_booking_type": "Placement booking type",
}


ALLOW_CROSS_CLIENT_PARTNER_FALLBACK = True


PARTNER_ALIASES = {
    "Meta": ["Facebook", "Meta", "FB", "Instagram", "Threads"],
    "Facebook": ["Facebook", "Meta", "FB", "Instagram", "Threads"],

    "TikTok": ["TikTok", "Tiktok", "Tik Tok"],
    "Tiktok": ["TikTok", "Tiktok", "Tik Tok"],

    "Google": ["Google", "UAC", "Universal App Campaign"],
    "UAC": ["Google", "UAC", "Universal App Campaign"],

    "Google Search": ["Google Search", "Search", "SEM", "Paid Search"],
    "Google PMAX": ["Google PMAX", "Google - PMAX", "PMAX", "PMax", "Performance Max"],
    "Google Display": ["Google Display", "Display", "GDN", "Google Display Network"],
    "Google Demand Gen": ["Google Demand Gen", "Demand Gen", "DemandGen", "Discovery"],
    "Google Youtube": ["Google Youtube", "Google YouTube", "Youtube", "YouTube", "YT"],

    "Apple Search": ["Apple Search", "Apple Search Ads", "ASA", "IAD", "Apple"],
    "ASA": ["Apple Search", "Apple Search Ads", "ASA", "IAD", "Apple"],
    "Asa": ["Apple Search", "Apple Search Ads", "ASA", "IAD", "Apple"],

    "Reddit": ["Reddit", "Reddit Traffic"],
    "Reddit Traffic": ["Reddit", "Reddit Traffic"],

    "The Trade Desk": ["The Trade Desk", "Trade Desk", "TTD"],
    "TTD": ["The Trade Desk", "Trade Desk", "TTD"],

    "Moloco": ["Moloco"],
    "Jampp": ["Jampp"],
}


PARTNER_DETECTION_RULES = [
    ("Meta", ["facebook", "meta", "instagram", "threads"]),
    ("TikTok", ["tiktok", "tik tok"]),
    ("Apple Search", ["apple search", "apple search ads", "asa", "iad"]),
    ("Reddit", ["reddit"]),
    ("The Trade Desk", ["trade desk", "ttd"]),
    ("Moloco", ["moloco"]),
    ("Jampp", ["jampp"]),
    ("Google Demand Gen", ["demand gen", "demandgen", "discovery"]),
    ("Google Youtube", ["youtube", "you tube", "yt"]),
    ("Google Search", ["google search", "paid search", "search", "sem"]),
    ("Google Display", ["google display", "display", "gdn"]),
    ("Google PMAX", ["google pmax", "google p max", "pmax", "p max", "performance max"]),
    ("Google", ["google", "uac", "universal app campaign"]),
]


GOOGLE_SPECIFIC_MARKERS = {
    "Google PMAX": ["pmax", "p max", "performance max"],
    "Google Search": ["search", "sem", "paid search"],
    "Google Display": ["display", "gdn", "google display network"],
    "Google Demand Gen": ["demand gen", "demandgen", "discovery"],
    "Google Youtube": ["youtube", "you tube", "yt"],
    "Google": ["google", "uac", "universal app campaign"],
}


GENERIC_GOOGLE_PREFERENCE = [
    "google display",
    "google youtube",
    "google search",
    "google pmax",
    "google p max",
    "google demand gen",
    "google",
]


def normalize_text(value):
    if pd.isna(value):
        return ""

    text = str(value).strip().lower()
    text = re.sub(r"[_\-/|(),;:\[\]]+", " ", text)

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


def clean_columns(df):
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]
    return df


def load_buying_guide(path, sheet_name="Buying guide 2"):
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Buying Guide not found: {path}")

    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    df = clean_columns(df)

    missing = [col for col in GUIDE_COLUMNS if col not in df.columns]

    if missing:
        raise ValueError("Buying Guide is missing required columns: " + ", ".join(missing))

    df = df.dropna(how="all").copy()

    for col in GUIDE_COLUMNS:
        df[col] = df[col].apply(lambda value: "" if is_blank(value) else str(value).strip())

    return df


def split_client_tokens(value):
    text = str(value or "").upper().strip()

    return [
        token
        for token in re.split(r"[\s,;/|]+", text)
        if token
    ]


def client_matches(value, client):
    value_text = str(value).strip().upper() if not pd.isna(value) else ""
    client_text = str(client).strip().upper() if not pd.isna(client) else ""

    if not value_text or not client_text:
        return False

    if value_text == client_text:
        return True

    return client_text in split_client_tokens(value_text)


def partner_aliases(partner):
    partner_text = str(partner).strip()
    normalized = normalize_text(partner_text)

    if partner_text in PARTNER_ALIASES:
        return PARTNER_ALIASES[partner_text]

    for canonical, needles in PARTNER_DETECTION_RULES:
        if any(normalize_text(needle) in normalized for needle in needles):
            return PARTNER_ALIASES[canonical]

    return [partner_text]


def normalized_aliases(partner):
    values = [partner] + partner_aliases(partner)
    normalized = []

    for value in values:
        text = normalize_text(value)

        if text and text not in normalized:
            normalized.append(text)

    return normalized


def text_contains_alias(value, partner):
    text = normalize_text(value)

    if not text:
        return False

    aliases = normalized_aliases(partner)

    return any(alias in text for alias in aliases)


def text_exact_or_token_match(value, partner):
    text = normalize_text(value)

    if not text:
        return False

    aliases = normalized_aliases(partner)

    if text in aliases:
        return True

    padded_text = f" {text} "

    return any(f" {alias} " in padded_text for alias in aliases)


def is_google_partner(partner):
    partner_norm = normalize_text(partner)
    return partner_norm.startswith("google") or partner_norm == "uac"


def google_specificity_score(booking_type, partner):
    booking = normalize_text(booking_type)
    partner_norm = normalize_text(partner)

    score = 0

    if not booking:
        return score

    if partner_norm and partner_norm in booking:
        score += 100

    for marker in GOOGLE_SPECIFIC_MARKERS.get(partner, []):
        marker_norm = normalize_text(marker)

        if marker_norm and marker_norm in booking:
            score += 25

    if normalize_text(partner) == "google":
        for index, preferred in enumerate(GENERIC_GOOGLE_PREFERENCE):
            if preferred in booking:
                score += max(20 - index, 1)
                break

    if "client paying supplier" in booking:
        score += 5

    return score


def match_quality_score(row, partner):
    booking_type = row.get("Placement booking type", "")
    supplier_name = row.get("Supplier name", "")

    score = 0

    if text_exact_or_token_match(booking_type, partner):
        score += 100

    if text_contains_alias(booking_type, partner):
        score += 50

    if text_contains_alias(supplier_name, partner):
        score += 20

    if is_google_partner(partner):
        score += google_specificity_score(booking_type, partner)

    if str(row.get("Cost method", "")).upper().strip() == "CPM":
        score += 10

    return score


def available_booking_types(df, limit=8):
    values = (
        df["Placement booking type"]
        .dropna()
        .astype(str)
        .map(str.strip)
    )

    values = [value for value in values.unique().tolist() if value]

    return values if len(values) <= limit else values[:limit] + [f"... plus {len(values) - limit} more"]


def client_rows(guide_df, client):
    col = "Clients that uses these respectively"

    rows = guide_df[
        guide_df[col].apply(lambda value: client_matches(value, client))
    ].copy()

    if rows.empty:
        raise ValueError(f"No Buying Guide rows found for client='{client}'.")

    return rows


def safe_client_rows(guide_df, client):
    col = "Clients that uses these respectively"

    return guide_df[
        guide_df[col].apply(lambda value: client_matches(value, client))
    ].copy()


def filter_partner_matches(rows, partner):
    partner_text = str(partner).strip()

    exact_matches = rows[
        rows["Placement booking type"].apply(
            lambda value: text_exact_or_token_match(value, partner_text)
        )
    ].copy()

    if not exact_matches.empty:
        return exact_matches

    contains_matches = rows[
        rows["Placement booking type"].apply(
            lambda value: text_contains_alias(value, partner_text)
        )
    ].copy()

    if not contains_matches.empty:
        return contains_matches

    supplier_matches = rows[
        rows["Supplier name"].apply(
            lambda value: text_contains_alias(value, partner_text)
        )
    ].copy()

    return supplier_matches


def rank_matches(matches, partner):
    matches = matches.copy()

    matches["_is_cpm"] = (
        matches["Cost method"].astype(str).str.upper().str.strip() == "CPM"
    ).astype(int)

    matches["_match_score"] = matches.apply(
        lambda row: match_quality_score(row, partner),
        axis=1,
    )

    matches["_booking_length"] = matches["Placement booking type"].astype(str).str.len()

    return matches.sort_values(
        by=["_is_cpm", "_match_score", "_booking_length"],
        ascending=[False, False, True],
    )


def annotate_match(row_dict, requested_client, requested_partner, match_scope):
    row_dict = dict(row_dict)
    row_dict["_requested_client"] = requested_client
    row_dict["_requested_partner"] = requested_partner
    row_dict["_match_scope"] = match_scope
    row_dict["_matched_guide_clients"] = row_dict.get("Clients that uses these respectively", "")
    return row_dict


def match_buying_guide_row(guide_df, client, partner):
    client_specific_rows = safe_client_rows(guide_df, client)

    if not client_specific_rows.empty:
        client_matches_df = filter_partner_matches(client_specific_rows, partner)

        if not client_matches_df.empty:
            ranked = rank_matches(client_matches_df, partner)
            guide_row = ranked.iloc[0].drop(
                labels=["_is_cpm", "_match_score", "_booking_length"],
                errors="ignore",
            ).to_dict()
            return annotate_match(guide_row, client, partner, "client_specific")

    if ALLOW_CROSS_CLIENT_PARTNER_FALLBACK:
        cross_client_matches = filter_partner_matches(guide_df, partner)

        if not cross_client_matches.empty:
            ranked = rank_matches(cross_client_matches, partner)
            guide_row = ranked.iloc[0].drop(
                labels=["_is_cpm", "_match_score", "_booking_length"],
                errors="ignore",
            ).to_dict()
            return annotate_match(guide_row, client, partner, "cross_client_partner_fallback")

    available_rows = client_specific_rows if not client_specific_rows.empty else guide_df

    if client_specific_rows.empty:
        raise ValueError(
            f"No Buying Guide rows found for client='{client}'. "
            f"Cross-client fallback found no approved partner row for partner='{partner}'."
        )

    raise ValueError(
        f"No Buying Guide match found for client='{client}', partner='{partner}'. "
        f"Available booking types: {available_booking_types(available_rows)}"
    )


def preview_match_score(guide_row, partner):
    try:
        return match_quality_score(pd.Series(guide_row), partner)
    except Exception:
        return 0


def enrich_with_buying_guide(consolidated_df, guide_df, skip_unmatched=False):
    if consolidated_df.empty:
        raise ValueError("Cannot enrich an empty consolidated dataframe.")

    enriched_rows = []
    skipped_rows = []
    fallback_rows = []

    for _, row in consolidated_df.iterrows():
        client = row.get("client")
        partner = row.get("partner")

        try:
            guide_row = match_buying_guide_row(guide_df, client, partner)
        except Exception as exc:
            if not skip_unmatched:
                raise

            skipped_rows.append(
                {
                    "client": client,
                    "partner": partner,
                    "placement_name": row.get("placement_name"),
                    "planned_amount": row.get("planned_amount"),
                    "planned_units": row.get("planned_units"),
                    "reason": str(exc),
                }
            )
            continue

        enriched = row.to_dict()
        enriched.update(
            {
                target: guide_row.get(source)
                for target, source in ENRICH_COLUMNS.items()
            }
        )

        enriched["buying_guide_match_score"] = preview_match_score(guide_row, partner)
        enriched["buying_guide_match_scope"] = guide_row.get("_match_scope", "")
        enriched["matched_guide_clients"] = guide_row.get("_matched_guide_clients", "")

        if guide_row.get("_match_scope") == "cross_client_partner_fallback":
            fallback_rows.append(
                {
                    "client": client,
                    "partner": partner,
                    "placement_name": row.get("placement_name"),
                    "planned_amount": row.get("planned_amount"),
                    "planned_units": row.get("planned_units"),
                    "matched_guide_clients": guide_row.get("_matched_guide_clients", ""),
                    "placement_booking_type": guide_row.get("Placement booking type", ""),
                    "supplier_name": guide_row.get("Supplier name", ""),
                    "supplier_code": guide_row.get("Supplier code", ""),
                    "reason": "Used approved Buying Guide row for the same partner from another client because no client-specific row was found.",
                }
            )

        enriched_rows.append(enriched)

    if not enriched_rows:
        details = "; ".join(
            f"{item['client']} / {item['partner']}: {item['reason']}"
            for item in skipped_rows[:10]
        )

        raise ValueError(
            "No Buying Guide matches found after skipping unmatched rows. "
            f"Skipped rows: {details}"
        )

    result = pd.DataFrame(enriched_rows)

    if skipped_rows:
        result.attrs["skipped_buying_guide_rows"] = skipped_rows

    if fallback_rows:
        result.attrs["cross_client_buying_guide_fallback_rows"] = fallback_rows

    return result


def preview_buying_guide_matches(consolidated_df, guide_df):
    rows = []

    for _, row in consolidated_df.iterrows():
        client = row.get("client")
        partner = row.get("partner")

        try:
            guide_row = match_buying_guide_row(guide_df, client, partner)
            match_scope = guide_row.get("_match_scope", "")

            preview = {
                "status": "Matched" if match_scope == "client_specific" else "Matched via cross-client fallback",
                "supplier_name": guide_row.get("Supplier name"),
                "supplier_code": guide_row.get("Supplier code"),
                "placement_booking_type": guide_row.get("Placement booking type"),
                "cost_method": guide_row.get("Cost method"),
                "currency": guide_row.get("Currency"),
                "match_score": preview_match_score(guide_row, partner),
                "match_scope": match_scope,
                "matched_guide_clients": guide_row.get("_matched_guide_clients", ""),
                "planned_amount": row.get("planned_amount"),
                "planned_units": row.get("planned_units"),
            }
        except Exception as exc:
            preview = {
                "status": f"Error: {exc}",
                "supplier_name": "",
                "supplier_code": "",
                "placement_booking_type": "",
                "cost_method": "",
                "currency": "",
                "match_score": 0,
                "match_scope": "",
                "matched_guide_clients": "",
                "planned_amount": row.get("planned_amount"),
                "planned_units": row.get("planned_units"),
            }

        rows.append(
            {
                "client": client,
                "partner": partner,
                "placement_name": row.get("placement_name"),
                **preview,
            }
        )

    return pd.DataFrame(rows)


class BuyingGuide:
    def __init__(self, path, sheet_name="Buying guide 2"):
        self.path = path
        self.df = load_buying_guide(path, sheet_name=sheet_name)

    def __len__(self):
        return len(self.df)

    def clients(self):
        col = "Clients that uses these respectively"

        if col not in self.df.columns:
            return []

        clients = set()

        for value in self.df[col].dropna().astype(str):
            tokens = split_client_tokens(value)

            if tokens:
                clients.update(tokens)

        return sorted(clients)
