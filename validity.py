"""Spanish date / validity parsing. Returns (date_end, normalized_text, confident).

Hardened: only trusts dates appearing near validity keywords, and explicitly
rejects 'No Definido' / 'indefinido' / 'sin fecha' / 'fin de existencias' as
unparseable (will cause is_active() to return False).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

# Phrases that explicitly mean "no end date"
_INDEFINITE_RE = re.compile(
    r"(no\s+definid[oa]|indefinid[oa]|sin\s+fecha|hasta\s+(?:agotar|fin\s+de\s+existencias)"
    r"|permanente|abierta\s+indefinidamente)",
    flags=re.IGNORECASE,
)


@dataclass
class Validity:
    date_end: date | None
    text: str
    confident: bool


def _try_numeric(s: str) -> date | None:
    m = re.search(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b", s)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _try_spanish_long(s: str) -> date | None:
    pattern = r"\b(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})\b"
    m = re.search(pattern, s, flags=re.IGNORECASE)
    if not m:
        return None
    d = int(m.group(1))
    mo_name = m.group(2).lower()
    mo_name = (mo_name.replace("á", "a").replace("é", "e").replace("í", "i")
               .replace("ó", "o").replace("ú", "u"))
    mo = SPANISH_MONTHS.get(mo_name)
    if not mo:
        return None
    try:
        return date(int(m.group(3)), mo, d)
    except ValueError:
        return None


def _scan_segment(seg: str) -> list[date]:
    """Find all dates inside a short segment of text."""
    out: list[date] = []
    for m in re.finditer(r"\b\d{1,2}[/\-]\d{1,2}[/\-]\d{4}\b", seg):
        d = _try_numeric(m.group(0))
        if d:
            out.append(d)
    for m in re.finditer(r"\b\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4}\b", seg, flags=re.IGNORECASE):
        d = _try_spanish_long(m.group(0))
        if d:
            out.append(d)
    return out


# Keywords that, when followed by a date within ~200 chars, mark a real end-date.
_VALIDITY_KEYWORDS = [
    r"v[áa]lida?\s+hasta",
    r"hasta\s+el",
    r"finaliza(?:r[áa])?(?:\s+el)?",
    r"finalizar[áa]\s+el",
    r"vigencia",
    r"vigente\s+hasta",
    r"per[íi]odo\s+de\s+validez",
    r"plazo\s+de\s+participaci[óo]n",
    r"caduca",
    r"fecha\s+l[íi]mite",
]


def parse_validity(raw_text: str) -> Validity:
    """Parse validity text. Returns confident=True only if a date is found
    in proximity to a validity keyword AND no 'indefinite' marker is present.
    """
    if not raw_text:
        return Validity(None, "", False)

    text = raw_text.strip()

    # Reject indefinite markers up front
    if _INDEFINITE_RE.search(text):
        return Validity(None, "indefinite", False)

    # Scan windows of ~200 chars after each validity keyword
    candidates: list[date] = []
    for kw in _VALIDITY_KEYWORDS:
        for m in re.finditer(kw, text, flags=re.IGNORECASE):
            start = m.end()
            window = text[start:start + 250]
            # Stop window at sentence end if reasonable
            stop = re.search(r"[.\n]", window[20:])  # allow first 20 chars
            if stop:
                window = window[: 20 + stop.start()]
            candidates.extend(_scan_segment(window))

    if candidates:
        # Pick the LATEST date found near a keyword (end of range)
        end = max(candidates)
        return Validity(end, end.isoformat(), True)

    return Validity(None, text[:200], False)


def is_active(v: Validity, today: date | None = None) -> bool:
    """Active iff we have an explicit confident end-date and it is >= today."""
    today = today or date.today()
    if not v.confident or v.date_end is None:
        return False
    return v.date_end >= today
