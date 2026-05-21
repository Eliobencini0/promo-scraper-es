"""Fetch & extract data from 'Participar' landings and 'bases legales' pages/PDFs."""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, USER_AGENT

REALISTIC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

log = logging.getLogger(__name__)


@dataclass
class Landing:
    url: str
    image: str = ""
    text: str = ""
    html: str = ""


@dataclass
class BasesLegales:
    url: str
    text: str = ""
    is_pdf: bool = False


def _headers() -> dict:
    return {"User-Agent": USER_AGENT}


# Selectors / texts that commonly identify cookie reject/close buttons
_COOKIE_REJECT_SELECTORS = [
    "#onetrust-reject-all-handler",
    ".ot-pc-refuse-all-handler",
    "button#rejectAll",
    "button[aria-label*='Rechazar' i]",
    "button[aria-label*='Reject' i]",
]
_COOKIE_REJECT_TEXTS = ["rechazar", "rechazar todas", "reject all", "no, gracias", "solo necesarias"]


def _try_dismiss_cookies(page) -> None:
    for sel in _COOKIE_REJECT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=2000)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass
    for txt in _COOKIE_REJECT_TEXTS:
        try:
            loc = page.get_by_role("button", name=re.compile(txt, re.I)).first
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=2000)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass


def fetch_brand_session(
    participar_url: str,
    bases_url: str | None,
    *,
    headed: bool = False,
    block_images: bool = False,
) -> tuple[Landing | None, "BasesLegales | None"]:
    """Open ONE Playwright session, do warm-up on the brand domain, then fetch
    participar landing and (optional) bases legales pages within the same context
    so cookies/session are shared. Returns (landing, bases). Either can be None if
    fetch failed.

    The bases URL is only handled here if it's NOT a PDF (PDFs go via requests/pypdf).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("playwright not installed")
        return None, None

    landing: Landing | None = None
    bases: BasesLegales | None = None
    bases_is_html = bool(bases_url) and not bases_url.lower().endswith(".pdf")

    # If bases is a PDF, handle it outside the browser session
    bases_pdf: BasesLegales | None = None
    if bases_url and not bases_is_html:
        bases_pdf = fetch_bases_legales(bases_url)

    target_host = urlparse(participar_url).hostname or ""
    warmup_url = f"https://{target_host}/" if target_host else None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed)
            ctx = browser.new_context(
                user_agent=REALISTIC_UA,
                locale="es-ES",
                timezone_id="Europe/Madrid",
                viewport={"width": 1366, "height": 800},
                extra_http_headers={"Accept-Language": "es-ES,es;q=0.9"},
            )
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                "Object.defineProperty(navigator,'languages',{get:()=>['es-ES','es']});"
                "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
            )

            def route(r):
                rt = r.request.resource_type
                if rt in {"font", "media"} or (block_images and rt == "image"):
                    return r.abort()
                return r.continue_()

            ctx.route("**/*", route)

            page = ctx.new_page()
            try:
                try:
                    from playwright_stealth import Stealth
                    Stealth().apply_stealth_sync(page)
                except ImportError:
                    try:
                        from playwright_stealth import stealth_sync
                        stealth_sync(page)
                    except ImportError:
                        pass
            except Exception as e:
                log.warning("stealth apply failed: %s", e)

            page.set_default_timeout(30_000)

            # ---- Warm-up: visit brand home, accept cookies, idle a bit ----
            if warmup_url:
                try:
                    log.info("warm-up: %s", warmup_url)
                    page.goto(warmup_url, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    _try_dismiss_cookies(page)
                    page.wait_for_timeout(1500)
                    # Light human-ish interaction
                    try:
                        page.mouse.move(400, 300)
                        page.mouse.wheel(0, 600)
                        page.wait_for_timeout(800)
                    except Exception:
                        pass
                except Exception as e:
                    log.warning("warm-up failed: %s", e)

            # ---- Landing ----
            try:
                log.info("landing goto: %s", participar_url)
                try:
                    page.goto(participar_url, wait_until="networkidle")
                except Exception:
                    page.goto(participar_url, wait_until="domcontentloaded")
                _try_dismiss_cookies(page)
                page.wait_for_timeout(1500)
                html = page.content()
                final = page.url
                landing = Landing(url=participar_url, html=html)
                landing.image = _extract_image(html, final)
                soup = BeautifulSoup(html, "lxml")
                landing.text = soup.get_text("\n", strip=True)[:20_000]
            except Exception as e:
                log.warning("landing failed: %s", e)

            # ---- Bases legales (HTML in same session) ----
            if bases_url and bases_is_html:
                try:
                    log.info("bases goto: %s", bases_url)
                    try:
                        page.goto(bases_url, wait_until="networkidle")
                    except Exception:
                        page.goto(bases_url, wait_until="domcontentloaded")
                    _try_dismiss_cookies(page)
                    page.wait_for_timeout(1500)
                    html = page.content()
                    soup = BeautifulSoup(html, "lxml")
                    for tag in soup.select("script, style, nav, footer, header"):
                        tag.decompose()
                    bases = BasesLegales(url=bases_url, text=soup.get_text("\n", strip=True))
                except Exception as e:
                    log.warning("bases failed: %s", e)

            browser.close()
    except Exception as e:
        log.warning("playwright session error: %s", e)

    return landing, (bases or bases_pdf)


def _render(url: str, *, block_images: bool = False) -> tuple[str, str] | None:
    """Render page with Playwright. Returns (html, final_url) or None."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("playwright not installed")
        return None
    realistic_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=realistic_ua,
                locale="es-ES",
                timezone_id="Europe/Madrid",
                viewport={"width": 1366, "height": 800},
                extra_http_headers={"Accept-Language": "es-ES,es;q=0.9"},
            )
            # Hide webdriver flag — Akamai/Cloudflare check this
            ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                "Object.defineProperty(navigator, 'languages', {get: () => ['es-ES','es']});"
                "Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});"
            )

            def route(r):
                rt = r.request.resource_type
                if rt in {"font", "media"} or (block_images and rt == "image"):
                    return r.abort()
                return r.continue_()

            ctx.route("**/*", route)
            page = ctx.new_page()
            # Stealth v2: Stealth().apply_stealth_sync(page). v1: stealth_sync(page).
            try:
                try:
                    from playwright_stealth import Stealth  # v2
                    Stealth().apply_stealth_sync(page)
                except ImportError:
                    from playwright_stealth import stealth_sync  # v1
                    stealth_sync(page)
            except ImportError:
                log.warning("playwright-stealth not installed; running without stealth")
            except Exception as e:
                log.warning("stealth apply failed: %s", e)
            page.set_default_timeout(25_000)
            try:
                page.goto(url, wait_until="networkidle")
            except Exception:
                try:
                    page.goto(url, wait_until="domcontentloaded")
                except Exception as e:
                    log.warning("playwright goto %s failed: %s", url, e)
                    browser.close()
                    return None
            _try_dismiss_cookies(page)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            html = page.content()
            final = page.url
            browser.close()
            return html, final
    except Exception as e:
        log.warning("playwright error for %s: %s", url, e)
        return None


