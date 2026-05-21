"""CLI entrypoint: discover, parse, dedup, append CSV, optional Google Sheets push."""
from __future__ import annotations

import argparse
import logging
import random
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path

import article_parser
import cache
import discovery
import extractor
import io_xlsx
import io_sheets
import landing_parser
import validity as validity_mod
from config import RATE_LIMIT_SECONDS, RUNS_DIR, XLSX_PATH
from extractor import url_to_cashback_id


def setup_logging() -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RUNS_DIR / f"{date.today().isoformat()}.log"
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers = [logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers, force=True)
    return log_path


def _copy_to_downloads() -> None:
    dl = Path.home() / "Downloads"
    if not dl.exists():
        return
    log = logging.getLogger("downloads")
    for name in ("cashbacks.xlsx", "cashbacks.csv"):
        src = Path(__file__).resolve().parent / "data" / name
        if src.exists():
            dst = dl / name
            try:
                shutil.copy2(src, dst)
                log.info("copied %s -> %s", src.name, dst)
            except Exception as e:
                log.warning("copy failed for %s: %s", src, e)


def _debug_dump(name: str, content: str) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    p = RUNS_DIR / f"debug_{name}.txt"
    p.write_text(content or "", encoding="utf-8")
    logging.getLogger("debug").info("dumped %s (%d chars) -> %s", name, len(content or ""), p)


