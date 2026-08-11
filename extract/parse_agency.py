"""Parser for state department / agency home pages.

URL shape: /msa/mdmanual/{NN}{abbr}/html/{abbr}.html
(e.g. 10da/html/da.html, 16dhmh/html/dhmh.html)
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from . import patterns
from .base import APPOINTER_OFFICE, Entity, Edge, PageResult

# Person link + following role in italics, tolerant of the vintage markup.
OFFICIAL_RE = re.compile(
    r'<a\s+href="([^"]*(?:msa\d+|sc\d+)[^"]*\.html)"[^>]*>([^<]+)</a>\s*,?\s*'
    r'<i>([^<]+)</i>',
    re.I,
)

LEADERSHIP_WORDS = ("secretary", "director", "executive", "administrator",
                    "chair", "chief", "commissioner", "president")


# URL shapes that match the generic agency pattern but aren't agencies.
_NOT_AGENCIES = {"const"}  # 43const/html/const.html = the state constitution


def _agency_id(url: str) -> str | None:
    m = patterns.AGENCY_URL_RE.search(url)
    if not m:
        return None
    abbr = m.group(2).lower()
    if abbr in _NOT_AGENCIES:
        return None
    return "agency:" + abbr


def parse(url: str, html: str, reg=None) -> PageResult | None:
    aid = _agency_id(url)
    if aid is None:
        return None

    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    title = soup.find("title")
    name = patterns.clean(h1.get_text()) if h1 else (
        patterns.clean(title.get_text()) if title else aid)
    # Titlecase the shouty h1 ("DEPARTMENT OF AGING"), keeping small words down.
    if name.isupper():
        small = {"of", "and", "the", "for", "on", "to", "in", "&"}
        words = name.title().split()
        name = " ".join(
            w.lower() if w.lower() in small and i else w
            for i, w in enumerate(words)
        )

    text = patterns.clean_lines(soup.get_text("\n"))

    result = PageResult(page_type="agency")

    attrs: dict = {}
    # Real agency website: an external *.maryland.gov link (not msa.) whose
    # anchor text is itself a URL — that's how the Manual lists "web:" links,
    # which distinguishes them from footer nav ("Governor", "General Assembly").
    _BOILERPLATE = ("governor.maryland.gov", "www.maryland.gov",
                    "feedback.msa", "mgaleg.maryland.gov")
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        anchor = patterns.clean(a.get_text())
        if not re.match(r"https?://(?!msa\.)([a-z0-9-]+\.)*maryland\.gov", href, re.I):
            continue
        if any(b in href for b in _BOILERPLATE):
            continue
        if not re.match(r"(https?://|www\.)", anchor):
            continue  # anchor text is a word, not a URL -> nav, skip
        candidates.append(href)
    if candidates:
        attrs["website"] = min(candidates, key=lambda h: (len(h.split("/")), len(h)))

    dept = "department of" in name.lower() or aid.startswith("agency:d")
    result.add_entity(Entity(
        id=aid, name=name, type="department" if dept else "agency",
        level="state", url=url, attrs=attrs,
    ))

    # --- Officials (person -> agency, with role) ---
    seen_person = set()
    seen_edge = set()
    for m in OFFICIAL_RE.finditer(html):
        href, pname, role = m.group(1), patterns.clean(m.group(2)), patterns.clean(m.group(3))
        pid = patterns.person_id_from_url(href)
        if not pid:
            continue
        if pid not in seen_person:
            result.add_entity(Entity(
                id=pid, name=pname, type="person", level="state",
                url=("https://msa.maryland.gov" + href) if href.startswith("/") else href,
            ))
            seen_person.add(pid)
        edge_key = (pid, role.lower())
        if edge_key in seen_edge:
            continue
        seen_edge.add(edge_key)
        is_leader = any(w in role.lower() for w in LEADERSHIP_WORDS)
        result.add_edge(Edge(
            source_id=pid, type="leads" if is_leader else "serves_in",
            target_id=aid, qualifiers={"role": role},
            method="regex", provenance_url=url,
            evidence=patterns.clean(f"{pname}, {role}")[:200],
        ))

    # --- Appointments (appointer office -> agency) ---
    appt_seen = set()
    for appt in patterns.find_appointments(text):
        office = APPOINTER_OFFICE.get(appt["appointer"])
        if not office:
            continue  # county/municipal appointers not meaningful on a state page
        oid, oname, olevel = office
        key = (oid, tuple(sorted(appt["qualifiers"].items())))
        if key in appt_seen:
            continue
        appt_seen.add(key)
        result.add_entity(Entity(id=oid, name=oname, type="office", level=olevel))
        result.add_edge(Edge(
            source_id=oid, type="appoints", target_id=aid,
            qualifiers=appt["qualifiers"], method="regex",
            provenance_url=url, evidence=appt["evidence"],
        ))

    # --- Created-by statutes ---
    for law in patterns.find_session_laws(text):
        sid = f"statute:{law['year']}-{law['chapter']}"
        result.add_entity(Entity(id=sid, name=law["citation"], type="statute", level="state"))
        result.add_edge(Edge(
            source_id=aid, type="created_by", target_id=sid,
            qualifiers={"chapter": law["chapter"], "year": law["year"]},
            method="regex", provenance_url=url, evidence=law["citation"],
        ))

    return result