_IMAGE_BLOCKLIST = (
    "cookielaw.org", "cookiebot.com", "onetrust.com", "trustarc.com",
    "googletagmanager.com", "google-analytics.com", "doubleclick.net",
    "facebook.com/tr", "facebook.net", "/pixel", "/tracker", "/beacon",
    "/sprite", "/icons/", "favicon",
    # social icons / small UI assets
    "/ico_", "ico_fb", "ico_tw", "ico_ig", "ico_yt", "ico_in",
    "icon_fb", "icon_tw", "icon_ig", "icon_yt", "icon_in",
    "logo_fb", "logo_tw", "logo_ig", "powered_by",
    "/share-", "/social-", "social_icon", "social-icon",
)


def _is_blocked_image(src: str) -> bool:
    s = (src or "").lower()
    if any(b in s for b in _IMAGE_BLOCKLIST):
        return True
    # Reject bare-host URLs ("https://host/" or "https://host"): no real image path
    try:
        from urllib.parse import urlparse
        u = urlparse(s)
        if u.scheme and u.netloc and u.path in ("", "/"):
            return True
    except Exception:
        pass
    return False


def _extract_image(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    # 1) og:image
    for prop in ("og:image", "og:image:secure_url"):
        tag = soup.find("meta", {"property": prop})
        if tag and tag.get("content"):
            url = urljoin(base_url, tag["content"].strip())
            if not _is_blocked_image(url):
                return url
    # 2) twitter:image
    tw = soup.find("meta", {"name": "twitter:image"})
    if tw and tw.get("content"):
        url = urljoin(base_url, tw["content"].strip())
        if not _is_blocked_image(url):
            return url
    # 3) significant <img> inside main/article/header
    containers = soup.select("main, article, header, body")
    seen: set[str] = set()
    for c in containers:
        for img in c.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src or src.startswith("data:"):
                continue
            if _is_blocked_image(src):
                continue
            if src in seen:
                continue
            seen.add(src)
            cls = " ".join(img.get("class") or []).lower()
            try:
                w = int(img.get("width") or 0)
            except ValueError:
                w = 0
            keywords = ("banner", "hero", "media__element", "promo", "header")
            if w >= 300 or any(k in cls for k in keywords):
                return urljoin(base_url, src)
        if seen:
            for src in list(seen)[:1]:
                return urljoin(base_url, src)
    return ""


def fetch_landing_with_playwright(url: str) -> Landing:
    landing = Landing(url=url)
    res = _render(url, block_images=True)
    if not res:
        return _fetch_landing_static(url)
    html, final = res
    landing.html = html
    landing.image = _extract_image(html, final)
    soup = BeautifulSoup(html, "lxml")
    landing.text = soup.get_text("\n", strip=True)[:20_000]
    return landing


def _fetch_landing_static(url: str) -> Landing:
    landing = Landing(url=url)
    try:
        r = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return landing
        landing.html = r.text
        landing.image = _extract_image(r.text, r.url)
        soup = BeautifulSoup(r.text, "lxml")
        landing.text = soup.get_text("\n", strip=True)[:20_000]
    except requests.RequestException as e:
        log.warning("landing GET %s failed: %s", url, e)
    return landing


def _is_pdf_url(url: str, content_type: str = "") -> bool:
    if "pdf" in content_type.lower():
        return True
    return url.lower().endswith(".pdf")


def fetch_bases_legales(url: str) -> BasesLegales:
    bl = BasesLegales(url=url)
    # HEAD first to decide PDF vs HTML without downloading body
    try:
        head = requests.head(url, headers=_headers(), timeout=REQUEST_TIMEOUT, allow_redirects=True)
        ct = head.headers.get("Content-Type", "")
    except requests.RequestException:
        ct = ""

    if _is_pdf_url(url, ct):
        try:
            r = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                bl.is_pdf = True
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(r.content))
                bl.text = "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception as e:
            log.warning("pdf parse %s failed: %s", url, e)
        return bl

    # HTML: render with Playwright (many brand legal pages are JS-rendered SPAs)
    res = _render(url, block_images=True)
    if res:
        html, _ = res
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.select("script, style, nav, footer, header"):
            tag.decompose()
        bl.text = soup.get_text("\n", strip=True)
        return bl

    # Fallback to static fetch
    try:
        r = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            for tag in soup.select("script, style, nav, footer, header"):
                tag.decompose()
            bl.text = soup.get_text("\n", strip=True)
    except requests.RequestException as e:
        log.warning("bases legales GET %s failed: %s", url, e)
    return bl


