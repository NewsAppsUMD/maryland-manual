"""Canonical entity registry, built from the Manual's own index pages.

The county roster is authoritative for adjacency resolution: the Boundaries
prose names neighbors in free text, and we match those names against the known
set of 24 jurisdictions. Baltimore is deliberately ambiguous in English
("Baltimore County" vs "Baltimore City"), so we handle it explicitly.
"""

from __future__ import annotations

from .patterns import decode_page

import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from . import patterns

CACHE = Path("data/cache")
COUNTY_INDEX = CACHE / "msa/mdmanual/01glance/html/county.html"


@dataclass
class County:
    id: str
    name: str        # "Howard County"
    short: str       # "Howard"
    abbrev: str      # "how"
    url: str
    slug: str


@dataclass
class Registry:
    counties: list[County] = field(default_factory=list)
    _by_abbrev: dict[str, County] = field(default_factory=dict)
    _name_index: list[tuple[str, str]] = field(default_factory=list)  # (lower name, id)

    def by_abbrev(self, abbrev: str) -> County | None:
        return self._by_abbrev.get(abbrev.lower())

    def id_for_url(self, url: str) -> str | None:
        m = patterns.COUNTY_URL_RE.search(url)
        if m:
            c = self.by_abbrev(m.group(1))
            return c.id if c else None
        return None

    def match_names(self, text: str) -> list[str]:
        """Return county ids named in free text (e.g. a Boundaries sentence).

        Handles the shared-plural construction "Baltimore & Carroll counties"
        and the Baltimore City / Baltimore County ambiguity: in boundary prose a
        bare "Baltimore" means the county (the city is always spelled out).
        """
        low = text.lower()
        found: list[str] = []

        def add(cid: str) -> None:
            if cid not in found:
                found.append(cid)

        city_id = None
        county_baltimore_id = None
        for c in self.counties:
            if c.short.lower() == "baltimore city":
                city_id = c.id
            elif c.short.lower() == "baltimore":
                county_baltimore_id = c.id

        for name, cid in self._name_index:
            if cid in (city_id, county_baltimore_id):
                continue  # handled specially below
            if re.search(r"\b" + re.escape(name) + r"\b", low):
                add(cid)

        # Baltimore disambiguation.
        if city_id and re.search(r"\bbaltimore\s+city\b", low):
            add(city_id)
        if county_baltimore_id and re.search(r"\bbaltimore\b(?!\s+city)", low):
            add(county_baltimore_id)
        return found


def _canonical_name(short: str) -> str:
    if short.lower() == "baltimore city":
        return "Baltimore City"
    return f"{short} County"


def load_registry(index_path=None) -> Registry:
    reg = Registry()
    path = index_path or COUNTY_INDEX
    if not path.exists():
        return reg
    soup = BeautifulSoup(decode_page(path.read_bytes()), "lxml")
    for a in soup.find_all("a", href=True):
        m = patterns.COUNTY_URL_RE.search(a["href"])
        if not m:
            continue
        abbrev = m.group(1).lower()
        name = patterns.clean(a.get_text())
        if not name:
            continue
        short = re.sub(r"\s+County$", "", name, flags=re.I)
        cid = "county:" + patterns.slugify(short)
        if abbrev in reg._by_abbrev:
            continue
        url = "https://msa.maryland.gov" + a["href"] if a["href"].startswith("/") else a["href"]
        c = County(id=cid, name=_canonical_name(short), short=short,
                   abbrev=abbrev, url=url, slug=patterns.slugify(short))
        reg.counties.append(c)
        reg._by_abbrev[abbrev] = c

    # Build name index for adjacency matching. Longer names first so
    # "Prince George's" wins over a bare token, and "Baltimore City" /
    # "Baltimore County" disambiguate before plain "Baltimore".
    names: list[tuple[str, str]] = []
    for c in reg.counties:
        if c.short.lower() == "baltimore city":
            names.append(("baltimore city", c.id))
        elif c.short.lower() == "baltimore":
            names.append(("baltimore county", c.id))
            names.append(("baltimore co", c.id))
        else:
            names.append((c.short.lower(), c.id))
            names.append((c.name.lower(), c.id))
    reg._name_index = sorted(set(names), key=lambda t: len(t[0]), reverse=True)
    return reg
