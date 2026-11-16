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
    # Officials rosters (legislature, judiciary, municipalities by name)
    "senate_roster": "https://msa.maryland.gov/msa/mdmanual/05sen/html/senal.html",
    "senate_district": "https://msa.maryland.gov/msa/mdmanual/05sen/html/sendist.html",
    "senate_home": "https://msa.maryland.gov/msa/mdmanual/05sen/html/sen.html",
    "senate_committees": "https://msa.maryland.gov/msa/mdmanual/05sen/html/sencom.html",
    "house_roster": "https://msa.maryland.gov/msa/mdmanual/06hse/html/hseal.html",
    "house_district": "https://msa.maryland.gov/msa/mdmanual/06hse/html/hsedist.html",
    "house_home": "https://msa.maryland.gov/msa/mdmanual/06hse/html/hse.html",
    "house_committees": "https://msa.maryland.gov/msa/mdmanual/06hse/html/hsecom.html",
    "general_assembly": "https://msa.maryland.gov/msa/mdmanual/07leg/html/ga.html",
    "cabinet": "https://msa.maryland.gov/msa/mdmanual/08conoff/html/01coun.html",
    "judiciary": "https://msa.maryland.gov/msa/mdmanual/29ap/html/00list.html",
    "supreme_court": "https://msa.maryland.gov/msa/mdmanual/29ap/html/ap.html",
    "appellate_court": "https://msa.maryland.gov/msa/mdmanual/30sp/html/sp.html",
    "district_court": "https://msa.maryland.gov/msa/mdmanual/32dc/html/dc.html",
    "municipalities_by_name": "https://msa.maryland.gov/msa/mdmanual/01glance/html/mun.html",
    "universities": "https://msa.maryland.gov/msa/mdmanual/01glance/html/edhigh.html",
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
    # Officials: only roster pages that list office-holders, plus the
    # biography pages they link. Scoped by OFFICIALS_FOLLOW below.
    "officials": [
        "senate_roster", "senate_district", "senate_home", "senate_committees",
        "house_roster", "house_district", "house_home", "house_committees",
        "general_assembly",
        "const_offices", "cabinet", "departments", "independent", "commissions",
        "universities",
        "judiciary", "supreme_court", "appellate_court", "district_court",
        "counties", "municipalities_by_name",
    ],
}

# Link depth limit per profile (None = unlimited). Rosters sit at most a few
# hops below the seeds; bios are one hop below a roster.
PROFILE_MAX_DEPTH = {"officials": 4}

# --- Officials profile scope -----------------------------------------------
# Pages under /msa/mdmanual/ that may list office-holders. Matched against the
# path with MANUAL_PREFIX removed. Anything else in the Manual is skipped.
_M = r"[a-z0-9]+"
OFFICIALS_FOLLOW = [re.compile(p, re.I) for p in (
    r"01glance/html/(county|mun|edhigh)\.html$",
    r"05sen/html/(senal|sendist|sen|sencom)\.html$",
    r"06hse/html/(hseal|hsedist|hse|hsecom)\.html$",
    r"0[567](sen|hse|leg)/html/com/" + _M + r"\.html$",
    r"07leg/html/ga\.html$",
    r"08conoff/(" + _M + r"/)*html/" + _M + r"\.html$",
    r"09dept/html/00list\.html$",
    # Departments, independent agencies, universities, commissions
    r"(1\d|2[0-6])" + _M + r"/(" + _M + r"/)*html/" + _M + r"\.html$",
    r"29ap/html/(00list|ap)\.html$",
    r"30sp/html/sp\.html$",
    r"32dc/html/dc\.html$",
    # County landing + executive / legislative / judicial branch pages
    r"36loc/(" + _M + r")/html/\1(e|l|j)?\.html$",
    # Municipal home pages: 37mun/{slug}/html/{letter}.html
    r"37mun/" + _M + r"/html/[a-z]\.html$",
)]

# Never follow: historical, descriptive or financial pages.
OFFICIALS_EXCLUDE = re.compile(
    r"/(former|defunct|functions|elect|chron|reports?|budget|history)/"
    r"|mayors\.html$|coex\.html$|00former|biosf\.html$"
    # Department satellite pages: {abbr}{f|r|b|h|d|a}.html and NNagen.html
    r"|/\d\d(?P<ab>[a-z]+)/html/(?P=ab)[frbhda]\.html$"
    r"|/\d\dagen\.html$",
    re.I,
)

# Biography pages inside the Manual: .../msaNNNNN.html
MANUAL_BIO_RE = re.compile(r"/msa\d+\.html$", re.I)


def classify_officials(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc.lower().endswith("msa.maryland.gov"):
        return "skip"
    path = parsed.path
    if path.startswith(BIO_PREFIX):
        return "fetch_only"
    if not path.startswith(MANUAL_PREFIX):
        return "skip"
    if MANUAL_BIO_RE.search(path):
        return "fetch_only"
    if OFFICIALS_EXCLUDE.search(path):
        return "skip"
    rel = path[len(MANUAL_PREFIX):]
    if any(p.match(rel) for p in OFFICIALS_FOLLOW):
        return "fetch_follow"
    return "skip"

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


def classify(url: str, profile: str | None = None) -> str:
    """Return a crawl disposition for a normalized URL.

    One of: 'fetch_follow', 'fetch_only', 'record_only', 'skip'.
    """
    if profile == "officials":
        return classify_officials(url)
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


def seed_urls(profile: str) -> list[str]:
    keys = PROFILES.get(profile, PROFILES["mvp"])
    return [SEEDS[k] for k in keys]