# ---- Sections parser for bases legales ----

# Matches numbered headings whether on their own line OR inline before body.
# Title runs from first uppercase letter until either a newline or the first
# lowercase letter (which signals start of the section body).
_SECTION_RE = re.compile(
    r"(?:^|\n)\s*(\d{1,2})\s*[\.\-\)]?\s*"
    r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9 ,\-\(\)/]{3,120}?)"
    r"(?=\s+[a-záéíóúñ]|\s*\n|$)",
)


def parse_sections(text: str) -> dict[str, str]:
    """Returns {section_title_upper: body_text}."""
    if not text:
        return {}
    matches = list(_SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        title = m.group(2).strip().rstrip(".").upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # filter out obvious false positives (very short bodies are usually noise)
        if len(body) >= 20:
            sections[title] = body
    return sections


def find_section(sections: dict[str, str], *needles: str) -> str:
    """Return the body of the first section whose title contains any needle."""
    needles_lc = [n.lower() for n in needles]
    for title, body in sections.items():
        tl = title.lower()
        if any(n in tl for n in needles_lc):
            return body
    return ""


# legacy helpers kept for fallback in extractor

_STEP_HEADERS = [
    ("passo_1_acquisto", r"(compr[ae]|adquisici[óo]n|producto\s+promocional|requisitos\s+de\s+compra)"),
    ("passo_2_documenti", r"(ticket|comprobante|factura|documentaci[óo]n)"),
    ("passo_3_verifica", r"(verificaci[óo]n|validaci[óo]n|comprobaci[óo]n)"),
    ("passo_4_registrazione", r"(registro|inscripci[óo]n|alta|formulario)"),
    ("passo_5_erogazione", r"(entrega|pago|reembolso|env[íi]o\s+del\s+premio)"),
]


def _extract_step(text: str, pattern: str) -> str:
    if not text:
        return ""
    for chunk in re.split(r"\n\s*\n", text):
        if re.search(pattern, chunk, flags=re.IGNORECASE):
            chunk = chunk.strip()
            if 30 < len(chunk) < 800:
                return chunk
    return ""


def extract_steps(text: str) -> dict[str, str]:
    return {field: _extract_step(text, pat) for field, pat in _STEP_HEADERS}


def extract_field(text: str, patterns: list[str]) -> str:
    if not text:
        return ""
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            seg = m.group(0).strip()
            if 10 < len(seg) < 500:
                return seg
    return ""
