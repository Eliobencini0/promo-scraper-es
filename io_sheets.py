"""Optional push to Google Sheets via gspread."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from config import CSV_HEADER

log = logging.getLogger(__name__)


def push_rows(rows: list[dict]) -> None:
    if not rows:
        return
    sheet_id = os.environ.get("SHEET_ID")
    sheet_tab = os.environ.get("SHEET_TAB", "Sheet1")
    sa_path = Path(os.environ.get(
        "SHEETS_SA_JSON",
        str(Path.home() / ".config/promo-scraper-es/sa.json"),
    ))
    if not sheet_id:
        log.warning("SHEET_ID not set; skipping sheets push")
        return
    if not sa_path.exists():
        log.warning("service account JSON not found at %s; skipping", sa_path)
        return

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        log.warning("gspread / google-auth not installed; skipping sheets push")
        return

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(str(sa_path), scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(sheet_tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(sheet_tab, rows=1000, cols=len(CSV_HEADER))
        ws.append_row(CSV_HEADER)

    # dedup against existing cashback_ids in the sheet
    existing = ws.col_values(1)[1:]  # skip header
    existing_set = set(existing)
    to_append = [
        [r.get(col, "") for col in CSV_HEADER]
        for r in rows
        if r.get("cashback_id") and r["cashback_id"] not in existing_set
    ]
    if to_append:
        ws.append_rows(to_append, value_input_option="RAW")
        log.info("pushed %d new rows to Google Sheet", len(to_append))
    else:
        log.info("no new rows to push to Google Sheet")
