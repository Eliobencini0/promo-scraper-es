"""Discovery of article URLs via sitemap and category crawl."""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import robots
from config import (
    BASE_URL, CATEGORIES, MAX_CATEGORY_PAGES, REQUEST_TIMEOUT,
    SITEMAP_INDEX_URL, USER_AGENT,
)

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": USER_AGENT}


def _get(url: str) -> str | None:
    if not robots.allowed(url):
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.text
        log.warning("GET %s -> %d", url, r.status_code)
    except requests.RequestException as e:
        log.warning("GET %s failed: %s", url, e)
    return None


def _is_article_url(url: str) -> bool:
    """Article pages end in .html or .htm and are not in /category/."""
    p = urlparse(url)
    if p.netloc and "regalosymuestrasgratis.com" not in p.netloc:
        return False
    if "/category/" in p.path:
        return False
    if p.path.endswith((".html", ".htm")):
        return True
    return False


def _parse_sitemap_locs(xml_text: str) -> list[str]:
    return re.findall(r"<loc>([^<]+)</loc>", xml_text)


def _parse_sitemap_entries(xml_text: str) -> list[tuple[str, str]]:
    """Returns list of (loc, lastmod) — lastmod may be empty."""
    entries = []
    for url_block in re.findall(r"<url>(.*?)</url>", xml_text, flags=re.DOTALL):
        loc_m = re.search(r"<loc>([^<]+)</loc>", url_block)
        lm_m = re.search(r"<lastmod>([^<]+)</lastmod>", url_block)
        if loc_m:
            entries.append((loc_m.group(1), lm_m.group(1) if lm_m else ""))
    return entries


def from_sitemap(limit_subsitemaps: int = 2, min_year: int = 2026) -> set[str]:
    """Fetch sitemap index, then the N most recent post-sitemap files.
    Filters out URLs whose <lastmod> year is < min_year.
    """
    urls: set[str] = set()
    idx_xml = _get(SITEMAP_INDEX_URL)
    if not idx_xml:
        return urls
    sub_sitemaps = [u for u in _parse_sitemap_locs(idx_xml) if "post-sitemap" in u]
    for sm in sub_sitemaps[:limit_subsitemaps]:
        body = _get(sm)
        if not body:
            continue
        for loc, lastmod in _parse_sitemap_entries(body):
            if not _is_article_url(loc):
                continue
            if lastmod:
                m = re.match(r"(\d{4})", lastmod)
                if m and int(m.group(1)) < min_year:
                    continue
            urls.add(loc)
    log.info("sitemap: %d article URLs (year>=%d)", len(urls), min_year)
    return urls


def from_category(cat_slug: str, cat_url: str) -> list[str]:
    found: list[str] = []
    for page in range(1, MAX_CATEGORY_PAGES + 1):
        url = cat_url if page == 1 else f"{cat_url.rstrip('/')}/page/{page}/"
        html = _get(url)
        if not html:
            break
        soup = BeautifulSoup(html, "lxml")
        page_urls: list[str] = []
        # Heuristic: anchors inside h2/h3 of article listings on WordPress themes
        for a in soup.select("h2 a, h3 a, article a"):
            href = a.get("href")
            if href and _is_article_url(href):
                page_urls.append(href)
        if not page_urls:
            break
        # stop if page didn't add anything new compared to known
        new = [u for u in page_urls if u not in found]
        if not new:
            break
        found.extend(new)
    log.info("category %s: %d URLs", cat_slug, len(found))
    return found


def collect_article_urls() -> dict[str, str]:
    """Returns {url: category_slug}. Category from first source that found it."""
    result: dict[str, str] = {}

    # Sitemap first — no category info, marked as "sitemap"
    for u in from_sitemap():
        result.setdefault(u, "sitemap")

    # Category crawl — overrides "sitemap" with real category
    for slug, cat_url in CATEGORIES.items():
        for u in from_category(slug, cat_url):
            # prefer real category over "sitemap"
            if u not in result or result[u] == "sitemap":
                result[u] = slug

    log.info("total unique article URLs: %d", len(result))
    return result
