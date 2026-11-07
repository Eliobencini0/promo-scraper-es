"""robots.txt check, cached per origin.

Every fetch in this project (source site, brand landing pages, legal-terms pages) asks `allowed(url)` first.
No robots.txt (404, 410, other 4xx/5xx except 401/403) means everything is allowed; 401/403 or a network error
while reading it means nothing is. The user agent is the one in config.py, which names the project and its repo.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from config import REQUEST_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)

_parsers: dict[str, RobotFileParser] = {}


def _load(origin: str) -> RobotFileParser:
    rp = RobotFileParser()
    try:
        r = requests.get(f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
        elif r.status_code in (401, 403):
            rp.disallow_all = True
        else:
            rp.allow_all = True
    except requests.RequestException as e:
        log.warning("robots.txt unreadable for %s (%s): treating the origin as disallowed", origin, e)
        rp.disallow_all = True
    return rp


def allowed(url: str) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    origin = f"{p.scheme}://{p.netloc}"
    if origin not in _parsers:
        _parsers[origin] = _load(origin)
    ok = _parsers[origin].can_fetch(USER_AGENT, url)
    if not ok:
        log.info("robots.txt disallows %s", url)
    return ok
