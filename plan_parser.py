"""
Plan parser — detects the media plan template and extracts normalized placements.
Mirrors the role of invoice_extractor.py for the Prisma pipeline.
"""
from __future__ import annotations
from pathlib import Path

import openpyxl

from plan_adapters import ALL_ADAPTERS, BasePlanAdapter, Placement


def parse_plan(path: Path | str) -> tuple[BasePlanAdapter, list[Placement]]:
    """
    Auto-detect plan format and extract placements.
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
