"""Persistent caches: seen-classification + active-queue."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from config import DATA_DIR

SEEN_PATH = DATA_DIR / "seen_cache.json"
QUEUE_PATH = DATA_DIR / "active_queue.json"

# How long a classification ("expired"/"disabled"/"old") stays trusted before we re-check.
STALE_AFTER_DAYS = 30

log = logging.getLogger("cache")


def _load(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("cache read failed %s: %s", p, e)
        return {}


def _save(p: Path, data) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- seen cache ----------

def load_seen() -> dict[str, dict]:
    return _load(SEEN_PATH)


def save_seen(seen: dict[str, dict]) -> None:
    _save(SEEN_PATH, seen)


def can_skip(entry: dict | None) -> str | None:
    """Return a skip-reason string if the cached entry is still trusted as terminal, else None."""
    if not entry:
        return None
    checked = entry.get("checked_at")
    if not checked:
        return None
    try:
        d = datetime.fromisoformat(checked).date()
    except Exception:
        return None
    if (date.today() - d) > timedelta(days=STALE_AFTER_DAYS):
        return None
    status = entry.get("status")
    # Terminal statuses we trust within the staleness window
    if status in ("disabled", "old", "no_date"):
        return status
    if status == "expired":
        end = entry.get("date_end")
        # Still expired? trust it.
        if end and end < date.today().isoformat():
            return "expired"
    return None


def record(seen: dict, url: str, status: str, **extra) -> None:
    seen[url] = {"status": status, "checked_at": date.today().isoformat(), **extra}


# ---------- active queue ----------

def save_queue(items: Iterable[tuple[str, str]]) -> None:
    """Persist [(url, categoria_slug), ...] of active offers ready to scrape."""
    _save(QUEUE_PATH, [{"url": u, "categoria": c} for u, c in items])


def load_queue() -> list[tuple[str, str]]:
    raw = _load(QUEUE_PATH)
    if not isinstance(raw, list):
        return []
    return [(d["url"], d.get("categoria", "manual")) for d in raw if isinstance(d, dict) and d.get("url")]


def clear_queue() -> None:
    if QUEUE_PATH.exists():
        QUEUE_PATH.unlink()
