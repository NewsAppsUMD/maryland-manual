"""Shared extraction patterns and helpers.

The Maryland Manual's markup is vintage but remarkably consistent. These are the
regexes and small helpers the page-type parsers share. Keep parsing tolerant:
prefer matching against the page's *text* (BeautifulSoup get_text) over its
tag soup, except where a link target is the payload.
"""

from __future__ import annotations

import re
import unicodedata

# --- URL shapes -----------------------------------------------------------

# A county home page: /msa/mdmanual/36loc/{ab}/html/{ab}.html
COUNTY_URL_RE = re.compile(r"/msa/mdmanual/36loc/([a-z0-9]+)/html/\1\.html$", re.I)

# A state department / agency home page: /msa/mdmanual/{NN}{abbr}/html/{abbr}.html
# e.g. 10da/html/da.html, 16dhmh/html/dhmh.html
AGENCY_URL_RE = re.compile(r"/msa/mdmanual/(\d+)([a-z]+)/html/\2\.html$", re.I)

# Biographical person pages.
BIO_SC3500_RE = re.compile(r"/msa/speccol/sc3500/.*?/(msa\d+|sc\d+)[^/]*\.html$", re.I)
# Local person pages inside a section: .../html/msaNNNNN.html
BIO_LOCAL_RE = re.compile(r"/msa/mdmanual/[^/]+/html/(msa\d+)\.html$", re.I)

# Session-law citation, e.g. "Chapter 22, Acts of 1838".
SESSION_LAW_RE = re.compile(r"Chapter\s+(\d+),\s+Acts?\s+of\s+(\d{4})", re.I)

# --- Labeled fields on county pages ---------------------------------------

FORM_OF_GOVT_RE = re.compile(r"Form of Government:\s*([^\n<]+)", re.I)
COUNTY_SEAT_RE = re.compile(r"County Seat:\s*([^\n<]+)", re.I)
ORIGIN_RE = re.compile(r"Origin:\s*(.+?)(?:\n|Boundaries:)", re.I | re.S)
# The Boundaries value is a single line in get_text("\n") output; stopping at the
# newline keeps photo captions and footer county names out of adjacency.
BOUNDARIES_RE = re.compile(r"Boundaries:\s*([^\n]+)", re.I)
# Census figures like "2020 census: 332,317"
CENSUS_RE = re.compile(r"(\d{4})\s+census:\s*([\d,]+)", re.I)

# --- Appointment prose -----------------------------------------------------
# Matches "appointed by the Governor", "Appointed by County Executive", with
# optional "with Senate advice & consent" and "to N-year terms".
APPOINTERS = [
    "Governor",
    "General Assembly",
    "Senate President",
    "President of the Senate",
    "House Speaker",
    "Speaker of the House",
    "County Executive",
    "County Council",
    "County Commissioners",
    "Board of County Commissioners",
    "Mayor",
    "City Council",
    "Chief Judge",
    "Secretary",
    "Board of Public Works",
    "Attorney General",
    "Comptroller",
]
_APPOINTER_ALT = "|".join(re.escape(a) for a in sorted(APPOINTERS, key=len, reverse=True))
APPOINTMENT_RE = re.compile(
    r"[Aa]ppointed by\s+(?:the\s+)?(" + _APPOINTER_ALT + r")"
    r"(?P<consent>\s+with\s+Senate\s+advice\s*&?\s*consent)?"
    r"(?:[^.\n]*?to\s+(?P<term>\d+)-year terms?)?",
)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def clean(text: str) -> str:
    """Collapse whitespace and strip the vintage non-breaking junk."""
    text = text.replace("\xa0", " ").replace("​", "")
    return re.sub(r"\s+", " ", text).strip()


def clean_lines(text: str) -> str:
    """Collapse horizontal whitespace but preserve line breaks.

    Labeled fields ("Form of Government: Charter since 1968") end at a line
    break in BeautifulSoup's get_text("\\n") output, so the field regexes need
    the newlines kept.
    """
    text = text.replace("\xa0", " ").replace("​", "")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def find_appointments(text: str) -> list[dict]:
    """Return appointment relationships found in prose, with evidence."""
    out = []
    for m in APPOINTMENT_RE.finditer(text):
        appointer = clean(m.group(1))
        # Normalize a couple of synonyms.
        appointer = {
            "President of the Senate": "Senate President",
            "Speaker of the House": "House Speaker",
            "Board of County Commissioners": "County Commissioners",
        }.get(appointer, appointer)
        qual = {}
        if m.group("consent"):
            qual["consent"] = "senate"
        if m.group("term"):
            qual["term_years"] = int(m.group("term"))
        # Evidence: a window around the match.
        start = max(0, m.start() - 40)
        end = min(len(text), m.end() + 20)
        window = text[m.start():end].lower()
        if "nonvoting" in window or "non-voting" in window:
            qual["voting"] = False
        out.append({
            "appointer": appointer,
            "qualifiers": qual,
            "evidence": clean(text[start:end]),
        })
    return out


def person_id_from_url(url: str) -> str | None:
    """Stable person node id from a biography URL."""
    m = BIO_LOCAL_RE.search(url)
    if m:
        return "person:" + m.group(1).lower()
    m = BIO_SC3500_RE.search(url)
    if m:
        return "person:" + m.group(1).lower()
    return None


def find_session_laws(text: str) -> list[dict]:
    out = []
    seen = set()
    for m in SESSION_LAW_RE.finditer(text):
        chapter, year = m.group(1), m.group(2)
        key = (chapter, year)
        if key in seen:
            continue
        seen.add(key)
        out.append({"chapter": int(chapter), "year": int(year),
                    "citation": f"Chapter {chapter}, Acts of {year}"})
    return out
