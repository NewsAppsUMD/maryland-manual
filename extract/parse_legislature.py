"""General Assembly rosters.

Members come from the by-district pages, which give district, the counties
each district spans, party and a bio link in one place::

    <b>DISTRICT 2A</b> (Frederick & Washington Counties)<br>
    <a href=".../06hse/html/msa18500.html">William M. Valentine</a> (R)<br>

Leadership roles come from the alphabetical rosters::

    <li><a href=".../05sen/html/msa15347.html">Ferguson, Bill</a> (D), <i>Senate President</i>, District 46
"""

from __future__ import annotations

import re

from .patterns import clean
from .roster import PARTY_CODES, PARTY_RE, Official, tokenize

DISTRICT_PAGE_RE = re.compile(r"/(05sen|06hse)/html/(sendist|hsedist)\.html$", re.I)
ALPHA_PAGE_RE = re.compile(r"/(05sen|06hse)/html/(senal|hseal)\.html$", re.I)
COMMITTEE_PAGE_RE = re.compile(r"/(05sen|06hse|07leg)/html/com/[a-z0-9]+\.html$", re.I)

_DISTRICT_HEAD_RE = re.compile(r"^DISTRICT\s+([0-9]+[A-C]?)\s*(?:\((.*?)\))?", re.I)
_TERM_RE = re.compile(r"took office on ([A-Z][a-z]+ \d{1,2}, \d{4}), and serve until ([A-Z][a-z]+ \d{1,2}, (\d{4}))")
_BIO_RE = re.compile(r"/msa\d+\.html$", re.I)

CHAMBER = {"05sen": ("Senate", "State Senator"), "06hse": ("House of Delegates", "Delegate")}


def parse_district_page(url: str, html: str) -> list[Official]:
    section = DISTRICT_PAGE_RE.search(url).group(1).lower()
    body, title = CHAMBER[section]
    tm = _TERM_RE.search(clean(re.sub(r"<[^>]+>", " ", html)))
    term_end = int(tm.group(3)) if tm else None
    rows: list[Official] = []
    district = counties = None
    for line in tokenize(html):
        text = line.text
        dm = _DISTRICT_HEAD_RE.match(text)
        if dm:
            district, counties = dm.group(1), clean(dm.group(2) or "")
            continue
        if not district:
            continue
        bio = [(h, t) for h, t in line.links if _BIO_RE.search(h)]
        if not bio:
            if re.match(r"^vacancy\b", text, re.I):
                rows.append(Official(name="", is_vacancy=True, role=title, district=district,
                                     body=body, term_end_year=term_end, evidence=text,
                                     selection_method="elected", appointing_authority="Voters",
                                     extra={"counties_text": counties, "office_title": title}))
            continue
        href, name = bio[0]
        pm = PARTY_RE.search(text)
        rows.append(Official(
            name=clean(name).strip(" ,*"),
            party=PARTY_CODES[pm.group(1).upper()] if pm else None,
            role="", district=district, body=body, term_end_year=term_end,
            selection_method="elected", appointing_authority="Voters",
            term_length_years=4, bio_url=href, evidence=text,
            extra={"counties_text": counties, "office_title": title,
                   "term_start": tm.group(1) if tm else None},
        ))
    return rows


def parse_alpha_roles(html: str) -> dict[str, str]:
    """Map bio href -> leadership role from senal/hseal."""
    roles: dict[str, str] = {}
    for line in tokenize(html):
        links = [(h, t) for h, t in line.links if _BIO_RE.search(h)]
        if not links:
            continue
        italic = clean(" ".join(s.text for s in line.segs if s.italic))
        if italic:
            roles[links[0][0]] = italic.strip(" ,")
    return roles
