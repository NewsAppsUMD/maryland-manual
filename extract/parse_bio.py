"""Parse a Maryland Manual biography page (.../msaNNNNN.html).

Biography pages have no structured fields, but the header is regular:

    <b>KAREN LEWIS YOUNG</b><br>
    <i>Democrat, District 3, <a href=".../36loc/fr/html/fr.html">Frederick County</a></i>

    <b>ANTHONY G. BROWN, <i>Attorney General (Democrat)</i></b>

followed by a service paragraph such as "Member of Senate since January 11,
2023." or "Secretary of Agriculture since March 2, 2023."
"""

from __future__ import annotations

import re
from datetime import datetime

from .patterns import clean, unescape

PARTY_WORDS = r"Democrat|Republican|Unaffiliated|Independent|Green|Libertarian"
# "(Democrat)" after a title, or "Democrat, District 3, ..." under the name.
_HEADER_PARTY_RE = re.compile(r"\((" + PARTY_WORDS + r")\)|\b(" + PARTY_WORDS + r"),\s")
_COUNTY_LINK_RE = re.compile(r'href="?/msa/mdmanual/36loc/([a-z0-9]+)/html/\1\.html"?', re.I)
_DISTRICT_RE = re.compile(r"\bDistrict\s+([0-9]+[A-C]?)\b")
_MONTHS = ("January|February|March|April|May|June|July|August|September|October|"
           "November|December")
_TW = r"(?:[A-Z][\w.'&-]*|of|the|and|for|on|in|to|&|de|pro|tem)"
_SINCE_RE = re.compile(
    r"(?<![\w/])([A-Z][\w.'&-]*(?:,?\s+" + _TW + r")*)\s+since\s+((?:" + _MONTHS + r")\s+\d{1,2},\s+\d{4}|(?:"
    + _MONTHS + r")\s+\d{4}|\d{4})"
)
_COPYRIGHT_RE = re.compile(r"Copyright\s+((?:" + _MONTHS + r")\s+\d{1,2},\s+\d{4})", re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _iso(date_text: str) -> str:
    for fmt in ("%B %d, %Y", "%B %Y", "%Y"):
        try:
            d = datetime.strptime(clean(date_text), fmt)
            return d.strftime({"%B %d, %Y": "%Y-%m-%d", "%B %Y": "%Y-%m", "%Y": "%Y"}[fmt])
        except ValueError:
            continue
    return clean(date_text)


def _text(fragment: str) -> str:
    return clean(unescape(_TAG_RE.sub(" ", fragment)))


def parse_bio(html: str) -> dict:
    out: dict = {"party": None, "district": None, "counties": [], "since_title": None,
                 "since_date": None, "page_date": None, "title": None}
    m = _TITLE_RE.search(html)
    if m:
        out["title"] = _text(m.group(1))

    # Header: first <b> block plus the following line(s), before the first <hr>
    # after it or the first service paragraph.
    b = re.search(r"<b>", html, re.I)
    if b:
        tail = html[b.start():]
        stop = re.search(r"<ul>|<hr|<p>\s*[A-Z]", tail[10:], re.I)
        header = tail[: (stop.start() + 10) if stop else 1500]
        htext = _text(header)
        pm = _HEADER_PARTY_RE.search(htext)
        if pm:
            out["party"] = pm.group(1) or pm.group(2)
        dm = _DISTRICT_RE.search(htext)
        if dm:
            out["district"] = dm.group(1)
        out["counties"] = sorted(set(c.lower() for c in _COUNTY_LINK_RE.findall(header)))

        # Service paragraph: first "X since <date>" after the header.
        body = tail[len(header):]
        body_text = _text(body[:6000])
        sm = _SINCE_RE.search(body_text)
        if sm:
            out["since_title"] = sm.group(1).strip(" ,")
            out["since_date"] = _iso(sm.group(2))

    cm = _COPYRIGHT_RE.search(html)
    if cm:
        out["page_date"] = _iso(cm.group(1))
    return out
