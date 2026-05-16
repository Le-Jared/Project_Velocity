"""
Prisma import builder — writes a Prisma-ready Excel file using the
ACCT-108 DIGITAL TEMPLATE and a Buying Guide for supplier-code lookup.
Mirrors the role of invoice_sorter.py for the Prisma pipeline.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Optional

import openpyxl

from buying_guide  import BuyingGuide
from plan_adapters import Placement
from gemini_fallback_prisma import is_available as gemini_available, _get_client, _parse_json, GEMINI_MODEL


SHEET_NAME = "Digital import sheet ALL TYPES"

# Column positions on the template (1-indexed) — adjust if your template differs
COLS = {
    "Row Type":               1,
    "Site Name/Supplier":     2,
    "PACKAGE/PLACEMENT TYPE": 3,
    "Buy Type":               4,
    "Buy Category":           5,
    "Booking Category":       6,
    "Package name":           7,
    "Placement Name":         8,
    "Unit Dimensions":        9,
    "Positioning":           10,
    "Cost Method":           11,
    "Unit Type":             12,
    "Unit Rate":             13,
    "Planned unit amount":   14,
    "Gross/Planned Cost":    15,
    "Flight Start":          16,
    "Flight End":            17,
}


def build_prisma_import(
    placements: list[Placement],
    client_code: str,
    template_path: Path,
    buying_guide_path: Path,
    output_dir: Path,
    output_name: Optional[str] = None,
) -> dict:
    """
    Build a Prisma-ready import xlsx.

    Returns:
        {
            "output_path": Path,
            "matched":     int,
            "unmatched":   list[str],   # channel names that had no guide match
            "total":       int,
        }
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not template_path.exists():
        raise FileNotFoundError(f"Prisma template not found: {template_path}")
    if not buying_guide_path.exists():
        raise FileNotFoundError(f"Buying Guide not found: {buying_guide_path}")

    guide = BuyingGuide(buying_guide_path)
    wb    = openpyxl.load_workbook(template_path)

    if SHEET_NAME not in wb.sheetnames:
        wb.close()
        raise ValueError(f"Sheet '{SHEET_NAME}' missing from template")

    ws = wb[SHEET_NAME]

    consolidated = _consolidate(placements)
    start_row    = _find_first_empty_row(ws)

    # ── Pre-build Gemini alias cache for unmatched channels ───────────────
    # Attempt Gemini resolution once per unique unmatched channel name
    # so we don't call the API redundantly for repeated channels.
    gemini_alias_cache: dict[str, Optional[str]] = {}

    matched   = 0
    unmatched: list[str] = []

    current_row = start_row
    for p in consolidated:
        guide_row = guide.lookup(
            client   = client_code,
            channel  = p.channel,
            currency = p.currency,
        )

        # ── Point 2: Gemini fallback for unmatched channels ───────────────
        if guide_row is None and gemini_available():
            channel_key = p.channel.strip().lower()

            # Use cached result if we've already asked Gemini about this channel
            if channel_key not in gemini_alias_cache:
                gemini_alias_cache[channel_key] = _gemini_resolve_channel(
                    channel     = p.channel,
                    client_code = client_code,
                    guide       = guide,
                )

            resolved_name = gemini_alias_cache[channel_key]
            if resolved_name:
                # Retry lookup with Gemini-suggested name
                guide_row = guide.lookup(
                    client   = client_code,
                    channel  = resolved_name,
                    currency = p.currency,
                )
                if guide_row:
                    print(f"  [GEMINI] Resolved '{p.channel}' → '{resolved_name}'")
                    # Persist alias so future plans don't need Gemini for this
                    guide.CHANNEL_ALIASES[
                        BuyingGuide._normalize(p.channel)
                    ] = BuyingGuide._normalize(resolved_name)
        # ─────────────────────────────────────────────────────────────────

        if not guide_row:
            unmatched.append(p.channel)
            continue

        _write_row(ws, current_row, p, guide_row)
        current_row += 1
        matched     += 1

    out_name = output_name or _default_name(client_code)
    out_path = output_dir / out_name
    wb.save(out_path)
    wb.close()

    # Sidecar report — same pattern as invoice_sort_report.csv
    _write_report(out_path, client_code, matched, unmatched, len(consolidated))

    return {
        "output_path": out_path,
        "matched":     matched,
        "unmatched":   sorted(set(unmatched)),
        "total":       len(consolidated),
    }


# ── Gemini channel resolver ───────────────────────────────────────────────

