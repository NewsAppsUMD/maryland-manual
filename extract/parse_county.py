"""Parser for county home pages (/msa/mdmanual/36loc/{ab}/html/{ab}.html)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from . import patterns
from .base import Entity, Edge, PageResult
from .registry import Registry


def _form_of_government(raw: str) -> dict:
    raw = patterns.clean(raw)
    low = raw.lower()
    since = None
    m = re.search(r"since\s+(\d{4})", low)
    if m:
        since = int(m.group(1))
    if "charter" in low:
        category = "charter"
    elif "code home rule" in low:
        category = "code-home-rule"
    elif "commission" in low:
        category = "commission"
    else:
        category = "other"
    return {"raw": raw, "category": category, "since": since}


def parse(url: str, html: str, reg: Registry) -> PageResult | None:
    m = patterns.COUNTY_URL_RE.search(url)
    if not m:
        return None
    county = reg.by_abbrev(m.group(1))
    if county is None:
        return None

    soup = BeautifulSoup(html, "lxml")
    text = patterns.clean_lines(soup.get_text("\n"))
    flat = patterns.clean(text)

    result = PageResult(page_type="county")

    attrs: dict = {"abbrev": county.abbrev}

    fm = patterns.FORM_OF_GOVT_RE.search(text)
    if fm:
        attrs["form_of_government"] = _form_of_government(fm.group(1))
    elif re.search(r"City Charter", text, re.I) and re.search(r"\bMayor\b", text):
        # Baltimore City: a chartered independent city, described in prose rather
        # than with the county "Form of Government:" field. It is treated on a par
        # with counties (Const. 1851) and runs under a Mayor-Council city charter.
        attrs["form_of_government"] = {
            "raw": "Mayor-Council (City Charter)", "category": "charter",
            "since": None, "independent_city": True,
        }

    seat = patterns.COUNTY_SEAT_RE.search(text)
    if seat:
        attrs["county_seat"] = patterns.clean(seat.group(1)).split(";")[0]

    census = {yr: int(v.replace(",", "")) for yr, v in patterns.CENSUS_RE.findall(flat)}
    if census:
        attrs["population"] = census
        attrs["population_latest"] = census[max(census)]
        attrs["population_year"] = int(max(census))

    entity = Entity(
        id=county.id, name=county.name, type="county", level="county",
        url=county.url, attrs=attrs,
    )
    result.add_entity(entity)

    # --- Adjacency (from the Boundaries sentence) ---
    bm = patterns.BOUNDARIES_RE.search(text)
    if bm:
        boundary_text = patterns.clean(bm.group(1))
        for neighbor_id in reg.match_names(boundary_text):
            if neighbor_id == county.id:
                continue
            result.add_edge(Edge(
                source_id=county.id, type="adjacent_to", target_id=neighbor_id,
                method="regex", provenance_url=url,
                evidence=boundary_text[:200],
            ))

    # --- Origin: created_by statutes + named_for person ---
    om = patterns.ORIGIN_RE.search(flat)
    origin_text = patterns.clean(om.group(1)) if om else flat[:600]
    for law in patterns.find_session_laws(origin_text):
        sid = f"statute:{law['year']}-{law['chapter']}"
        result.add_entity(Entity(
            id=sid, name=law["citation"], type="statute", level="state",
        ))
        result.add_edge(Edge(
            source_id=county.id, type="created_by", target_id=sid,
            qualifiers={"chapter": law["chapter"], "year": law["year"]},
            method="regex", provenance_url=url, evidence=origin_text[:200],
        ))

    # named_for: first person link inside the origin paragraph
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if patterns.BIO_SC3500_RE.search(href) or patterns.BIO_LOCAL_RE.search(href):
            name = patterns.clean(a.get_text())
            if name and name in origin_text:
                result.add_edge(Edge(
                    source_id=county.id, type="named_for", target_url=href,
                    qualifiers={"person_name": name},
                    method="regex", provenance_url=url,
                    evidence=f"named for {name}",
                ))
                break

    return result
