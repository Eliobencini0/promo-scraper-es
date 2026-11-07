> Original Italian notes from May 2026, kept for history. Where they differ from the main [README](../README.md) the main README wins: the run writes `data/cashbacks.xlsx` (not CSV), and the browser session no longer masks automation or skips robots.txt.

# promo-scraper-es

Scraper settimanale per concorsi/cashback/promo brand attivi in Spagna da [regalosymuestrasgratis.com](https://regalosymuestrasgratis.com).

## Setup

```bash
cd ~/Projects/promo-scraper-es
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Uso

### Smoke test su un singolo URL (dry-run, niente scrittura CSV)
```bash
python scraper.py --url https://regalosymuestrasgratis.com/buitoni-sortea-8-proyectores-prixton-wifi-renoir.html --dry-run
```

### Run completo (settimanale)
```bash
python scraper.py
```
- Carica i `cashback_id` esistenti dal CSV → dedup automatico.
- Discovery via sitemap + crawl delle 9 categorie.
- Per ogni nuovo articolo: parsing + validity check (skip se scaduto) + fetch landing Participar (Playwright) + fetch bases legales.
- Append su `data/cashbacks.csv`.
- Log in `data/runs/YYYY-MM-DD.log`.

### Limitare il numero di articoli (debug)
```bash
python scraper.py --limit 5
```

### Push opzionale su Google Sheets
```bash
export SHEET_ID=...               # ID del foglio
export SHEET_TAB="Sheet1"
# service account JSON in ~/.config/promo-scraper-es/sa.json
python scraper.py --push-sheets
```

## Output

`data/cashbacks.csv` — colonne nell'ordine richiesto + colonne tecniche:
- `_source_url`, `_scraped_at`, `_confidence` (lista comma-separated di campi a bassa confidenza).

## Anti-allucinazione

- Tutti i campi derivano da selettori CSS / regex espliciti sulla pagina sorgente.
- Quando un campo non è estraibile con certezza → vuoto + flag in `_confidence`.
- `conviene_se` e `attenzione_se` sono **sempre vuoti** (editoriali, mai inventati).
- `image` solo da `og:image` della landing Participar; nessun fallback.
- Concorsi con data finale < oggi → skippati.

## Note

- Cadenza consigliata: 1 run/settimana, manuale.
- Lo script rispetta un rate limit di ~1 req/s con jitter.
- User-Agent identificativo: `promo-scraper-es/0.1`.
