"""XLSX load / append with cashback_id dedup."""
from __future__ import annotations

import logging
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

from config import CSV_HEADER, XLSX_PATH

log = logging.getLogger(__name__)

SHEET_NAME = "cashbacks"

# Per-column widths (chars). Wide for long-text fields.
_WIDE_COLS = {
    "title", "description", "where_to_buy", "reimbursement", "claim_method",
    "[extra] mecanica_full",
    "[extra] passo_1_acquisto", "[extra] passo_2_documenti",
    "[extra] passo_3_verifica", "[extra] passo_4_registrazione",
    "[extra] passo_5_erogazione",
    "[extra] canali_esclusi", "channel", "image",
    "[extra] form_registrazione_url", "[extra] bases_legales_url",
    "_source_url",
}


def _open_or_create(path: Path) -> Workbook:
    if path.exists():
        return load_workbook(path)
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append(CSV_HEADER)
    # column widths
    for idx, col in enumerate(CSV_HEADER, start=1):
        width = 60 if col in _WIDE_COLS else 22
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"
    return wb


def load_seen_ids(path: Path = XLSX_PATH) -> set[str]:
    if not path.exists():
        return set()
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[SHEET_NAME] if SHEET_NAME in wb.sheetnames else wb.active
    seen: set[str] = set()
    # Skip header row
    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
        cid = row[0]
        if cid:
            seen.add(str(cid).strip())
    log.info("loaded %d existing cashback_ids from %s", len(seen), path.name)
    return seen


def append_rows(rows: list[dict], path: Path = XLSX_PATH) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = _open_or_create(path)
    ws = wb[SHEET_NAME] if SHEET_NAME in wb.sheetnames else wb.active
    for r in rows:
        ws.append([r.get(col, "") for col in CSV_HEADER])
    wb.save(path)
    log.info("appended %d rows to %s", len(rows), path)