def _gemini_resolve_channel(
    channel: str,
    client_code: str,
    guide: BuyingGuide,
) -> Optional[str]:
    """
    Ask Gemini to map an unrecognised channel name to a known
    Buying Guide booking type. Returns the suggested name or None.
    """
    known_keys = sorted({
        row["_booking_key"]
        for row in guide.rows
        if client_code.upper() in row["_clients"]
        and row["_booking_key"]
    })

    if not known_keys:
        return None

    prompt = f"""You are a media planning data assistant.

A channel named "{channel}" (client: {client_code}) could not be matched
to any entry in the Buying Guide.

The known Buying Guide booking types for this client are:
{known_keys}

Which one of the above booking types best matches "{channel}"?
Reply with ONLY the exact booking type string from the list, or reply with
the word NONE if there is no reasonable match.
"""

    try:
        client   = _get_client()
        response = client.models.generate_content(
            model    = GEMINI_MODEL,
            contents = prompt,
        )
        suggestion = (response.text or "").strip().strip('"').strip("'")
        if not suggestion or suggestion.upper() == "NONE":
            return None
        # Validate it's actually in the known list (prevent hallucination)
        norm = BuyingGuide._normalize(suggestion)
        if any(BuyingGuide._normalize(k) == norm for k in known_keys):
            return suggestion
        print(f"  [GEMINI] Suggestion '{suggestion}' not in known keys — ignored")
        return None
    except Exception as e:
        print(f"  [GEMINI] Channel resolution failed for '{channel}': {e}")
        return None


# ── Internal helpers ──────────────────────────────────────────────────────

def _write_row(ws, row_idx: int, p: Placement, guide_row: dict) -> None:
    """Write a single Prisma row using guide values + placement data."""
    def G(key, default=None):
        val = guide_row.get(key)
        return val if val not in (None, "") else default

    cost_method = G("Cost method", p.cost_method or "CPM")
    unit_type   = G("Unit type",   "Impressions")

    ws.cell(row=row_idx, column=COLS["Row Type"],               value="Direct placement")
    ws.cell(row=row_idx, column=COLS["Site Name/Supplier"],     value=G("Supplier name"))
    ws.cell(row=row_idx, column=COLS["PACKAGE/PLACEMENT TYPE"], value="Standalone")
    ws.cell(row=row_idx, column=COLS["Buy Type"],               value=G("Buy type", "Display"))
    ws.cell(row=row_idx, column=COLS["Buy Category"],           value=G("Buy category", "Display"))
    ws.cell(row=row_idx, column=COLS["Booking Category"],       value="Standard")
    ws.cell(row=row_idx, column=COLS["Package name"],           value=G("Buy type", "Display"))
    ws.cell(row=row_idx, column=COLS["Placement Name"],         value=p.placement_name or p.channel)
    ws.cell(row=row_idx, column=COLS["Unit Dimensions"],        value=G("Ad size", "1 x 1"))
    ws.cell(row=row_idx, column=COLS["Positioning"],            value=G("Positioning", "Other"))
    ws.cell(row=row_idx, column=COLS["Cost Method"],            value=cost_method)
    ws.cell(row=row_idx, column=COLS["Unit Type"],              value=unit_type)
    ws.cell(row=row_idx, column=COLS["Unit Rate"],              value=p.unit_rate or None)
    ws.cell(row=row_idx, column=COLS["Planned unit amount"],    value=p.planned_units or None)
    ws.cell(row=row_idx, column=COLS["Gross/Planned Cost"],     value=p.planned_amount or p.gross_amount)
    ws.cell(row=row_idx, column=COLS["Flight Start"],           value=_to_date(p.flight_start))
    ws.cell(row=row_idx, column=COLS["Flight End"],             value=_to_date(p.flight_end))


def _consolidate(placements: list[Placement]) -> list[Placement]:
    """Group by (channel, currency, flight, cost_method) — sum budgets/units."""
    buckets: dict[tuple, Placement] = {}
    for p in placements:
        key = (
            p.channel.lower().strip(),
            p.currency,
            p.flight_start,
            p.flight_end,
            p.cost_method,
        )
        if key in buckets:
            b = buckets[key]
            b.planned_amount += p.planned_amount
            b.gross_amount   += p.gross_amount
            b.planned_units  += p.planned_units
        else:
            buckets[key] = Placement(**{**p.__dict__})
    return list(buckets.values())


def _find_first_empty_row(ws) -> int:
    """Find the first row where column A is empty (after sample template rows)."""
    row = 2
    while ws.cell(row=row, column=1).value not in (None, ""):
        row += 1
    return row


def _to_date(value):
    """Best-effort string → datetime conversion for Excel date cells."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    for fmt in (
        "%Y-%m-%d",
        "%m-%d-%y",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%d %b %Y",
        "%d-%b-%Y",
        "%d %B %Y",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return s  # fall back to the raw string


def _default_name(client_code: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"PRISMA_IMPORT_{client_code}_{stamp}.xlsx"


def _write_report(
    output_path: Path,
    client_code: str,
    matched: int,
    unmatched: list[str],
    total: int,
) -> None:
    """Write a small .report.txt next to the import file."""
    report = output_path.with_suffix(".report.txt")
    lines = [
        f"Prisma Import Report",
        f"====================",
        f"Generated:        {datetime.now().isoformat(timespec='seconds')}",
        f"Output:           {output_path.name}",
        f"Client:           {client_code}",
        f"Total placements: {total}",
        f"Matched:          {matched}",
        f"Unmatched:        {len(set(unmatched))}",
        "",
    ]
    if unmatched:
        lines.append("Unmatched channels (add to Buying Guide):")
        for ch in sorted(set(unmatched)):
            lines.append(f"  - {ch}")
    report.write_text("\n".join(lines), encoding="utf-8")