def process_one(url: str, categoria_slug: str, debug: bool = False, headed: bool = False) -> dict | None:
    log = logging.getLogger("process")
    log.info("→ %s", url)
    art = article_parser.parse(url)
    if not art:
        log.warning("could not fetch %s", url)
        return None

    # Filter: editor-flagged as no longer available
    if art.disabled:
        log.info("   skip — disabled: %s", art.disabled_reason[:120])
        return None

    # Filter: contest hosted on social only (Instagram/FB/TikTok/X/...)
    if art.social_only:
        log.info("   skip — social-only contest (Instagram/FB/TikTok/...)")
        return None

    # Filter: article must be published in 2026 or later
    if art.published_year is not None and art.published_year < 2026:
        log.info("   skip — published in %d (< 2026)", art.published_year)
        return None

    v = validity_mod.parse_validity(art.validity_raw)
    if not validity_mod.is_active(v):
        log.info("   skip — no clear future end-date (date_end=%s)", v.date_end)
        return None

    landing = None
    bases = None
    if art.participar_url:
        landing, bases = landing_parser.fetch_brand_session(
            art.participar_url,
            art.bases_legales_url or None,
            headed=headed,
        )
        if debug and landing:
            _debug_dump("landing_text", landing.text)
            _debug_dump("landing_html", landing.html)
            log.info("landing image=%r", landing.image)
        if debug and bases:
            _debug_dump("bases_text", bases.text)
            from landing_parser import parse_sections
            secs = parse_sections(bases.text)
            log.info("parsed %d sections: %s", len(secs), list(secs.keys()))
    elif art.bases_legales_url:
        # No participar URL, fetch bases standalone (PDF or static)
        bases = landing_parser.fetch_bases_legales(art.bases_legales_url)

    row = extractor.build_row(art, v, landing, bases, categoria_slug)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="Process a single URL (smoke test)")
    ap.add_argument("--dry-run", action="store_true", help="Do not write CSV")
    ap.add_argument("--push-sheets", action="store_true", help="Push to Google Sheets")
    ap.add_argument("--limit", type=int, default=0, help="Cap number of new articles to process")
    ap.add_argument("--debug", action="store_true", help="Dump intermediate texts to data/runs/")
    ap.add_argument("--headed", action="store_true", help="Run Playwright with visible Chromium (helps bypass Akamai/anti-bot)")
    ap.add_argument("--count-only", action="store_true", help="Discover + apply filters (no Playwright). Print counts and exit.")
    ap.add_argument("--from-queue", action="store_true", help="Skip discovery; scrape only URLs saved by a previous --count-only (data/active_queue.json).")
    ap.add_argument("--no-cache", action="store_true", help="Ignore seen_cache.json (force re-check of every URL).")
    args = ap.parse_args()

    log_path = setup_logging()
    log = logging.getLogger("main")
    log.info("=== run start %s ===", datetime.now().isoformat(timespec="seconds"))
    log.info("log file: %s", log_path)

    seen = io_xlsx.load_seen_ids()

    if args.url:
        cid = url_to_cashback_id(args.url)
        if cid in seen and not args.dry_run:
            log.info("already in CSV: %s", cid)
            return 0
        row = process_one(args.url, "manual", debug=args.debug, headed=args.headed)
        if row is None:
            log.info("no row produced")
            return 0
        if args.dry_run:
            for k, v in row.items():
                preview = (v or "")[:140] if isinstance(v, str) else v
                print(f"{k}: {preview}")
            return 0
        io_xlsx.append_rows([row])
        _copy_to_downloads()
        if args.push_sheets:
            io_sheets.push_rows([row])
        return 0

    # full run — discovery, or from saved queue
    if args.from_queue:
        queue = cache.load_queue()
        if not queue:
            log.error("--from-queue: queue empty or missing (run --count-only first)")
            return 1
        new_urls = [(u, c) for u, c in queue if url_to_cashback_id(u) not in seen]
        log.info("from-queue: %d URLs (after dedup vs CSV)", len(new_urls))
        url_to_cat = {u: c for u, c in queue}
    else:
        url_to_cat = discovery.collect_article_urls()
        log.info("discovered %d URLs", len(url_to_cat))
        new_urls = [(u, c) for u, c in url_to_cat.items() if url_to_cashback_id(u) not in seen]
        log.info("new (not in CSV): %d", len(new_urls))

    if args.count_only:
        seen_cache = {} if args.no_cache else cache.load_seen()
        active_items: list[tuple[str, str]] = []
        active = 0
        skip_disabled = skip_old = skip_no_date = skip_expired = errors = skip_cached = 0
        for u, cat in new_urls:
            # Cheap skip via cache
            reason = cache.can_skip(seen_cache.get(u))
            if reason:
                skip_cached += 1
                if reason == "disabled":
                    skip_disabled += 1
                elif reason == "old":
                    skip_old += 1
                elif reason == "no_date":
                    skip_no_date += 1
                elif reason == "expired":
                    skip_expired += 1
                continue
            try:
                art = article_parser.parse(u)
            except Exception:
                errors += 1
                continue
            if art is None:
                errors += 1
                continue
            if art.disabled:
                skip_disabled += 1
                cache.record(seen_cache, u, "disabled")
                continue
            if art.social_only:
                skip_disabled += 1
                cache.record(seen_cache, u, "disabled")
                continue
            if art.published_year is not None and art.published_year < 2026:
                skip_old += 1
                cache.record(seen_cache, u, "old", published_year=art.published_year)
                continue
            v = validity_mod.parse_validity(art.validity_raw)
            if v.date_end is None:
                skip_no_date += 1
                cache.record(seen_cache, u, "no_date")
                continue
            if not validity_mod.is_active(v):
                skip_expired += 1
                cache.record(seen_cache, u, "expired", date_end=v.date_end.isoformat())
                continue
            active += 1
            cache.record(seen_cache, u, "active", date_end=v.date_end.isoformat())
            active_items.append((u, cat))
            log.info("KEEP %s | end=%s", url_to_cashback_id(u), v.date_end)
        cache.save_seen(seen_cache)
        cache.save_queue(active_items)
        log.info(
            "COUNT discovered=%d new=%d active=%d "
            "skip_disabled=%d skip_old=%d skip_no_date=%d skip_expired=%d "
            "skip_cached=%d errors=%d",
            len(url_to_cat), len(new_urls), active,
            skip_disabled, skip_old, skip_no_date, skip_expired,
            skip_cached, errors,
        )
        print(f"\n=> {active} offerte attive salvate in data/active_queue.json — usa --from-queue per scaricarle.\n")
        return 0

    rows: list[dict] = []
    skipped_expired = 0
    errors = 0
    processed = 0
    for u, cat in new_urls:
        if args.limit and len(rows) >= args.limit:
            break
        processed += 1
        try:
            row = process_one(u, cat, headed=args.headed)
            if row is None:
                skipped_expired += 1
            else:
                rows.append(row)
        except Exception as e:
            errors += 1
            log.exception("error processing %s: %s", u, e)
        time.sleep(RATE_LIMIT_SECONDS + random.uniform(0, 0.5))

    log.info(
        "summary: discovered=%d new=%d processed=%d kept=%d skipped=%d errors=%d",
        len(url_to_cat), len(new_urls), processed, len(rows), skipped_expired, errors,
    )

    if args.dry_run:
        log.info("dry-run: not writing CSV")
        return 0

    io_xlsx.append_rows(rows)
    log.info("XLSX: %s", XLSX_PATH)
    _copy_to_downloads()

    if args.push_sheets:
        io_sheets.push_rows(rows)

    return 0


if __name__ == "__main__":
    sys.exit(main())
