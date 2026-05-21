"""CSV load / append with cashback_id dedup."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from config import CSV_HEADER, CSV_PATH

log = logging.getLogger(__name__)


def load_seen_ids(path: Path = CSV_PATH) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = (row.get("cashback_id") or "").strip()
            if cid:
                seen.add(cid)
    log.info("loaded %d existing cashback_ids", len(seen))
    return seen


def append_rows(rows: list[dict], path: Path = CSV_PATH) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        for r in rows:
            # ensure all keys exist
            writer.writerow({k: r.get(k, "") for k in CSV_HEADER})
    log.info("appended %d rows to %s", len(rows), path)
