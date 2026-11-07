# Architecture

A single-process Python CLI. No database, no server: state lives in files under `data/` (git-ignored).

## Modules

| File | Responsibility | Reads | Produces |
|---|---|---|---|
| `scraper.py` | CLI entry point. `process_one()` runs the per-article pipeline; `main()` handles the modes (`--url`, full run, `--count-only`, `--from-queue`) and the pause between articles | all modules | log file, rows |
| `config.py` | Source URL, the 9 category URLs, user agent, timeout, rate limit, file paths, the output column order | | constants |
| `robots.py` | `allowed(url)`: robots.txt check cached per origin. Used by every fetch | robots.txt of each site | True / False |
| `discovery.py` | Finds article URLs: the two latest post sitemaps (filtered by `lastmod` year) and the category pages (paginated, up to 20 pages) | source site | `{url: category}` |
| `article_parser.py` | Parses one article into an `Article` (title, brand, description, validity text, links to "Participar" and "bases legales", flags `disabled` and `social_only`, published year) | article HTML | `Article` |
| `validity.py` | Parses Spanish validity text into an end date. Trusts only dates near validity keywords; "indefinido"-type phrases mean not active | `Article.validity_raw` | `Validity(date_end, text, confident)` |
| `landing_parser.py` | Opens the brand's "Participar" page and legal terms. Playwright (Chromium) for JavaScript pages, `requests` + `pypdf` for PDFs; rejects cookie banners; splits legal text into numbered sections | brand sites | `Landing`, `BasesLegales` |
| `extractor.py` | `build_row()`: turns the article, landing and legal text into one output row, one rule per field, with a `_confidence` list | the three objects above | dict |
| `cache.py` | `data/seen_cache.json` (what was judged expired, disabled, old or without date, trusted 30 days) and `data/active_queue.json` (survivors of `--count-only`) | | JSON files |
| `io_xlsx.py` | Loads existing `cashbacks.xlsx` ids for deduplication and appends rows | | `data/cashbacks.xlsx` |
| `io_sheets.py` | Optional append to a Google Sheet (gspread, service account) | env `SHEET_ID` | Sheet rows |
| `io_csv.py` | Same idea for CSV. Not used by `scraper.py` today | | |

## Per-article decisions (`scraper.process_one`)

1. Fetch and parse the article. No page → skip.
2. `disabled` (the blog marked it as no longer available) → skip.
3. `social_only` (the participation link is Instagram, Facebook, TikTok, X, …) → skip.
4. `published_year < 2026` → skip.
5. No confident end date in the future → skip.
6. If there is a "Participar" link: open the brand page and, in the same browser session, the legal terms (HTML). If the legal terms are a PDF they are read separately. Without a "Participar" link, only the legal terms are fetched.
7. `build_row()`.

Every network step goes through `robots.allowed()`. A refusal behaves like a failed fetch: the field stays empty.

## State and side effects

- `data/cashbacks.xlsx`: the output and also the deduplication memory (`cashback_id`).
- `data/seen_cache.json`: classification of already-seen URLs. Terminal statuses (disabled, old, no date, expired) are trusted for 30 days; `active` is never skipped.
- `data/active_queue.json`: handoff between `--count-only` and `--from-queue`.
- `data/runs/`: one log per day, plus debug dumps with `--debug`.
- `~/Downloads`: after a run, `cashbacks.xlsx` and `cashbacks.csv` are copied there if they exist (`scraper._copy_to_downloads`).

## Failure behavior

- An exception while processing one article is logged and counted in `errors`; the run continues.
- A missing Playwright install, a blocked page or a timeout leaves landing data empty; the row is still built from what is available, and the affected fields are listed in `_confidence`.
- Nothing retries automatically. A weekly run is repeated by hand.
