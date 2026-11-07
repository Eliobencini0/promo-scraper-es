"""Constants and configuration."""
from pathlib import Path

BASE_URL = "https://regalosymuestrasgratis.com"
SITEMAP_INDEX_URL = f"{BASE_URL}/sitemap.xml"

USER_AGENT = "promo-scraper-es/0.1 (+https://github.com/Eliobencini0/promo-scraper-es)"
REQUEST_TIMEOUT = 20
RATE_LIMIT_SECONDS = 1.0

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
RUNS_DIR = DATA_DIR / "runs"
CSV_PATH = DATA_DIR / "cashbacks.csv"
XLSX_PATH = DATA_DIR / "cashbacks.xlsx"

# 9 in-scope categories (slug -> URL)
CATEGORIES = {
    "pruebalo-gratis-activos": f"{BASE_URL}/category/pruebalo-gratis-activos",
    "probar-productos-gratis": f"{BASE_URL}/category/probar-productos-gratis",
    "testers": f"{BASE_URL}/category/testers",
    "cosas-gratis-internet": f"{BASE_URL}/category/cosas-gratis-internet",
    "sorteos-activos-listado": f"{BASE_URL}/listado-de-sorteos-activos-actualizado-diariamente.htm",
    "sorteos-gratis-activos": f"{BASE_URL}/category/sorteos-gratis-activos",
    "cupones-de-descuento": f"{BASE_URL}/category/cupones-de-descuento",
    "promociones": f"{BASE_URL}/category/promociones",
    "canastillas-para-bebes": f"{BASE_URL}/category/canastillas-para-bebes",
}

MAX_CATEGORY_PAGES = 20  # safety cap for paginated category crawl

# CSV header — exact order requested + technical columns at end
CSV_HEADER = [
    "cashback_id",
    "title",
    "brand",
    "description",
    "where_to_buy",
    "validity",
    "reimbursement",
    "claim_method",
    "physical_stores",
    "channel",
    "image",
    "[extra] categoria",
    "[extra] mecanica_full",
    "[extra] passo_1_acquisto",
    "[extra] passo_2_documenti",
    "[extra] passo_3_verifica",
    "[extra] passo_4_registrazione",
    "[extra] passo_5_erogazione",
    "[extra] canali_esclusi",
    "[extra] form_registrazione_url",
    "[extra] bases_legales_url",
    "[extra] contatto_promo",
    "[extra] conviene_se",
    "[extra] attenzione_se",
    "_source_url",
    "_scraped_at",
    "_confidence",
    "validity_end_date",
]
