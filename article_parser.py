"""Parse a regalosymuestrasgratis.com article page."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)


@dataclass
class Article:
    url: str
    title: str = ""
    brand: str = ""
    description: str = ""
    body_text: str = ""              # full article text (mecanica_full source)
    validity_raw: str = ""
    participar_url: str = ""
    bases_legales_url: str = ""
    og_image: str = ""
    published_year: int | None = None
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    confidence: list[str] = field(default_factory=list)  # field names marked uncertain
    disabled: bool = False           # editor-flagged as no-longer-available
    disabled_reason: str = ""
    social_only: bool = False        # the primary CTA is on a social network


def fetch(url: str) -> str | None:
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.text
        log.warning("article GET %s -> %d", url, r.status_code)
    except requests.RequestException as e:
        log.warning("article GET %s failed: %s", url, e)
    return None


def _meta(soup: BeautifulSoup, prop: str, attr: str = "property") -> str:
    tag = soup.find("meta", {attr: prop})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return ""


_SOURCE_HOST = "regalosymuestrasgratis.com"

# Real social networks where a contest = "follow + comment" → out of scope
_PURE_SOCIAL_HOSTS = {
    "instagram.com", "facebook.com", "fb.com", "tiktok.com",
    "twitter.com", "x.com", "youtube.com", "youtu.be",
    "snapchat.com", "threads.net", "linkedin.com", "pinterest.com",
}


def _is_social_host(href: str) -> bool:
    if not href or not href.startswith("http"):
        return False
    host = (urlparse(href).hostname or "").removeprefix("www.")
    return any(host == s or host.endswith("." + s) for s in _PURE_SOCIAL_HOSTS)


def _is_brand_url(href: str) -> bool:
    """A 'brand' URL is external, not the source blog, not a social/share link."""
    if not href or not href.startswith("http"):
        return False
    parsed = urlparse(href)
    host = (parsed.hostname or "").removeprefix("www.")
    if not host:
        return False
    if host == _SOURCE_HOST or host.endswith("." + _SOURCE_HOST):
        return False
    if any(host == s or host.endswith("." + s) for s in _SOCIAL_HOSTS):
        return False
    # share/intent links — path or query reveals it even on neutral hosts
    full = href.lower()
    if any(p in full for p in _SHARE_PATH_PATTERNS):
        return False
    return True


def _find_link_by_text(soup: BeautifulSoup, *needles: str) -> str:
    needles_lc = [n.lower() for n in needles]
    for a in soup.find_all("a"):
        text = (a.get_text(" ") or "").strip().lower()
        if not text:
            continue
        if any(n in text for n in needles_lc):
            href = a.get("href") or ""
            if _is_brand_url(href):
                return href
    return ""


_SOCIAL_HOSTS = {
    # social networks
    "facebook.com", "fb.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "youtu.be", "pinterest.com", "tiktok.com",
    "wa.me", "t.me", "telegram.me", "whatsapp.com",
    "linkedin.com", "reddit.com", "snapchat.com", "threads.net",
    # share / preview / google infra
    "plus.google.com", "google.com", "googleusercontent.com",
    "blogger.com", "blogspot.com", "bp.blogspot.com",
    "gstatic.com", "ggpht.com",
    "addthis.com", "sharethis.com", "addtoany.com",
    # url shorteners / trackers commonly used for share
    "bit.ly", "tinyurl.com", "ow.ly", "buff.ly",
}

# Path patterns that mean "this is a share/intent link, not a brand link"
_SHARE_PATH_PATTERNS = (
    "/share", "/sharer", "/intent/", "share?url=", "?text=",
    "shareArticle", "/plus/share",
)


def _first_external_cta(soup: BeautifulSoup, source_host: str, exclude_url: str = "") -> str:
    """Fallback: first brand external link (rel=external/nofollow or target=_blank)
    that isn't the bases-legales link.
    """
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href == exclude_url:
            continue
        if not _is_brand_url(href):
            continue
        rel = " ".join(a.get("rel") or []).lower()
        target = (a.get("target") or "").lower()
        if "external" in rel or "nofollow" in rel or target == "_blank":
            return href
    return ""


def parse(url: str, html: str | None = None) -> Article | None:
    if html is None:
        html = fetch(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    art = Article(url=url)

    # Editor warning block — flags the promo as no longer available
    warning = soup.find("article", class_="warning") or soup.find(class_="warning")
    if warning:
        wtext = warning.get_text(" ", strip=True)
        markers = [
            "no disponibles", "no disponible",
            "ha dejado de estar accesible",
            "promoción finalizada", "promocion finalizada",
            "campaña terminada", "campana terminada", "campaña finalizada",
            "promoción agotada", "promocion agotada",
            "ya no disponible", "ya no está disponible", "ya no esta disponible",
            "stock agotado", "agotado",
        ]
        if any(m in wtext.lower() for m in markers):
            art.disabled = True
            art.disabled_reason = wtext[:300]

    # Title
    h1 = soup.find("h1")
    if h1:
        art.title = h1.get_text(" ", strip=True)
    else:
        art.title = _meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    if not art.title:
        art.confidence.append("title")

    # Main content: prefer <article>, fall back to .entry-content / .post-content
    body = (soup.find("article")
            or soup.find(class_=re.compile(r"(entry|post|article)[-_]?content"))
            or soup.find("main"))
    if body:
        # remove scripts/styles
        for tag in body.select("script, style, .sharedaddy, .jp-relatedposts, nav, footer"):
            tag.decompose()
        art.body_text = body.get_text("\n", strip=True)
    else:
        # fall back to all <p>
        art.body_text = "\n".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
        if not art.body_text:
            art.confidence.append("body")

    # Description = first non-empty paragraph from body
    paras = [p.get_text(" ", strip=True) for p in (body.find_all("p") if body else soup.find_all("p"))]
    paras = [p for p in paras if len(p) > 40]
    art.description = paras[0] if paras else ""
    if not art.description:
        art.confidence.append("description")

    # Validity raw text: search common phrases in body_text
    val_patterns = [
        r"V[áa]lida\s+hasta[^.\n]*",
        r"hasta\s+el[^.\n]*?\d{4}",
        r"Vigencia[^.\n]*",
        r"finaliza[^.\n]*?\d{4}",
        r"Tienes\s+desde[^.\n]*?\d{4}",
        r"\bdel\s+\d{1,2}[^.\n]*?\d{4}\b",
    ]
    found_segments: list[str] = []
    for pat in val_patterns:
        for m in re.finditer(pat, art.body_text, flags=re.IGNORECASE):
            found_segments.append(m.group(0).strip())
    art.validity_raw = " | ".join(found_segments[:5])
    if not art.validity_raw:
        art.confidence.append("validity")

    # Participar / CTA link — many variants used across articles
    art.participar_url = _find_link_by_text(
        soup,
        "participar", "participa ya", "participa aquí", "participa aqui",
        "ir a la promoción", "ir a la promocion", "ir a la oferta", "ir a la web",
        "pedir reembolso", "solicitar reembolso", "solicitar muestra",
        "obtener reembolso", "obtener cupón", "obtener cupon", "obtener muestra",
        "conseguir reembolso", "conseguir muestra", "conseguir cupón", "conseguir cupon",
        "recibir muestra", "recibir cupón", "recibir cupon",
        "canjear", "canjear cupón", "canjear cupon",
        "disfrutar", "disfruta",
        "pide tu muestra", "consigue tu muestra", "consigue tu cupón", "consigue tu cupon",
        "descargar cupón", "descargar cupon", "descarga tu cupón", "descarga tu cupon",
        "reclama tu", "rellena el formulario", "rellenar formulario",
        "más información", "mas informacion", "más info", "mas info",
        "acceder", "entrar", "registrate", "regístrate", "regístrate aquí",
        "pruébalo", "pruebalo", "probar gratis", "prueba gratis",
        "apuntarse", "apúntate", "apuntate", "inscribirse",
        "comprar", "comprar ahora", "comprar aquí", "comprar aqui",
        "visita la promoción", "visita la promocion", "visita la web",
    )
    if not art.participar_url:
        art.confidence.append("channel")

    # Bases legales link
    art.bases_legales_url = _find_link_by_text(soup, "bases legales", "bases legales en este enlace")
    if not art.bases_legales_url:
        art.confidence.append("bases_legales_url")

    # If the primary CTA (anchor with CTA-like text) points to a pure social
    # network (Instagram, FB, TikTok, X, YouTube, Threads, Pinterest, LinkedIn),
    # mark the article as out-of-scope: skipped upstream.
    _cta_text_markers = (
        "participar", "participa", "pedir", "obtener", "conseguir", "consigue",
        "solicitar", "pide", "descargar", "descarga", "reclama",
        "rellena", "regístrate", "registrate", "apúntate", "apuntate",
        "más información", "mas informacion", "comprar", "visita",
        "acceder", "entrar", "ir a la", "pruébalo", "pruebalo",
    )
    for a in (body or soup).find_all("a", href=True):
        text = (a.get_text(" ") or "").strip().lower()
        if not text:
            continue
        if any(m in text for m in _cta_text_markers):
            if _is_social_host(a["href"]):
                art.social_only = True
                break

    # Channel fallback — first external CTA-like link (excluding bases legales & socials)
    if not art.participar_url:
        art.participar_url = _first_external_cta(
            body or soup, _SOURCE_HOST, exclude_url=art.bases_legales_url,
        )
    # Last-resort: use bases_legales URL as channel (always a brand URL when present)
    if not art.participar_url and _is_brand_url(art.bases_legales_url):
        art.participar_url = art.bases_legales_url
    if art.participar_url and "channel" in art.confidence:
        art.confidence.remove("channel")

    # og:image of the article (used only for confidence reasoning, NOT as image fallback)
    art.og_image = _meta(soup, "og:image")

    # Published date — from meta tags or <time datetime="...">
    pub = (
        _meta(soup, "article:published_time")
        or _meta(soup, "og:article:published_time")
        or _meta(soup, "datePublished", attr="itemprop")
    )
    if not pub:
        t = soup.find("time", attrs={"datetime": True})
        if t:
            pub = t["datetime"]
    if pub:
        m = re.search(r"\b(20\d{2})\b", pub)
        if m:
            art.published_year = int(m.group(1))

    # Tags / categories from anchor links pointing to /tag/ or /category/
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if not text:
            continue
        if "/tag/" in href and text not in art.tags:
            art.tags.append(text)
        elif "/category/" in href and text not in art.categories:
            art.categories.append(text)

    # Brand inference:
    # 1) first capitalized token(s) in the H1 ("Buitoni sortea ..." -> "Buitoni")
    # 2) first tag
    # 3) hostname of participar link (last fallback)
    if art.title:
        m = re.match(r"^([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&'\.\-]*(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&'\.\-]*)?)\b", art.title)
        if m:
            candidate = m.group(1).strip()
            # avoid generic openers
            if candidate.lower() not in {"sorteo", "concurso", "gana", "consigue", "regalo", "promoción", "promocion"}:
                art.brand = candidate
    if not art.brand and art.tags:
        art.brand = art.tags[0]
    if not art.brand and art.participar_url:
        host = urlparse(art.participar_url).hostname or ""
        host = host.removeprefix("www.")
        parts = host.split(".")
        if parts:
            art.brand = parts[0]
    if not art.brand:
        art.confidence.append("brand")

    return art
