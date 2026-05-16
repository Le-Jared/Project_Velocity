"""
Plan parser — detects the media plan template and extracts normalized placements.
Mirrors the role of invoice_extractor.py for the Prisma pipeline.
"""
from __future__ import annotations
from pathlib import Path

import openpyxl

from plan_adapters import ALL_ADAPTERS, BasePlanAdapter, Placement
from gemini_fallback_prisma import enrich_placements, is_available as gemini_available


def parse_plan(path: Path | str) -> tuple[BasePlanAdapter, list[Placement]]:
    """
    Auto-detect plan format and extract placements.
    Gemini enrichment is applied after extraction to fill any blank fields
    (dates, currency, objective) that the adapter could not read directly.
    Returns (adapter, placements). Raises ValueError if no adapter matches.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Plan not found: {path}")

    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        for adapter in ALL_ADAPTERS:
            try:
                if adapter.detect(wb):
                    placements = adapter.extract(wb)

                    # ── Gemini enrichment ──────────────────────────────
                    # Fills blank fields (flight dates, currency, objective,
                    # cost_method) using the plan context as a hint.
                    # Skipped silently if GEMINI_API_KEY is not set.
                    if gemini_available():
                        print(f"  [GEMINI] Enriching placements for {adapter.label}...")
                        placements = enrich_placements(
                            placements,
                            plan_label=adapter.label,
                        )
                    # ──────────────────────────────────────────────────

                    return adapter, placements

            except Exception as e:
                # Bad adapter shouldn't kill the whole detection loop
                print(f"[WARN] Adapter {adapter.label} raised {type(e).__name__}: {e}")
                continue

        raise ValueError(
            f"No adapter recognised the media plan: {path.name}. "
            f"Tried: {', '.join(a.label for a in ALL_ADAPTERS)}"
        )
    finally:
        wb.close()


def detect_client(path: Path | str) -> str | None:
    """
    Lightweight client detection without full extraction.
    Used by /api/prisma/plans to show client tag in the list.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception:
        return None
    try:
        for adapter in ALL_ADAPTERS:
            try:
                if adapter.detect(wb):
                    return adapter.client_code
            except Exception:
                continue
    finally:
        wb.close()
    return None