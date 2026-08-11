"""Parsers for roster/index pages.

These establish the authoritative membership of a level of government and the
containment edges the entity pages don't carry on their own:
  * the department index (09dept/00list.html) -> department roster
  * per-county municipality lists (36loc/{ab}/html/{ab}mu.html) -> contains
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from . import patterns
from .base import Entity, Edge, PageResult
from .registry import Registry

DEPT_INDEX_RE = re.compile(r"/msa/mdmanual/09dept/html/00list\.html$")
MUNI_LIST_RE = re.compile(r"/msa/mdmanual/36loc/([a-z0-9]+)/html/\1mu\.html$", re.I)


def parse_dept_index(url: str, html: str) -> PageResult:
    """Emit part_of edges: each department -> Maryland state government."""
    result = PageResult(page_type="dept_index")
    result.add_entity(Entity(
        id="gov:maryland", name="State of Maryland", type="government",
        level="state", url=url,
    ))
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        m = patterns.AGENCY_URL_RE.search(a["href"])
        if not m:
            continue
        aid = "agency:" + m.group(2).lower()
        result.add_edge(Edge(
            source_id=aid, type="part_of", target_id="gov:maryland",
            method="link", provenance_url=url,
            evidence="listed in Maryland Departments index",
        ))
    return result


def parse_muni_list(url: str, html: str, reg: Registry) -> PageResult | None:
    m = MUNI_LIST_RE.search(url)
    if not m:
        return None
    county = reg.by_abbrev(m.group(1))
    if county is None:
        return None
    result = PageResult(page_type="muni_list")
    soup = BeautifulSoup(html, "lxml")
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Municipality pages live under 37mun/.../html/*.html
        if "/msa/mdmanual/37mun/" not in href:
            continue
        name = patterns.clean(a.get_text())
        if not name or len(name) < 2:
            continue
        mid = "municipality:" + patterns.slugify(name)
        if mid in seen:
            continue
        seen.add(mid)
        full = ("https://msa.maryland.gov" + href) if href.startswith("/") else href
        result.add_entity(Entity(
            id=mid, name=name, type="municipality", level="municipal", url=full,
        ))
        result.add_edge(Edge(
            source_id=county.id, type="contains", target_id=mid,
            method="link", provenance_url=url,
            evidence=f"{name} listed under {county.name}",
        ))
    return result
