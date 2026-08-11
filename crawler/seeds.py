"""Seed URLs and scope rules for the Maryland Manual crawler.

Golden rule learned the hard way: NEVER construct entity URLs. Guessed paths
return real IIS 404s. We start from a handful of authoritative index pages and
follow only the links we actually discover.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

BASE = "https://msa.maryland.gov"
MANUAL_PREFIX = "/msa/mdmanual/"

# Seed index pages. These are the authoritative rosters; everything else is
# reached by following links from here.
SEEDS = {
    # Full table of contents
    "toc": "https://msa.maryland.gov/msa/mdmanual/html/mmtoc.html",
    # Local government
    "counties": "https://msa.maryland.gov/msa/mdmanual/01glance/html/county.html",
    "counties_by_class": "https://msa.maryland.gov/msa/mdmanual/01glance/html/cocomm.html",
    "municipalities": "https://msa.maryland.gov/msa/mdmanual/01glance/html/munic.html",
    "local_gov": "https://msa.maryland.gov/msa/mdmanual/01glance/html/locgov.html",
    # State government
    "departments": "https://msa.maryland.gov/msa/mdmanual/09dept/html/00list.html",
    "const_offices": "https://msa.maryland.gov/msa/mdmanual/08conoff/html/01exec.html",
    "independent": "https://msa.maryland.gov/msa/mdmanual/25ind/html/00list.html",
    "commissions": "https://msa.maryland.gov/msa/mdmanual/26excom/html/00list.html",
    # Reference used by peer scoring
    "population": "https://msa.maryland.gov/msa/mdmanual/01glance/html/pop.html",
}

# Which seeds belong to which crawl profile.
PROFILES = {
    # MVP: counties + state departments + the glance indexes that classify them.
    # Entity-bearing rosters first so a bounded crawl reaches the counties and
    # departments before descending the giant table of contents.
    "mvp": [
        "counties",
        "counties_by_class",
        "departments",
        "const_offices",
        "population",
        "local_gov",
        "toc",
    ],
    # Full: everything, including municipalities, independent agencies and
    # executive commissions.
    "full": list(SEEDS.keys()),
}

# Path fragments we record as an edge target but never fetch/descend into.
# These are huge, off-mission, or archival scans.
_SKIP_DESCEND = (
    "/elect/",        # election returns — bulk, off-mission
    "/images/",
    "/pdf/",
)
_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".gif", ".png", ".zip", ".xls", ".xlsx", ".doc", ".docx")

# Biography pages: fetch once (they are the "person" nodes) but do NOT follow
# their outbound links.
BIO_PREFIX = "/msa/speccol/sc3500"
# Session-law megafile scans: record the citation, never fetch.
STATUTE_PREFIX = "/msa/speccol/sc2900"


def normalize(url: str, base: str | None = None) -> str | None:
    """Resolve, strip fragments, canonicalize. Returns None if not http(s)."""
    if base:
        url = urljoin(base, url)
    url = url.strip()
    if not url:
        return None
    # Drop fragments — a page is a page regardless of anchor.
    url = url.split("#", 1)[0]
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    # Force https and canonical host; the site serves both.
    netloc = parsed.netloc.lower()
    path = parsed.path
    if not path:
        path = "/"
    rebuilt = f"https://{netloc}{path}"
    if parsed.query:
        rebuilt += f"?{parsed.query}"
    return rebuilt


def classify(url: str) -> str:
    """Return a crawl disposition for a normalized URL.

    One of: 'fetch_follow', 'fetch_only', 'record_only', 'skip'.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path
    lower = path.lower()

    # Off-site: record as an external link, never fetch.
    if not host.endswith("maryland.gov"):
        return "record_only"

    if any(lower.endswith(ext) for ext in _SKIP_EXT):
        return "record_only"

    if path.startswith(STATUTE_PREFIX):
        return "record_only"
    if path.startswith(BIO_PREFIX):
        return "fetch_only"  # person node: fetch once, don't follow

    if path.startswith(MANUAL_PREFIX):
        if any(frag in lower for frag in _SKIP_DESCEND):
            return "record_only"
        return "fetch_follow"

    # Other msa.maryland.gov or *.maryland.gov pages: record but don't crawl.
    return "record_only"


_COUNTY_RE = re.compile(r"/msa/mdmanual/36loc/([a-z]+)/html/\1\.html$", re.I)


def seed_urls(profile: str) -> list[str]:
    keys = PROFILES.get(profile, PROFILES["mvp"])
    return [SEEDS[k] for k in keys]
