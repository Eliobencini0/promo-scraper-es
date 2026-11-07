# promo-scraper-es

A weekly scraper that turns a Spanish promotions blog into a structured dataset of **active** contests, cashback offers and brand promotions: one row per promotion, with what to buy, where, until when, how to claim, and a flag on every field the code was not sure about.

- Source: [regalosymuestrasgratis.com](https://regalosymuestrasgratis.com) (the list of promotions), then each brand's own landing page and legal terms ("bases legales") for the details.
- Output: `data/cashbacks.xlsx` (optional push to Google Sheets). The data itself is not in this repo.
- Language of the data: Spanish. Language of the code and docs: English. The original Italian notes are in [docs/README.it.md](docs/README.it.md).
- Status: single-author prototype, one commit (May 2026), run by hand once a week. No automated tests.

## The idea in one paragraph

Promotion pages are written for humans and change every week. The scraper does the boring part (find new pages, drop expired ones, open the brand's pages, pull out the fields) and refuses to do the risky part: **it never invents a value**. If a field cannot be taken from the page with a rule it can point to, the cell stays empty and the field name is written in a `_confidence` column. Two editorial columns (`conviene_se`, `attenzione_se`, "worth it if / watch out if") are always empty on purpose, because they need a human opinion.

## How a run works

```
sitemap + 9 categories (up to 20 pages each)     discovery.py
        │  article URLs, deduplicated
        ▼
skip what is already in data/cashbacks.xlsx      io_xlsx.py   (key: cashback_id)
skip what was judged dead in the last 30 days    cache.py     (data/seen_cache.json)
        │
        ▼  for each new article                  article_parser.py
   filters, in this order:
     1. flagged by the editor as no longer available   → skip
     2. contest that lives only on social networks      → skip
     3. published before 2026                           → skip
     4. no confident end date, or end date in the past  → skip   (validity.py)
        │
        ▼
brand landing page ("Participar") + legal terms  landing_parser.py
   (Playwright for JavaScript pages, requests + pypdf for PDFs)
        │
        ▼
one row, field by field, with confidence flags   extractor.py
        │
        ▼
append to XLSX  →  optional Google Sheets        io_xlsx.py, io_sheets.py
```

A second mode splits the run in two: `--count-only` does discovery and the four filters without opening a browser and saves the survivors in `data/active_queue.json`; `--from-queue` then scrapes only those.

## Design decisions worth knowing

| Decision | Why | Where |
|---|---|---|
| Every field comes from an explicit CSS selector or regular expression; otherwise empty plus a flag in `_confidence` | A wrong "where to buy" or "how to claim" is worse than a blank | `extractor.py`, `article_parser.py` |
| The descriptive text comes from the brand's own legal terms, not from the blog | Primary source, and no copying of the blog's prose | `extractor._synthesize_mecanica` |
| The image is taken only from the brand landing page and rejected if it comes from the blog, social widgets or trackers | Avoids reusing someone else's artwork and picking up share icons | `extractor.build_row`, `landing_parser._extract_image` |
| A promotion is "active" only with a **confident** end date in the future; "no definido", "indefinido", "hasta fin de existencias" count as not active | Better to miss an open-ended promo than to show an expired one | `validity.py` |
| The two editorial columns are never filled | They are opinions | `extractor.build_row` |
| Expired, disabled and old articles are cached for 30 days | Saves hundreds of requests per weekly run | `cache.py` |
| Run by hand, once a week | The source changes slowly and the volume is small | |

## Responsible scraping

- Every request first asks `robots.txt` of that site (`robots.py`). If it cannot be read, or forbids the path, the page is skipped.
- The user agent names the project and links to this repo.
- A pause of 1 to 1.5 seconds between articles in a full run.
- No attempt to hide automation: no stealth plugins, no masking of browser properties, no fake user agent, no solving of challenges. A brand page that blocks automated browsers is not worked around: whatever cannot be extracted stays empty and flagged.
- Contact data in the output is whatever the brand publishes in its own legal terms (an email or a phone number for the promotion).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

python scraper.py --url <article-url> --dry-run     # one article, prints the row, writes nothing
python scraper.py --count-only                      # discovery and filters only, saves data/active_queue.json
python scraper.py --from-queue                      # scrape the saved queue
python scraper.py                                   # full run
```

| Flag | Effect |
|---|---|
| `--url URL` | Process a single article |
| `--dry-run` | Do not write the output file |
| `--limit N` | Stop after N rows (debugging) |
| `--count-only` / `--from-queue` | The two halves of a run (see above) |
| `--no-cache` | Ignore `data/seen_cache.json` |
| `--debug` | Dump intermediate texts to `data/runs/` |
| `--headed` | Show the browser window |
| `--push-sheets` | Also append to Google Sheets (`SHEET_ID` env var, service-account JSON at `~/.config/promo-scraper-es/sa.json`) |

Logs go to `data/runs/YYYY-MM-DD.log`. After a run the XLSX is also copied to `~/Downloads` if that folder exists.

## Known limits

- The selectors and the Spanish regular expressions depend on the source site's layout and on how brands word their legal terms. A redesign breaks extraction without any error, only more empty cells.
- Two filters are hard-coded to 2026 (`published_year < 2026` in `scraper.py`, `min_year=2026` in `discovery.py`) and need a yearly edit.
- Discovery reads only the two most recent post sitemaps plus the 9 categories (up to 20 pages each).
- `io_csv.py` is a leftover: the run writes XLSX only.
- No tests. The quickest check is `--url ... --dry-run` on a known article.

## Where to read first

1. `scraper.py`: `process_one()` is the whole per-article pipeline in 50 lines.
2. `extractor.py`: `build_row()`, where each output field gets its rule and its confidence flag.
3. `validity.py`: what "active" means.
4. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md).
