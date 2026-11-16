"""Build the officials dataset from the crawl cache.

Reads the crawl manifest and cached HTML (never the network), runs the right
roster parser for each page type, enriches rows from biography pages, and
returns one dict per person-office.

    python -m extract.officials          # print a summary and coverage report
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urljoin

from . import parse_legislature as leg
from .parse_bio import parse_bio
from .patterns import clean, decode_page, slugify
from .registry import load_registry
from .roster import OFFICER_ROLES, Official, page_title, parse_roster, smart_title, tokenize

MANIFEST = Path("data/cache/crawl.db")
BASE = "https://msa.maryland.gov"

BIO_ID_RE = re.compile(r"/(msa\d+)\.html$", re.I)
COUNTY_PAGE_RE = re.compile(r"/36loc/([a-z0-9]+)/html/\1(e|l|j)\.html$", re.I)
MUNI_PAGE_RE = re.compile(r"/37mun/([a-z0-9]+)/html/[a-z]\.html$", re.I)
LEADERS_PAGE_RE = re.compile(r"/(05sen|06hse)/html/(sen|hse)\.html$", re.I)

# Index and navigation pages: no office-holders worth parsing.
SKIP_PAGE_RE = re.compile(
    r"/00list\.html$|/01glance/|/07leg/html/ga\.html$|/(sencom|hsecom|senal|hseal)\.html$"
    r"|/01exec\.html$|/36loc/([a-z0-9]+)/html/\2\.html$",
    re.I,
)

# Outside a selection block, unlinked rows are kept only for these titles.
HEAD_TITLES = re.compile(
    r"^(?:Acting\s+|Interim\s+)?(?:Governor|Lt\. Governor|Lieutenant Governor|Attorney General|"
    r"Comptroller(?: of Maryland)?|State Treasurer|Secretary of\b.*|State Superintendent.*|"
    r"Adjutant General|Mayor|County Executive|Chief Justice|Chief Judge)\s*$",
    re.I,
)

ELECTED_OFFICES = re.compile(
    r"^(?:State's Attorney|Sheriff|Clerk(?: of (?:the )?Circuit Court)?|Register of Wills|"
    r"County Executive|Mayor)$")

STATE_BRANCH = [
    (re.compile(r"/(05sen|06hse|07leg)/"), "legislative"),
    (re.compile(r"/(29ap|30sp|31cc|32dc|33jud)/"), "judicial"),
]

COUNTY_BRANCH = {"e": "executive", "l": "legislative", "j": "judicial"}


def _abs(href: str | None, base: str) -> str | None:
    return urljoin(base, href) if href else None


def person_id(o: Official, body: str, base: str) -> str:
    if o.bio_url:
        m = BIO_ID_RE.search(o.bio_url)
        if m:
            return "person:" + m.group(1).lower()
    return f"person:{slugify(o.name)}@{slugify(body)[:60]}"


_NAME_SUFFIX_RE = re.compile(r"\s+(Jr\.?|Sr\.?|II|III|IV|V)$")
_PARTICLE_RE = re.compile(r"^(?:de|da|del|della|der|di|du|la|le|van|von|st\.|dos|das|ten|ter)$", re.I)
_RANK_RE = re.compile(
    r"^(?:Maj\.|Gen\.|Col\.|Lt\.|Capt\.|Cpt\.|Sgt\.|Adm\.|Brig\.|Cmdr\.|Rear|Vice|Dr\.|Rev\.|Hon\.)\s+")


def split_name(full: str) -> dict:
    """'Yaakov (Jake) Weissmann, Esq.' -> first/middle/last/suffix/nickname."""
    out = {"name_first": "", "name_middle": "", "name_last": "", "name_suffix": "", "nickname": ""}
    if not full:
        return out
    parts = [p.strip() for p in full.split(",")]
    core, suffixes = parts[0], [p for p in parts[1:] if p]
    m = _NAME_SUFFIX_RE.search(core)
    if m:
        suffixes.insert(0, m.group(1))
        core = core[:m.start()]
    nick = re.findall(r"\(([^)]+)\)|\"([^\"]+)\"", core)
    if nick:
        out["nickname"] = next(a or b for a, b in nick)
    core = clean(re.sub(r"\([^)]*\)|\"[^\"]*\"", " ", core))
    while _RANK_RE.match(core):
        core = _RANK_RE.sub("", core, count=1)
    toks = core.split()
    if not toks:
        return out
    # Last name absorbs lowercase particles ("de la Cruz", "Van Hollen").
    i = len(toks) - 1
    while i > 1 and _PARTICLE_RE.match(toks[i - 1]):
        i -= 1
    out["name_last"] = " ".join(toks[i:])
    out["name_first"] = toks[0] if i > 0 else ""
    out["name_middle"] = " ".join(toks[1:i]) if i > 1 else ""
    out["name_suffix"] = ", ".join(suffixes)
    return out


def office_title_for(o: Official) -> str:
    if o.extra.get("office_title"):
        return o.extra["office_title"]
    role = o.role or ""
    if o.is_ex_officio:
        return "Member (ex officio)"
    if re.match(r"^Chief (?:Justice|Judge)\b", role):
        return role
    if not role or OFFICER_ROLES.match(role) or re.match(r"^(member|members)\b", role, re.I):
        return "Member"
    if re.search(r"\bstudent\b", role, re.I):
        return "Student Member"
    if re.match(r"^(designee|representative|representing)\b", role, re.I):
        return "Member"
    return role


def _page_body(html: str, fallback: str) -> str:
    """First real heading on the page (h1-h3), else the <title>."""
    for line in tokenize(html)[:60]:
        if line.heading and line.heading_level <= 3:
            t = line.text
            if t and not re.search(r"maryland manual|search the manual", t, re.I):
                return smart_title(t)
    return fallback


def _muni_name(title: str) -> str:
    t = re.sub(r",?\s*Maryland.*$", "", title).strip()
    return t or title


def iter_pages():
    conn = sqlite3.connect(MANIFEST)
    rows = conn.execute(
        "SELECT url, cache_path FROM pages WHERE status=200 AND cache_path IS NOT NULL ORDER BY url"
    ).fetchall()
    conn.close()
    for url, cpath in rows:
        p = Path(cpath)
        if p.exists():
            yield url, decode_page(p.read_bytes())


def build() -> tuple[list[dict], dict]:
    reg = load_registry()
    rows: list[dict] = []
    bios: dict[str, dict] = {}
    leaders: dict[str, list[str]] = defaultdict(list)
    stats = Counter()
    page_counts: dict[str, int] = {}

    def emit(o: Official, url: str, html_title: str, *, level: str, jurisdiction: str,
             jurisdiction_id: str | None, branch: str, parent_body: str):
        body = o.body or parent_body
        bio = _abs(o.bio_url, url)
        rec = {
            "person_id": person_id(o, body, url) if not o.is_vacancy else None,
            "name_full": o.name,
            **split_name(o.name),
            "office_title": office_title_for(o),
            "role": o.role,
            "role_note": o.role_note,
            "body_name": body,
            "parent_body": parent_body if parent_body != body else "",
            "jurisdiction_level": level,
            "jurisdiction": jurisdiction,
            "jurisdiction_id": jurisdiction_id,
            "branch": branch,
            "selection_method": o.selection_method,
            "appointing_authority": o.appointing_authority,
            "selection_text": o.selection_text,
            "party": o.party,
            "party_source": "roster" if o.party else None,
            "district": o.district,
            "counties": o.extra.get("counties_text", ""),
            "term_length_years": o.term_length_years,
            "term_start": o.extra.get("term_start"),
            "term_end_year": o.term_end_year,
            "is_vacancy": int(o.is_vacancy),
            "is_ex_officio": int(o.is_ex_officio),
            "note": o.note,
            "bio_url": bio,
            "record_type": "committee" if leg.COMMITTEE_PAGE_RE.search(url) else "office",
            "source_url": url + (f"#{o.section_anchor}" if o.section_anchor else ""),
            "evidence": o.evidence,
            "page_date": None,
        }
        rows.append(rec)

    for url, html in iter_pages():
        path = url.replace(BASE, "")
        if BIO_ID_RE.search(path):
            m = BIO_ID_RE.search(path)
            bios[url] = parse_bio(html)
            stats["bios"] += 1
            continue
        if SKIP_PAGE_RE.search(path):
            continue
        title = page_title(html)
        before = len(rows)

        if leg.DISTRICT_PAGE_RE.search(path):
            for o in leg.parse_district_page(url, html):
                emit(o, url, title, level="state", jurisdiction="Maryland", jurisdiction_id="state:md",
                     branch="legislative", parent_body="General Assembly")
        elif LEADERS_PAGE_RE.search(path):
            for o in parse_roster(html, title):
                if o.bio_url and o.role:
                    leaders[_abs(o.bio_url, url)].append(o.role)
            continue
        elif m := COUNTY_PAGE_RE.search(path):
            code, kind = m.group(1).lower(), m.group(2).lower()
            county = reg.by_abbrev(code)
            cname = county.name if county else code
            parent = _page_body(html, title)
            for o in parse_roster(html, cname, head_titles=HEAD_TITLES):
                emit(o, url, title, level="county", jurisdiction=cname,
                     jurisdiction_id=county.id if county else f"county:{code}",
                     branch=COUNTY_BRANCH[kind], parent_body=parent)
        elif m := MUNI_PAGE_RE.search(path):
            full = _muni_name(title)
            mname, _, mcounty = full.partition(", ")
            for o in parse_roster(html, mname, head_titles=HEAD_TITLES):
                o.extra.setdefault("counties_text", mcounty)
                emit(o, url, title, level="municipal", jurisdiction=mname,
                     jurisdiction_id=f"municipality:{slugify(mname)}",
                     branch="municipal", parent_body=mname)
        else:
            parent = _page_body(html, title)
            branch = next((b for rx, b in STATE_BRANCH if rx.search(path)), "executive")
            for o in parse_roster(html, parent, head_titles=HEAD_TITLES):
                emit(o, url, title, level="state", jurisdiction="Maryland", jurisdiction_id="state:md",
                     branch=branch, parent_body=parent)
        page_counts[url] = len(rows) - before
        stats["pages"] += 1

    # Leadership roles onto legislator rows.
    for r in rows:
        if r["branch"] == "legislative" and r["office_title"] in ("State Senator", "Delegate"):
            roles = leaders.get(r["bio_url"] or "")
            if roles:
                r["role"] = "; ".join(dict.fromkeys(roles))

    # Biography enrichment.
    for r in rows:
        b = bios.get(r["bio_url"] or "")
        if not b:
            continue
        if not r["party"] and b.get("party"):
            r["party"] = b["party"]
            r["party_source"] = "bio"
        if not r["term_start"] and b.get("since_date"):
            r["term_start"] = b["since_date"]
            r["term_start_title"] = b.get("since_title")
        r["page_date"] = b.get("page_date")
    for r in rows:
        r.setdefault("term_start_title", None)
        ts = r.get("term_start")
        if ts and not re.match(r"^\d{4}", ts):
            from .parse_bio import _iso
            r["term_start"] = _iso(ts)

    # Constitutionally elected offices sometimes lack an "Elected by Voters" label.
    for r in rows:
        if not r["selection_method"] and r["jurisdiction_level"] in ("county", "municipal") \
                and ELECTED_OFFICES.match(r["office_title"] or ""):
            r["selection_method"] = "elected"
            r["appointing_authority"] = "Voters"
            r["selection_text"] = "(inferred: office is elected)"

    rows = [r for r in rows if not STAFF_BODY_RE.search(r["body_name"] or "")]
    link_names_to_bios(rows)
    mark_ex_officio_officers(rows)
    rows = dedupe(rows)
    rows = dedupe_offices(rows)
    stats["rows"] = len(rows)
    stats["zero_yield_pages"] = sum(1 for n in page_counts.values() if n == 0)
    return rows, {"stats": dict(stats), "page_counts": page_counts}


STAFF_BODY_RE = re.compile(r"\b(?:Analysts?|Staff|Personnel|Employees)\b", re.I)
_STOP = {"of", "the", "and", "for", "on", "in", "to", "office", "state", "maryland", "&", "acting",
         "interim", "board", "commission", "council", "department", "dept."}


def _words(text: str) -> set[str]:
    t = (text or "").lower().replace("lt.", "lieutenant")
    return {w for w in re.findall(r"[a-z.']+", t) if w not in _STOP and len(w) > 2}


def link_names_to_bios(rows: list[dict]) -> None:
    """Give unlinked rows the bio id of the one linked person with the same full name."""
    ids: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r["person_id"] and r["person_id"].startswith("person:msa"):
            ids[r["name_full"]].add(r["person_id"])
    for r in rows:
        r["person_id_method"] = "bio_link" if r["bio_url"] else None
        if r["person_id"] and "@" in r["person_id"]:
            cand = ids.get(r["name_full"], set())
            if len(cand) == 1 and len(r["name_full"].split()) >= 3:
                r["person_id"] = next(iter(cand))
                r["person_id_method"] = "name_match"
            else:
                r["person_id_method"] = "local"


def mark_ex_officio_officers(rows: list[dict]) -> None:
    """A statewide or county officer listed on some other body sits there by virtue
    of office: record the seat as an ex officio membership, not the office itself."""
    for r in rows:
        title = r["office_title"] or ""
        if not HEAD_TITLES.match(title) or r["body_name"] in ("(cabinet)",):
            continue
        if _words(title) & _words(r["body_name"]) or _words(title) & _words(r["parent_body"]):
            continue
        if r["selection_method"] in ("elected", "appointed", "appointed/elected"):
            continue
        r["office_title"] = "Member (ex officio)"
        r["is_ex_officio"] = 1
        r["role_note"] = "; ".join(x for x in (title, r["role_note"]) if x)
        if r["role"] == title:
            r["role"] = ""
        if not r["selection_method"]:
            r["selection_method"] = "ex officio"


def dedupe_offices(rows: list[dict]) -> list[dict]:
    """One person, one named office (not a board seat): keep the richest row."""
    best: dict[tuple, int] = {}
    keep = [True] * len(rows)
    for i, r in enumerate(rows):
        if r["is_vacancy"] or not (r["person_id"] or "").startswith("person:msa"):
            continue
        if r["office_title"].startswith("Member") or r["record_type"] == "committee":
            continue
        key = (r["person_id"], r["office_title"], r["jurisdiction_id"])
        if key in best:
            j = best[key]
            if (_richness(r), len(r["name_full"])) > (_richness(rows[j]), len(rows[j]["name_full"])):
                keep[j] = False
                best[key] = i
            else:
                keep[i] = False
        else:
            best[key] = i
    return [r for r, k in zip(rows, keep) if k]


def _richness(r: dict) -> int:
    keys = ("selection_method", "term_end_year", "party", "district", "role", "bio_url", "term_length_years")
    return sum(1 for k in keys if r.get(k))


def dedupe(rows: list[dict]) -> list[dict]:
    """Collapse repeats of the same person in the same body.

    Pages often list a head twice (a summary line at the top, then the full
    roster entry), and some boards appear on more than one page.
    """
    best: dict[tuple, dict] = {}
    order: list[tuple] = []
    for i, r in enumerate(rows):
        if r["is_vacancy"]:
            key = ("vacancy", i)
        else:
            key = (r["person_id"].split("@")[0], slugify(r["body_name"]), r["jurisdiction_id"],
                   slugify(r["office_title"]))
        if key not in best:
            best[key] = r
            order.append(key)
        else:
            cur = best[key]
            if _richness(r) > _richness(cur):
                # Keep the richer row but don't lose a role from the poorer one.
                if not r["role"] and cur["role"]:
                    r["role"] = cur["role"]
                best[key] = r
    return [best[k] for k in order]


if __name__ == "__main__":
    rows, info = build()
    s = info["stats"]
    print(s)
    print(Counter(r["jurisdiction_level"] for r in rows))
    print(Counter(r["branch"] for r in rows))
