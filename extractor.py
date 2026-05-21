"""Build the final CSV row dict from Article + Landing + BasesLegales."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from article_parser import Article
from landing_parser import (
    BasesLegales, Landing, extract_field, extract_steps, find_section, parse_sections,
)
from validity import Validity


def url_to_cashback_id(url: str) -> str:
    """Stable id from URL path: e.g. 'buitoni-sortea-8-proyectores-prixton-wifi-renoir'."""
    p = urlparse(url)
    slug = p.path.lstrip("/")
    for ext in (".html", ".htm"):
        if slug.endswith(ext):
            slug = slug[: -len(ext)]
    return slug.strip("/")


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


_LEADING_NUMBERING_RE = re.compile(
    r"^\s*(?:"
    r"\d+(?:\.\d+)*\s*[\.\-–)]+\s*"   # 5.1.- / 5.1. / 5.1) / 5.- / 5)
    r"|[a-zA-Z]\s*[\.\)]\s+"           # a. / a) / A)
    r"|[•·\-–—]\s+"                    # bullets
    r")"
)


_PARA_RE = re.compile(r"\n\s*\n+")
_SINGLE_NL_RE = re.compile(r"[ \t]*\n[ \t]*")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


def _normalize_whitespace(s: str) -> str:
    """Rejoin lines broken mid-sentence (from <br>/inline spans) while keeping paragraph breaks."""
    if not s:
        return s
    # placeholder for real paragraph breaks
    s = _PARA_RE.sub("␟", s)
    # collapse remaining single newlines into spaces (these split sentences mid-flow)
    s = _SINGLE_NL_RE.sub(" ", s)
    # restore paragraph breaks
    s = s.replace("␟", "\n\n")
    s = _MULTI_SPACE_RE.sub(" ", s)
    # tidy stray space before punctuation
    s = re.sub(r"\s+([,.;:!?)])", r"\1", s)
    s = re.sub(r"([(¡¿])\s+", r"\1", s)
    return s.strip()


def _strip_leading_numbering(s: str) -> str:
    """Strip leading legal-section numbering like '5.1.-', '5.- ', 'a)' from the start."""
    if not s:
        return s
    prev = None
    out = s.lstrip()
    while out != prev:
        prev = out
        out = _LEADING_NUMBERING_RE.sub("", out, count=1).lstrip()
    return out


def _section_first_paragraph(body: str, n: int = 600) -> str:
    """First non-empty paragraph of a section body, truncated, with leading numbering stripped."""
    if not body:
        return ""
    for chunk in re.split(r"\n\s*\n", body):
        chunk = _normalize_whitespace(_strip_leading_numbering(chunk.strip()))
        if len(chunk) >= 30:
            return _truncate(chunk, n)
    return _truncate(_normalize_whitespace(_strip_leading_numbering(body)), n)


_STEP_MARKER_RE = re.compile(
    r"(?:^|\n)\s*(?:"
    r"(?:[1-9]|10)\s*[\.\)\-]"          # 1. 2) 3-
    r"|[a-eA-E]\s*\)"                    # a) b)
    r"|Paso\s+\d+\s*[:\.]"               # Paso 1:
    r"|Primero|Segundo|Tercero|Cuarto|Quinto|Despu[ée]s|Por\s+[úu]ltimo|A\s+continuaci[óo]n"
    r")\s+",
    flags=re.IGNORECASE,
)


def _split_mecanica_into_steps(text: str, max_steps: int = 5) -> list[str]:
    """Split a MECÁNICA section body into ordered sub-steps.
    Strategy: split by numeric/alphabetic step markers; fall back to paragraphs.
    """
    if not text:
        return []
    # Try marker-based split
    parts = _STEP_MARKER_RE.split(text)
    parts = [p.strip() for p in parts if p and len(p.strip()) >= 30]
    if len(parts) >= 2:
        return [_truncate(p, 500) for p in parts[:max_steps]]
    # Fallback: paragraphs
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) >= 30]
    return [_truncate(p, 500) for p in paras[:max_steps]]


def _synthesize_mecanica(sections: dict[str, str]) -> str:
    """Compose a structured summary from bases legales sections.
    Source = brand's own legal text (not blog text) -> no plagiarism concern.
    Format: labeled blocks, each one a single trimmed paragraph from the section.
    Empty string if no sections available.
    """
    if not sections:
        return ""
    parts: list[tuple[str, str]] = []
    mapping = [
        ("Premio", ["premio", "regalo"]),
        ("Mecánica", ["mec[áa]nica", "participaci[óo]n", "c[óo]mo participar"]),
        ("Duración", ["duraci[óo]n", "plazo", "vigencia"]),
        ("Ámbito", ["[áa]mbito", "territorio"]),
        ("Requisitos", ["requisitos", "participantes"]),
        ("Entrega", ["entrega", "comunicaci[óo]n del premio"]),
        ("Exclusiones", ["exclusi", "no podr[áa]n participar"]),
    ]
    used: set[str] = set()
    for label, needles in mapping:
        for n in needles:
            body = ""
            for title, sec_body in sections.items():
                if title in used:
                    continue
                if re.search(n, title, flags=re.IGNORECASE):
                    body = sec_body
                    used.add(title)
                    break
            if body:
                parts.append((label, _section_first_paragraph(body, 500)))
                break
    if not parts:
        return ""
    return "\n\n".join(f"{label}: {body}" for label, body in parts)


def build_row(
    art: Article,
    validity: Validity,
    landing: Landing | None,
    bases: BasesLegales | None,
    categoria_slug: str,
) -> dict[str, str]:
    confidence: list[str] = list(art.confidence)

    bases_text = bases.text if bases else ""
    landing_text = landing.text if landing else ""
    sections = parse_sections(bases_text)

    # ---- Fields driven by bases legales sections (preferred) ----
    # NB: "ámbito" alone is ambiguous (can be parent of Temporal/Territorial subsections).
    # We require "territorial" or "territorio" specifically.
    where_to_buy = _section_first_paragraph(
        find_section(sections, "territorial", "ámbito territorial", "ambito territorial"), 400
    )
    if not where_to_buy:
        # Fallback regex on bases text: catch typical territorial phrases
        m = re.search(
            r"(?:territorio\s+(?:nacional|espa[ñn]ol)"
            r"|v[áa]lid[oa]\s+(?:en|exclusivamente)\s+(?:el\s+)?territorio\s+espa[ñn]ol"
            r"|espacio\s+peninsular"
            r"|Pen[íi]nsula(?:[^.\n]{0,80}Canarias)?"
            r"|residencia\s+legal\s+en\s+Espa[ñn]a)"
            r"[^.\n]{0,250}",
            bases_text, flags=re.IGNORECASE,
        )
        if m:
            where_to_buy = _truncate(m.group(0).strip(), 400)
    if not where_to_buy:
        where_to_buy = extract_field(
            landing_text,
            [r"(?:disponible|v[áa]lid[oa])\s+en[^.\n]{5,200}",
             r"(?:hipermercado|supermercado|tiendas?|establecimientos?)[^.\n]{5,200}"],
        )
    if not where_to_buy:
        confidence.append("where_to_buy")

    reimbursement = _section_first_paragraph(
        find_section(sections, "premio", "regalo", "reembolso", "cashback"), 600
    )
    if not reimbursement:
        reimbursement = extract_field(
            landing_text,
            [r"(?:premio|gana(?:r|n|rás|ras)?|sorte[oa])[^.\n]{10,400}",
             r"(?:reembolso|cashback|devoluci[óo]n)[^.\n]{10,400}"],
        )
    if not reimbursement:
        confidence.append("reimbursement")

    claim_method = _section_first_paragraph(
        find_section(sections, "mecánica", "mecanica", "participación", "participacion", "cómo participar"),
        700,
    )
    if not claim_method:
        claim_method = extract_field(
            landing_text,
            [r"(?:para\s+participar|c[óo]mo\s+participar|mec[áa]nica)[^.\n]{10,500}",
             r"(?:rellena|completa|sube|env[íi]a|reg[íi]strate)[^.\n]{10,400}"],
        )
    if not claim_method:
        confidence.append("claim_method")

    physical_stores = extract_field(
        bases_text + "\n" + landing_text,
        [r"(?:tienda\s+f[íi]sica|punto\s+de\s+venta|establecimientos?\s+adheridos?)[^.\n]{5,300}"],
    )
    if not physical_stores:
        confidence.append("physical_stores")

    canali_esclusi = _section_first_paragraph(
        find_section(sections, "exclusi", "no podrán", "no podran"), 500
    )
    if not canali_esclusi:
        # Often inside DESTINATARIOS or PARTICIPANTES: search for the exclusion phrase
        dest_body = find_section(sections, "destinatarios", "participantes")
        scope = dest_body or bases_text
        m = re.search(
            r"(?:quedan\s+excluidos|no\s+podr[áa]n\s+participar)[^.]*\.(?:\s+[^.]*\.){0,3}",
            scope, flags=re.IGNORECASE | re.DOTALL,
        )
        if m:
            canali_esclusi = _truncate(m.group(0).strip(), 500)
    if not canali_esclusi:
        confidence.append("canali_esclusi")

    # contact: email or ES phone in bases
    contatto = ""
    m = re.search(r"[\w\.\-]+@[\w\.\-]+\.[a-z]{2,}", bases_text or landing_text)
    if m:
        contatto = m.group(0)
    else:
        m = re.search(r"\b(?:\+34\s?)?\d{3}[\s-]?\d{3}[\s-]?\d{3}\b", bases_text or landing_text)
        if m:
            contatto = m.group(0)
    if not contatto:
        confidence.append("contatto_promo")

    # passi — first try keyword sections; then fall back to extracting sub-steps
    # from inside MECÁNICA / PARTICIPACIÓN section (Nestlé/Buitoni structure).
    def _section_step(*needles: str) -> str:
        return _section_first_paragraph(find_section(sections, *needles), 500)

    passo_1 = _section_step("compra", "adquisici", "producto promocional", "requisitos de compra", "productos")
    passo_2 = _section_step("ticket", "comprobante", "factura", "documentaci")
    passo_3 = _section_step("verifica", "validaci", "comprobaci")
    passo_4 = _section_step("registro", "inscripci", "formulario", "alta")
    passo_5 = _section_step("entrega", "pago", "reembolso", "envío del premio", "envio del premio",
                            "comunicaci", "notificaci")

    # Fallback: split MECÁNICA / PARTICIPACIÓN section into sub-steps
    mecanica_body = find_section(sections, "mecánica", "mecanica", "participación", "participacion",
                                 "cómo participar", "como participar")
    if mecanica_body and not all([passo_1, passo_2, passo_3, passo_4, passo_5]):
        sub_steps = _split_mecanica_into_steps(mecanica_body)
        if not passo_1 and len(sub_steps) >= 1: passo_1 = sub_steps[0]
        if not passo_2 and len(sub_steps) >= 2: passo_2 = sub_steps[1]
        if not passo_3 and len(sub_steps) >= 3: passo_3 = sub_steps[2]
        if not passo_4 and len(sub_steps) >= 4: passo_4 = sub_steps[3]
        if not passo_5 and len(sub_steps) >= 5: passo_5 = sub_steps[4]

    legacy = extract_steps(bases_text)
    passi = {
        "passo_1_acquisto": passo_1 or legacy["passo_1_acquisto"],
        "passo_2_documenti": passo_2 or legacy["passo_2_documenti"],
        "passo_3_verifica": passo_3 or legacy["passo_3_verifica"],
        "passo_4_registrazione": passo_4 or legacy["passo_4_registrazione"],
        "passo_5_erogazione": passo_5 or legacy["passo_5_erogazione"],
    }
    for k, v in passi.items():
        if not v:
            confidence.append(k)

    image = landing.image if landing else ""
    # Reject images coming from the source blog or from social/share infra
    _BAD_IMG_HOSTS = (
        "regalosymuestrasgratis.com",
        "blogger.com", "blogspot.com", "googleusercontent.com",
        "ggpht.com", "gstatic.com", "addthis.com", "sharethis.com",
    )
    if image and any(h in image.lower() for h in _BAD_IMG_HOSTS):
        image = ""
    if not image:
        confidence.append("image")

    # Synthesized mecanica_full from brand's bases legales (no blog plagiarism)
    mecanica_full = _synthesize_mecanica(sections)
    if not mecanica_full and landing_text:
        # Fallback: structured summary from brand landing page (still brand-sourced)
        snippets: list[str] = []
        for label, pat in [
            ("Premio", r"(?:premio|gana(?:r|n|rás|ras)?|sorte[oa])[^.\n]{20,400}"),
            ("Mecánica", r"(?:para\s+participar|c[óo]mo\s+participar|mec[áa]nica)[^.\n]{20,500}"),
            ("Duración", r"(?:vigencia|duraci[óo]n|plazo|del\s+\d{1,2}[^.\n]{0,40}\d{4})[^.\n]{0,200}"),
        ]:
            m = re.search(pat, landing_text, flags=re.IGNORECASE)
            if m:
                snippets.append(f"{label}: {_truncate(m.group(0).strip(), 400)}")
        mecanica_full = "\n\n".join(snippets)
    if not mecanica_full:
        confidence.append("mecanica_full")

    form_url = art.participar_url
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    row = {
        "cashback_id": url_to_cashback_id(art.url),
        "title": art.title,
        "brand": art.brand,
        "description": art.description,
        "where_to_buy": where_to_buy,
        "validity": validity.text if validity.confident else "",
        "reimbursement": reimbursement,
        "claim_method": claim_method,
        "physical_stores": physical_stores,
        "channel": art.participar_url,
        "image": image,
        "[extra] categoria": categoria_slug,
        "[extra] mecanica_full": mecanica_full,
        "[extra] passo_1_acquisto": passi["passo_1_acquisto"],
        "[extra] passo_2_documenti": passi["passo_2_documenti"],
        "[extra] passo_3_verifica": passi["passo_3_verifica"],
        "[extra] passo_4_registrazione": passi["passo_4_registrazione"],
        "[extra] passo_5_erogazione": passi["passo_5_erogazione"],
        "[extra] canali_esclusi": canali_esclusi,
        "[extra] form_registrazione_url": form_url,
        "[extra] bases_legales_url": art.bases_legales_url,
        "[extra] contatto_promo": contatto,
        "[extra] conviene_se": "",
        "[extra] attenzione_se": "",
        "_source_url": art.url,
        "_scraped_at": now,
        "_confidence": ",".join(sorted(set(confidence + ["conviene_se", "attenzione_se"]))),
        "validity_end_date": validity.date_end.isoformat() if validity.date_end else "",
    }
    return row
