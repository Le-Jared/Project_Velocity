"""
Media plan adapters — one class per known template.
All adapters output a normalized list[Placement] regardless of source layout.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ── Normalized Placement ─────────────────────────────────────────────────────

@dataclass
class Placement:
    """Source-agnostic placement row."""
    channel:         str
    campaign_name:   str = ""
    placement_name: str = ""
    objective:       str = ""
    cost_method:     str = ""        # CPM / CPC / CPI / CPV / CPT
    unit_rate:       float = 0.0
    planned_units:   float = 0.0
    planned_amount: float = 0.0      # net media
    gross_amount:    float = 0.0     # with agency fee
    currency:        str = "USD"
    flight_start:    str = ""
    flight_end:      str = ""
    geography:       str = ""
    ad_format:       str = ""
    targeting:       str = ""
    os:              str = ""
    extras:          dict = field(default_factory=dict)


# ── Base Adapter ─────────────────────────────────────────────────────────────

class BasePlanAdapter:
    client_code: str = ""
    label:       str = "Unknown"

    def detect(self, wb) -> bool:
        raise NotImplementedError

    def extract(self, wb) -> list[Placement]:
        raise NotImplementedError

    @staticmethod
    def _flt(value, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            if isinstance(value, str):
                value = value.replace(",", "").replace("$", "").strip()
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _str(value) -> str:
        if value is None:
            return ""
        return str(value).strip()


# ── SkillIgnition (GU client) ────────────────────────────────────────────────

class SkillIgnitionAdapter(BasePlanAdapter):
    client_code = "GU"
    label       = "SkillIgnition"
    sheet_name  = "MP"

    def detect(self, wb) -> bool:
        if self.sheet_name not in wb.sheetnames:
            return False
        ws = wb[self.sheet_name]
        for row in ws.iter_rows(min_row=1, max_row=8, values_only=True):
            joined = " ".join(self._str(c) for c in row).lower()
            if "campaign name" in joined and "campaign id" in joined:
                return True
        return False

    def extract(self, wb) -> list[Placement]:
        ws = wb[self.sheet_name]
        placements: list[Placement] = []

        # Locate the row whose first non-empty cell == "Channel"
        header_row_idx = None
        header_values  = None
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), start=1):
            for c in row:
                if self._str(c).lower() == "channel":
                    header_row_idx = i
                    header_values  = row
                    break
            if header_row_idx:
                break

        if not header_row_idx or not header_values:
            return placements

        headers = [self._str(c) for c in header_values]
        col     = {h.lower(): idx for idx, h in enumerate(headers) if h}

        def g(row, *keys):
            for k in keys:
                idx = col.get(k.lower())
                if idx is not None and idx < len(row) and row[idx] is not None:
                    return row[idx]
            return None

        for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
            channel = self._str(g(row, "Channel"))
            if not channel:
                continue
            campaign = self._str(g(row, "Campaign Name"))
            kpi      = self._str(g(row, "KPI"))
            net      = self._flt(g(row, "Net Media (Budget excluding fees)"))
            gross    = self._flt(g(row, "Gross Media (Budget with Fee)"))
            start    = self._str(g(row, "Campaign \nStart", "Campaign Start"))
            end      = self._str(g(row, "Campaign \nEnd", "Campaign End"))
            cpm      = self._flt(g(row, "Estimated CPM (USD)"))
            imps     = self._flt(g(row, "Estimated Impression"))

            placements.append(Placement(
                channel         = channel,
                campaign_name  = campaign,
                placement_name = campaign or channel,
                objective       = kpi,
                cost_method     = kpi.upper() if kpi else "CPM",
                unit_rate       = cpm,
                planned_units   = imps,
                planned_amount = net,
                gross_amount    = gross,
                currency        = "USD",
                flight_start    = start,
                flight_end      = end,
            ))
        return placements


# ── MCP 2026 Mobile Media Plan ───────────────────────────────────────────────

class MCPAdapter(BasePlanAdapter):
    client_code = "MCP"
    label       = "MCP 2026"

    def detect(self, wb) -> bool:
        for sn in wb.sheetnames:
            ws = wb[sn]
            for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
                joined = " ".join(self._str(c) for c in row).upper()
                if "MOBILE MEDIA" in joined and "CAMPAIGN DETAILS" in joined:
                    return True
        return False

    def extract(self, wb) -> list[Placement]:
        placements: list[Placement] = []
        for sn in wb.sheetnames:
            ws = wb[sn]
            currency = "SGD"
            section  = ""

            # First pass — find client currency
            for row in ws.iter_rows(min_row=1, max_row=20, values_only=True):
                if not row:
                    continue
                first = self._str(row[0]).upper()
                if "CLIENT CURRENCY" in first:
                    for cell in row[1:]:
                        val = self._str(cell)
                        if val:
                            currency = val
                            break
                    break

            # Walk rows — toggle in_table when a new "Channel" header is found
            in_table = False
            headers: list[str] = []
            for row in ws.iter_rows(values_only=True):
                first = self._str(row[0]) if row else ""

                if first.upper() in ("MCP1", "MCP2"):
                    section  = first.upper()
                    in_table = False
                    continue

                if first.lower() == "channel":
                    headers  = [self._str(c) for c in row]
                    in_table = True
                    continue

                if in_table:
                    if not first or "total" in first.lower():
                        in_table = False
                        continue

                    rec = dict(zip(headers, row))
                    media_budget = self._flt(rec.get("Media Budget (SGD)"))
                    gross        = self._flt(rec.get("Gross media budget (SGD)"))

                    if media_budget == 0 and gross == 0:
                        continue

                    os_val = self._str(rec.get("OS"))
                    placements.append(Placement(
                        channel        = first,
                        campaign_name  = section,
                        placement_name = f"{section} - {first} - {os_val}".strip(" -"),
                        objective      = self._str(rec.get("Optimized towards")),
                        cost_method    = self._str(rec.get("Buy Type")).upper() or "CPI",
                        unit_rate      = self._flt(rec.get("Target CPI")),
                        planned_units  = self._flt(rec.get("Estimated Installs"))
                                       or self._flt(rec.get("Installs")),
                        planned_amount = media_budget,
                        gross_amount   = gross,
                        currency       = currency,
                        flight_start   = self._str(rec.get("Start Date")),
                        flight_end     = self._str(rec.get("End Date")),
                        os             = os_val,
                        targeting      = self._str(rec.get("Targeting")),
                    ))
        return placements


# ── MI / Mercari ─────────────────────────────────────────────────────────────

class MIAdapter(BasePlanAdapter):
    client_code = "MI"
    label       = "MI / Mercari"

    def detect(self, wb) -> bool:
        for sn in wb.sheetnames:
            low = sn.lower()
            if "mercari" in low or low.startswith("mi"):
                return True
        for sn in wb.sheetnames:
            ws = wb[sn]
            for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
                joined = " ".join(self._str(c) for c in row).lower()
                if "publisher product" in joined:
                    return True
        return False

    def extract(self, wb) -> list[Placement]:
        placements: list[Placement] = []

        for sn in wb.sheetnames:
            ws = wb[sn]
            header_idx    = None
            header_values = None

            for i, row in enumerate(ws.iter_rows(min_row=1, max_row=40, values_only=True), start=1):
                joined = " ".join(self._str(c) for c in row).lower()
                if "publisher product" in joined and ("budget" in joined or "objective" in joined):
                    header_idx    = i
                    header_values = row
                    break

            if not header_idx:
                continue

            headers = [self._str(c) for c in header_values]
            col     = {h.lower(): idx for idx, h in enumerate(headers) if h}

            def g(row, *keys, default=None):
                for k in keys:
                    idx = col.get(k.lower())
                    if idx is not None and idx < len(row) and row[idx] is not None:
                        return row[idx]
                return default

            for row in ws.iter_rows(min_row=header_idx + 1, values_only=True):
                product = self._str(g(row, "Publisher Product"))
                if not product:
                    continue
                if any(kw in product.lower() for kw in ("subtotal", "total", "sum")):
                    continue

                budget = self._flt(g(row, "Budget (USD)", "Total Budget (USD)", "Budget"))
                if budget == 0:
                    continue

                placements.append(Placement(
                    channel        = product,
                    campaign_name  = sn,
                    placement_name = product,
                    objective      = self._str(g(row, "Objective")),
                    ad_format      = self._str(g(row, "Ad Format")),
                    cost_method    = "CPM",
                    planned_amount = budget,
                    currency       = "USD",
                ))
        return placements


# ── Registry ─────────────────────────────────────────────────────────────────

ALL_ADAPTERS: list[BasePlanAdapter] = [
    SkillIgnitionAdapter(),
    MCPAdapter(),
    MIAdapter(),
]
