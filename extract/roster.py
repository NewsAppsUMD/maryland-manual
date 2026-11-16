"""Shared roster grammar for Maryland Manual pages that list office-holders.

The Manual's rosters are hand-written HTML with no classes, unbalanced <ul>
nesting and stray </a> and </i> tags, so a DOM walk is unreliable. Instead:

1. ``tokenize()`` walks the raw tags with a regex and emits *lines* (split at
   <br>, <p>, <li>, headings and other block tags). Each line is a list of
   segments: (text, italic, href). Named anchors and headings are kept.
2. ``parse_roster()`` runs a small state machine over the lines. It tracks the
   current section (body name), the current selection block ("Appointed by
   Governor with Senate advice & consent to 4-year terms:"), and turns each
   member entry into an ``Official`` record.

Party, district and term are written inline, e.g.::

    <a href=".../msa18472.html">Natali Fani-Gonz&#225;lez</a> (D),
        <i>President (chosen by Council in Dec., 1-year term), Dist. 6</i><br>
    Bonnie A. Suchman, Esq., 2027; Frederick H. Hoover, Esq., 2029.
    Marianne Bailey, D.V.M.; one vacancy. <i>Terms expire 2024.</i>
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .patterns import clean, unescape

# --- Tokenizer -------------------------------------------------------------

_TAG_RE = re.compile(
    r"<!--.*?-->|<(script|style|title)\b[^>]*>.*?</\1\s*>|<(/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>",
    re.S | re.I,
)
_HREF_RE = re.compile(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
_NAME_RE = re.compile(r"""name\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title", re.S | re.I)

_BREAK_TAGS = {
    "br", "p", "li", "dt", "dd", "ul", "ol", "dl", "hr", "div", "table", "tr",
    "td", "th", "center", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
}
# Tags at which an unclosed <i> is forgiven.
_ITALIC_RESET = {"p", "li", "hr", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4"}


@dataclass
class Seg:
    text: str
    italic: bool = False
    href: str | None = None
    bold: bool = False


@dataclass
class Line:
    segs: list[Seg] = field(default_factory=list)
    anchor: str | None = None      # last <a name=...> seen before this line
    heading: bool = False          # came from <h1>-<h4>
    heading_level: int = 0

    @property
    def text(self) -> str:
        return clean("".join(s.text for s in self.segs))

    @property
    def links(self) -> list[tuple[str, str]]:
        out = []
        for s in self.segs:
            if s.href and s.text.strip():
                if out and out[-1][0] == s.href:
                    out[-1] = (s.href, out[-1][1] + s.text)
                else:
                    out.append((s.href, s.text))
        return [(h, clean(t)) for h, t in out]

    def marked(self) -> str:
        """Text with italic runs wrapped in \\x01 ... \\x02."""
        out = []
        prev_italic = False
        for s in self.segs:
            if s.italic and not prev_italic:
                out.append("\x01")
            elif not s.italic and prev_italic:
                out.append("\x02")
            out.append(s.text)
            prev_italic = s.italic
        if prev_italic:
            out.append("\x02")
        txt = "".join(out).replace("\xa0", " ")
        txt = re.sub(r"\s+", " ", txt)
        # Normalize whitespace around markers.
        txt = re.sub(r"\x01\s*\x02", "", txt)
        return txt.strip()


def page_title(html: str) -> str:
    m = _TITLE_RE.search(html)
    return clean(unescape(m.group(1))) if m else ""


def _attr(rx: re.Pattern, attrs: str) -> str | None:
    m = rx.search(attrs)
    if not m:
        return None
    return next(g for g in m.groups() if g is not None)


def tokenize(html: str) -> list[Line]:
    lines: list[Line] = []
    cur = Line()
    italic = 0
    bold = 0
    href: str | None = None
    anchor: str | None = None
    heading_level = 0

    def flush():
        nonlocal cur
        if any(s.text.strip() for s in cur.segs):
            lines.append(cur)
        cur = Line(anchor=anchor, heading=heading_level > 0, heading_level=heading_level)

    def add_text(raw: str):
        if not raw:
            return
        txt = unescape(raw)
        if not txt:
            return
        if not cur.segs:
            cur.anchor = anchor
            cur.heading = heading_level > 0
            cur.heading_level = heading_level
        cur.segs.append(Seg(txt, italic > 0, href, bold > 0))

    pos = 0
    for m in _TAG_RE.finditer(html):
        add_text(html[pos:m.start()])
        pos = m.end()
        if m.group(1) or m.group(0).startswith("<!--"):
            continue  # comment, script, style or title
        closing = m.group(2) == "/"
        tag = m.group(3).lower()
        attrs = m.group(4) or ""
        if tag in ("i", "em"):
            italic = max(0, italic - 1) if closing else italic + 1
            continue
        if tag in ("b", "strong"):
            bold = max(0, bold - 1) if closing else bold + 1
            continue
        if tag == "a":
            if closing:
                href = None
            else:
                h = _attr(_HREF_RE, attrs)
                if h is not None:
                    href = h
                n = _attr(_NAME_RE, attrs)
                if n is not None:
                    anchor = n
                    if not cur.segs:
                        cur.anchor = anchor
            continue
        if tag in _BREAK_TAGS:
            flush()
            if tag in _HEADING_TAGS:
                heading_level = 0 if closing else int(tag[1])
                cur.heading = heading_level > 0
                cur.heading_level = heading_level
            if tag in _ITALIC_RESET:
                italic = 0
                bold = 0
            if tag in ("li", "p", "hr"):
                href = None
    add_text(html[pos:])
    flush()
    return lines


# --- Entry grammar ---------------------------------------------------------

PARTY_CODES = {
    "D": "Democrat", "R": "Republican", "U": "Unaffiliated", "I": "Independent",
    "G": "Green", "L": "Libertarian", "O": "Other", "N": "Nonpartisan",
    "DEMOCRAT": "Democrat", "REPUBLICAN": "Republican",
    "UNAFFILIATED": "Unaffiliated", "INDEPENDENT": "Independent",
    "GREEN": "Green", "LIBERTARIAN": "Libertarian",
}
PARTY_RE = re.compile(
    r"\(\s*(D|R|U|I|G|L|Democrat|Republican|Unaffiliated|Independent|Green|Libertarian)\s*\)",
)

# Name suffixes and post-nominals that follow a comma but belong to the name.
SUFFIXES = {
    "jr", "sr", "ii", "iii", "iv", "v", "esq", "ph.d", "phd", "m.d", "md", "d.o",
    "ed.d", "edd", "d.v.m", "dvm", "j.d", "jd", "r.n", "rn", "c.p.a", "cpa",
    "m.p.h", "mph", "d.d.s", "dds", "pharm.d", "d.n.p", "dnp", "psy.d", "p.e",
    "pe", "m.s.w", "msw", "l.c.s.w-c", "lcsw-c", "lcsw", "d.min", "m.b.a", "mba",
    "aia", "faia", "fache", "aicp", "r.a", "ret", "usn", "usa", "usaf", "usmc",
    "d.p.m", "o.d", "d.c", "m.s", "m.a", "b.s", "d.sc", "sc.d", "llm", "ll.m",
    "d.p.t", "dpt", "n.p", "np", "pa-c", "crnp", "m.ed", "m.p.a", "mpa", "cfp",
    "msn", "bsn", "dnp", "facs", "faap", "facp", "drph", "dr.p.h", "pharmd",
}
_SUFFIX_RE = re.compile(r"^[A-Za-z.\-]+$")

VACANCY_RE = re.compile(
    r"^(?:(?P<word>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)\s+)?"
    r"vacanc(?:y|ies)\b",
    re.I,
)
_NUMWORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}

TERM_EXPIRES_RE = re.compile(r"\bTerms?\s+expires?\s+(?:[A-Z][a-z]+\.?\s+\d{1,2},\s+)?(\d{4})\.?", re.I)
YEAR_TAIL_RE = re.compile(r"[,\s]\s*((?:19|20)\d{2})\s*\.?\s*$")
ADDRESS_RE = re.compile(
    r"\b(?:Courthouse|Court House|Building|Room\s+\d|Suite|St\.|Ave\.|Street|Avenue|Blvd\.?|"
    r"Road|Rd\.|Drive|Dr\.,|P\.\s?O\.\s+Box|Box\s+\d|Plaza|Center|Complex)\b|\bMD\s+\d{5}|\b\d{5}(?:-\d{4})?\b"
)
PHONE_RE = re.compile(r"\(\d{3}\)\s*\d{3}-\d{4}|\b\d{3}-\d{3}-\d{4}\b|\be-?mail:|\bweb:|\bfax\b", re.I)

DISTRICT_RE = re.compile(
    r"(?P<d>(?:Councilmanic\s+)?Dist(?:rict)?\.?\s*[0-9]+[A-Z]?\.?"
    r"|At[- ]Large|Ward\s+[0-9IVX]+[A-Z]?|Precinct\s+\d+"
    r"|\d+(?:st|nd|rd|th)\s+(?:Appellate\s+)?Judicial\s+Circuit"
    r"|(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth)\s+(?:Appellate\s+)?Judicial\s+Circuit)",
    re.I,
)

# Words that never appear in a person's name: used to reject prose lines.
NON_NAME_WORDS = re.compile(
    r"\b(?:Courts?|County|Counties|Boards?|Departments?|Offices?|Commissions?|Committees?|"
    r"Subcommittees?|Councils?|Maryland|States?|Divisions?|Administrations?|Agency|Agencies|"
    r"Authority|Programs?|Centers?|Universit(?:y|ies)|Colleges?|Associations?|Inc|LLC|"
    r"Foundations?|Senate|Government|Annapolis|Street|Road|Avenue|Suite|Building|Room|"
    r"P\.\s?O\.|Box|Library|Schools?|Hospitals?|Services?|Funds?|Corporations?|Institutes?|"
    r"Society|Federation|Bureau|Units?|Sections?|Branch|Task|Members?|Chairs?|"
    r"Designees?|Representatives?|Secretary|Director|President|Judges|Assembly|"
    r"Legislative|Process|Health|Behavioral|Criminal|Defunct|Commissioners?|Delegates?|"
    r"Senators?|Staff|Vacanc(?:y|ies)|Terms?|Elected|Appointed|Ex\s+officio|Region(?:al)?|"
    r"District|Districts|Precinct|Census|Population|Budget|Reports?|Functions|History)\b"
)
_PARTICLES = {"de", "da", "del", "della", "der", "di", "du", "la", "le", "van", "von",
              "y", "st.", "dos", "das", "bin", "ibn", "al", "el", "ten", "ter", "zu", "and"}

OFFICER_ROLES = re.compile(
    r"^(Chair|Co-Chair|Vice[- ]Chair|President|Vice[- ]President|Secretary|Treasurer|"
    r"Secretary-Treasurer|Chair Pro Tem(?:pore)?|President Pro Tem(?:pore)?|Speaker Pro Tem(?:pore)?|"
    r"Presiding Officer|Vice-Presiding Officer|Chief Judge|Chief Justice|Parliamentarian|"
    r"Majority Leader|Minority Leader|Deputy Majority Leader|Deputy Minority Leader|"
    r"Majority Whip|Minority Whip|Deputy Majority Whip|Deputy Minority Whip|Co-Chairs?|"
    r"Vice-Chairs?|Chairs?)\b",
    re.I,
)

# Labels that open a selection block.
LABEL_START_RE = re.compile(
    r"^(Elected|Appointed|Ex officio|Ex-officio|Representing|Nominated|Chosen|Designated|"
    r"Selected|Serving|Members?|Nonvoting|Non-voting|Advisory|Senior Judge|Associate|"
    r"Student|Co-Chairs?|Chairs?|Vice-Chairs?|Secretary|Treasurer|Designees?|Staff|"
    r"Legislative|Public|Commissioners?|Delegates?|Senators?|Judges?|Alternates?|"
    r"Consultants?|Liaisons?|Advisors?|Officers?|Trustees?)\b",
    re.I,
)
_LEADING_STARS = re.compile(r"^\*+\s*")
FOOTNOTE_RE = re.compile(r"^\*+\s*\(|^\((?:appointed|elected|sworn|resigned|died|chosen|named|served|term)", re.I)
TERM_LEN_RE = re.compile(r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen)[- ]year\s+terms?", re.I)
_TERM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
               "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15}


@dataclass
class Block:
    label: str = ""
    method: str = ""               # elected | appointed | ex officio | other
    authority: str = ""
    term_years: int | None = None


@dataclass
class Official:
    name: str
    party: str | None = None
    role: str = ""                 # e.g. Chair, Associate Judge, Sheriff
    role_note: str = ""            # e.g. "chosen by Council in Dec., 1-year term"
    district: str = ""
    term_end_year: int | None = None
    body: str = ""
    section_anchor: str | None = None
    selection_method: str = ""
    appointing_authority: str = ""
    selection_text: str = ""
    term_length_years: int | None = None
    is_vacancy: bool = False
    is_ex_officio: bool = False
    bio_url: str | None = None
    note: str = ""
    stars: int = 0
    evidence: str = ""
    extra: dict = field(default_factory=dict)


def parse_block_label(label: str) -> Block:
    lab = clean(label).rstrip(":").strip()
    low = lab.lower()
    b = Block(label=lab)
    m = TERM_LEN_RE.search(lab)
    if m:
        v = m.group(1).lower()
        b.term_years = int(v) if v.isdigit() else _TERM_WORDS.get(v)
    if low.startswith(("ex officio", "ex-officio")):
        b.method = "ex officio"
    elif low.startswith("elected") or " elected by " in f" {low} ":
        b.method = "elected"
        m = re.search(r"elected by\s+(?:the\s+)?(.+?)(?:\s+to\s+\S+[- ]year|\s+for\s+|\s*\(|$)", lab, re.I)
        b.authority = clean(m.group(1)) if m else ""
        if low.startswith("appointed"):
            b.method = "appointed/elected"
            m2 = re.search(r"appointed by\s+(?:the\s+)?(.+?)(?:\s+with\s+|\s*&|\s+and\s+|\s+to\s+|$)", lab, re.I)
            if m2:
                b.authority = clean(m2.group(1)) + (" / " + b.authority if b.authority else "")
    elif low.startswith(("appointed", "nominated", "chosen", "designated", "selected", "named")) \
            or re.search(r"\bappointed by\b", low):
        b.method = "appointed"
    elif low.startswith("representing"):
        b.method = "appointed"
        b.authority = ""
    elif low.startswith("staff"):
        b.method = "staff"
    elif LABEL_START_RE.match(lab) and not re.search(r"left to right|photo|meet(?:s|ings?)\b", low):
        b.method = "other"
    else:
        b.method = "ignore"
    if b.method.startswith("appointed") and not b.authority:
        m = re.search(
            r"(?:appointed|nominated|chosen|designated|selected|named)\s+by\s+(?:the\s+)?"
            r"(.+?)(?:\s+with\s+|\s+to\s+(?:\S+[- ]year|serve|\d)|\s*\(|,\s*(?:upon|on|from|with)\b|$)",
            lab, re.I)
        if m:
            b.authority = clean(m.group(1)).rstrip(",")
    return b


def _split_top(text: str, sep: str = ";") -> list[str]:
    """Split on sep outside parentheses."""
    parts, depth, buf = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p for p in (x.strip() for x in parts) if p]


def is_suffix(tok: str) -> bool:
    t = tok.strip().rstrip(".").lower().replace(" ", "")
    return t in SUFFIXES or bool(re.fullmatch(r"(?:[a-z]\.){2,4}[a-z]?", t + "."))  and len(t) <= 8


def looks_like_name(name: str) -> bool:
    n = name.strip()
    if not n or len(n) > 70 or len(n) < 3:
        return False
    if re.search(r"\d", n):
        return False
    letters = [c for c in n if c.isalpha()]
    if len(letters) > 4 and all(c.isupper() for c in letters):
        return False
    if NON_NAME_WORDS.search(n):
        return False
    base = re.sub(r"\([^)]*\)", " ", n)          # nicknames in parentheses
    base = re.sub(r"\"[^\"]*\"", " ", base)
    base = base.split(",")[0]
    toks = [t for t in re.split(r"\s+", base) if t]
    if len(toks) < 2 or len(toks) > 7:
        return False
    if ":" in n or any(not re.match(r"[\"'(]?[^\W\d_]", t) for t in toks):
        return False
    lower_toks = [t for t in toks if t[0].islower() and t.lower() not in _PARTICLES]
    if lower_toks:
        return False
    if not any(len(t.strip(".")) > 1 for t in toks):
        return False
    return True


def fix_apostrophes(text: str) -> str:
    text = re.sub(r"(?<=\w)\ufffd(?=\w)", "'", text)
    return text.replace("\u2019", "'").replace("\u2018", "'")


_PLAIN_LABEL_RE = re.compile(r"^([A-Z][A-Za-z.\- ]{2,40}):\s+(?=\S)")


def split_name_and_rest(text: str) -> tuple[str, str]:
    """Split 'Name, Esq., Title words' into ('Name, Esq.', 'Title words')."""
    parts = [p.strip() for p in text.split(",")]
    name = parts[0]
    i = 1
    while i < len(parts) and parts[i] and is_suffix(parts[i]):
        name += ", " + parts[i]
        i += 1
    return name.strip(), ", ".join(p for p in parts[i:] if p)


_DOTTED = {"jr", "sr", "esq"}


def _fix_suffix_periods(name: str) -> str:
    parts = [p.strip() for p in name.split(",")]
    for i in range(1, len(parts)):
        t = parts[i]
        if is_suffix(t) and not t.endswith(".") and ("." in t or t.lower() in _DOTTED):
            parts[i] = t + "."
    return ", ".join(parts)


_SMALL_WORDS = {"of", "and", "the", "for", "on", "in", "to", "a", "an", "at", "by", "or", "with", "from"}


_ACRONYMS = {
    "usm", "mta", "bwi", "md", "ii", "iii", "iv", "stem", "hiv", "aids", "k-12", "dna", "naacp",
    "lgbtq", "lgbtqia", "lgbtqia+", "9-1-1", "911", "it", "gis", "pfas", "ems", "nasa", "usa",
    "u.s.", "us", "dc", "wmata", "fema", "edu", "sbe", "psc", "mde", "dnr", "mdot", "covid-19",
    "tmdl", "cyber", "abc", "cpr", "hbcu", "hbcus", "aapi", "esg", "ai", "rfp", "llc",
}


def smart_title(text: str) -> str:
    """Title-case an all-caps heading, keeping small words and acronyms sane."""
    if not text.isupper():
        return text
    words = text.lower().split()
    out = []
    for i, w in enumerate(words):
        if i and w in _SMALL_WORDS:
            out.append(w)
        elif "+" in w or w.strip("(),[]:;") in _ACRONYMS:
            out.append(w.upper())
        elif re.fullmatch(r"(?:[a-z]\.){2,}", w):
            out.append(w.upper())
        else:
            out.append("-".join(x[:1].upper() + x[1:] for x in w.split("-")))
    res = " ".join(out)
    res = re.sub(r"'S\b", "'s", res)
    return res


def _strip_role_parens(role: str) -> tuple[str, str]:
    notes = re.findall(r"\(([^)]*)\)", role)
    role = re.sub(r"\s*\([^)]*\)", "", role)
    return clean(role).strip(" ,;."), "; ".join(clean(n) for n in notes)


def parse_entry(entry: str, links: list[tuple[str, str]], block: Block | None) -> list[Official]:
    """Parse one member entry (italic runs marked with \\x01..\\x02)."""
    raw = entry.strip().strip(";").strip()
    plain = clean(raw.replace("\x01", "").replace("\x02", ""))
    if not plain:
        return []
    # Vacancies.
    vm = VACANCY_RE.match(plain.lstrip("*"))
    if vm:
        w = (vm.group("word") or "one").lower()
        n = int(w) if w.isdigit() else _NUMWORDS.get(w, 1)
        rest = plain[vm.end():].strip(" ,.")
        role = ""
        italics = re.findall(r"\x01(.*?)(?:\x02|$)", raw)
        if italics:
            role, _ = _strip_role_parens(italics[0])
        yr = YEAR_TAIL_RE.search(" " + plain)
        out = []
        for _ in range(min(n, 30)):
            o = Official(name="", is_vacancy=True, role=role, evidence=plain)
            if yr:
                o.term_end_year = int(yr.group(1))
            out.append(o)
        return out

    # Stars mark footnotes.
    stars = len(re.findall(r"\*", plain.split("(")[0] if "(" in plain else plain))

    # Year at the end (term expiration).
    year = None
    tmp = raw.replace("*", "")
    tm = TERM_EXPIRES_RE.search(tmp)
    if tm:
        year = int(tm.group(1))
        tmp = tmp[:tm.start()] + tmp[tm.end():]
    flat = clean(tmp.replace("\x01", " \x01").replace("\x02", "\x02 "))
    ym = YEAR_TAIL_RE.search(" " + flat.replace("\x01", "").replace("\x02", ""))
    if ym and year is None:
        year = int(ym.group(1))

    # Separate italic (role/district) text from plain text.
    italic_parts = re.findall(r"\x01(.*?)(?:\x02|$)", flat)
    outside = clean(re.sub(r"\x01.*?(?:\x02|$)", " | ", flat))
    if ym:
        outside = re.sub(r"[,\s]*(?:19|20)\d{2}\s*\.?\s*$", "", outside)
    outside = re.sub(r"(?:\|\s*)+$", "", outside).strip(" ,;.|")

    # Party.
    party = None
    pm = PARTY_RE.search(outside)
    if pm:
        party = PARTY_CODES[pm.group(1).upper()]
        outside = (outside[:pm.start()] + outside[pm.end():])
    # Name is everything before the first italic run (or the whole thing).
    head = outside.split("|")[0]
    tail_plain = " ".join(p.strip(" ,") for p in outside.split("|")[1:])
    head = clean(head).strip(" ,")
    # Inline "(appointed by ...)" or "(elected by ...)" after the title.
    inline_sel = re.findall(r"\(((?:appointed|elected)\s+by[^)]*)\)",
                            plain, re.I)
    head = re.sub(r"\s*\((?:appointed|elected|chosen|designated|nominated)\s+by[^)]*\)", "", head, flags=re.I)
    head = fix_apostrophes(head)
    prefix_role = ""
    lm = _PLAIN_LABEL_RE.match(head)
    if lm and not looks_like_name(lm.group(1)):
        prefix_role = lm.group(1)
        head = head[lm.end():]
    # Co-holders: "Tara N. Phillips & Jena Smith", "Matthew Rose/J. Angel Knight".
    co = re.split(r"\s*/\s*|\s+&\s+", head.split(",")[0])
    if len(co) == 2 and all(looks_like_name(c) for c in co):
        out = []
        tail = head[len(head.split(",")[0]):]
        for c in co:
            out.extend(parse_entry(entry.replace(head.split(",")[0], c, 1), links, block))
        if out:
            return out
    name, rest = split_name_and_rest(head)
    if prefix_role:
        rest = clean(f"{prefix_role}, {rest}").strip(" ,")
    name = clean(name).strip(" ,")
    # Drop a trailing period that isn't part of an abbreviation/suffix.
    if name.endswith(".") and not is_suffix(name.split(",")[-1].split()[-1]) \
            and not re.search(r"\b[A-Z]\.$", name):
        name = name[:-1]
    name = _fix_suffix_periods(name)
    name = re.sub(r"^(?:and|&)\s+", "", name)
    name = re.sub(r"^(?:Sen\.|Del\.|Hon\.|Dr\.|Rev\.|Mr\.|Ms\.|Mrs\.)\s+", "", name)
    # Military ranks in front of a linked name: keep the linked text if present.
    link_url = None
    for href, ltxt in links:
        lt = clean(ltxt).strip(" ,*")
        if lt and (lt in name or name in lt) and len(lt) > 3:
            link_url = href
            if lt != name and name.endswith(lt):
                name = lt
            break
    if not looks_like_name(name):
        return []
    if ADDRESS_RE.search(plain) and not (party or year or link_url):
        return []

    role_text = " ".join(clean(p) for p in italic_parts if clean(p))
    if not role_text:
        role_text = rest
    elif rest:
        role_text = rest + ", " + role_text
    if tail_plain:
        role_text = (role_text + ", " + tail_plain) if role_text else tail_plain
    role_text = re.sub(r"\b(?:19|20)\d{2}\s*\.?\s*$", "", role_text).strip(" ,.;")
    role_text = re.sub(r"(?:,\s*)?Terms?\s+expires?.*$", "", role_text, flags=re.I).strip(" ,.;")
    role_text = PHONE_RE.split(role_text)[0].strip(" ,;")

    district = ""
    dm = DISTRICT_RE.search(role_text)
    if dm:
        district = clean(dm.group("d")).rstrip(".")
        role_text = clean(role_text[:dm.start()] + role_text[dm.end():]).strip(" ,;.")
    role, role_note = _strip_role_parens(role_text)
    role = re.sub(r"^(?:and|&)\s+", "", role).strip(" ,")
    if inline_sel:
        role_note = "; ".join([role_note] + inline_sel).strip("; ")

    o = Official(
        name=name, party=party, role=role, role_note=role_note, district=district,
        term_end_year=year, bio_url=link_url, stars=stars, evidence=plain,
    )
    if inline_sel and (not block or not block.method):
        sb = parse_block_label(inline_sel[0])
        o.selection_method = sb.method
        o.appointing_authority = sb.authority
        o.selection_text = inline_sel[0]
        o.term_length_years = sb.term_years
    return [o]


# --- State machine ---------------------------------------------------------

def _is_heading_text(text: str) -> bool:
    t = re.sub(r"\([^)]*\)", "", text).strip()
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 4 or len(t) > 160:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) > 0.85


def _label_from_line(line: Line) -> tuple[str | None, int]:
    """If the line opens with an italic label ending in ':', return (label, n_segs)."""
    segs = line.segs
    i = 0
    while i < len(segs) and not segs[i].text.strip():
        i += 1
    if i >= len(segs) or not segs[i].italic:
        return None, 0
    label = ""
    j = i
    while j < len(segs) and segs[j].italic:
        label += segs[j].text
        j += 1
    lab = clean(label)
    nxt = segs[j].text.lstrip() if j < len(segs) else ""
    if lab.endswith(":") or nxt.startswith(":"):
        if LABEL_START_RE.match(lab) or len(lab) < 140:
            return lab.rstrip(":"), j
    elif LABEL_START_RE.match(lab) and re.match(r"(Elected|Appointed)\b", lab) and \
            re.search(r"\bterms?\b|\bby\b", lab) and j >= len(segs):
        return lab, j
    return None, 0


@dataclass
class RosterContext:
    page_body: str = ""
    body: str = ""
    anchor: str | None = None
    block: Block | None = None
    block_rows: list[Official] = field(default_factory=list)
    last_rows: list[Official] = field(default_factory=list)
    page_head_done: bool = False


def _finish_row(o: Official, ctx: RosterContext) -> Official:
    o.body = ctx.body or ctx.page_body
    o.section_anchor = ctx.anchor
    b = ctx.block
    if b and b.method:
        if not o.selection_method:
            o.selection_method = b.method
            o.appointing_authority = b.authority
            o.selection_text = b.label
            o.term_length_years = b.term_years
        if b.method == "ex officio":
            o.is_ex_officio = True
        if b.method == "other":
            lab_role, lab_note = _strip_role_parens(b.label)
            if not o.role:
                o.role = lab_role
                o.role_note = "; ".join(x for x in (o.role_note, lab_note) if x)
            elif OFFICER_ROLES.match(lab_role) and not OFFICER_ROLES.match(o.role):
                o.role_note = "; ".join(x for x in (o.role, o.role_note, lab_note) if x)
                o.role = lab_role
    return o


def parse_roster(html: str, page_body: str = "", *, keep_unblocked_links: bool = True,
                 head_titles: re.Pattern | None = None,
                 heading_filter=None) -> list[Official]:
    """Parse every member entry on a roster page.

    keep_unblocked_links: outside any selection block, keep entries whose name
        links to a biography page (e.g. a County Executive or a cabinet
        Secretary listed with phone numbers).
    head_titles: outside blocks, also keep unlinked entries whose role matches
        this pattern.
    heading_filter: optional callable(text) -> bool to decide whether an
        uppercase line is a section heading.
    """
    ctx = RosterContext(page_body=page_body, body=page_body)
    rows: list[Official] = []

    for line in tokenize(html):
        text = line.text
        if not text:
            continue
        if line.anchor != ctx.anchor and line.anchor is not None:
            ctx.anchor = line.anchor
        # Section headings.
        is_heading = (line.heading and line.heading_level <= 3) or (
            _is_heading_text(text) and not PARTY_RE.search(text)
            and not re.search(r"\b(?:19|20)\d{2}\b", text))
        if is_heading and (heading_filter is None or heading_filter(text)):
            ctx.body = smart_title(text)
            ctx.block = None
            ctx.block_rows = []
            ctx.last_rows = []
            continue

        # Footnote lines attach to the starred rows above.
        if FOOTNOTE_RE.match(text):
            n = len(re.match(r"^\**", text).group(0))
            targets = [r for r in ctx.block_rows or ctx.last_rows if n and r.stars == n] or \
                ctx.last_rows[-1:]
            for r in targets:
                r.note = clean((r.note + " " + text.lstrip("*")).strip())
            continue

        # Plain-text "Staff:" lines are never members.
        if re.match(r"^\s*Staff\b", text, re.I):
            continue

        # Pieces of this line: alternate label and entries.
        work_segs = list(line.segs)
        pieces: list[tuple[str, Line]] = []   # ("label"|"entries", Line)
        while work_segs:
            tmp = Line(segs=work_segs, anchor=line.anchor)
            label, n = _label_from_line(tmp)
            if label is not None:
                pieces.append(("label", Line(segs=[Seg(label, True)])))
                rest = work_segs[n:]
                if rest and rest[0].text.lstrip().startswith(":"):
                    rest = [Seg(rest[0].text.lstrip()[1:], rest[0].italic, rest[0].href)] + rest[1:]
                work_segs = rest
                continue
            # Find the next italic label mid-line.
            k = None
            for idx in range(1, len(work_segs)):
                s = work_segs[idx]
                if s.italic and (idx == 0 or not work_segs[idx - 1].italic):
                    cand = Line(segs=work_segs[idx:])
                    lab, _ = _label_from_line(cand)
                    if lab is not None and (LABEL_START_RE.match(lab) or lab.lower().startswith(
                            ("appointed", "elected", "ex officio"))):
                        # Only a label if the preceding text ends an entry.
                        prev = "".join(x.text for x in work_segs[:idx]).rstrip()
                        if not prev or prev[-1] in ".;:)0123456789" or re.search(r"\d{4}\.?$", prev):
                            k = idx
                            break
            if k is None:
                pieces.append(("entries", Line(segs=work_segs, anchor=line.anchor)))
                work_segs = []
            else:
                pieces.append(("entries", Line(segs=work_segs[:k], anchor=line.anchor)))
                work_segs = work_segs[k:]

        for kind, piece in pieces:
            if kind == "label":
                ctx.block = parse_block_label(piece.text)
                ctx.block_rows = []
                continue
            if ctx.block and ctx.block.method in ("staff", "ignore"):
                continue
            ptext = piece.marked()
            if not ptext.strip(" .;,"):
                continue
            # "Terms expire 2026." alone: apply to the current block.
            only_trailer = TERM_EXPIRES_RE.fullmatch(
                clean(ptext.replace("\x01", "").replace("\x02", "")).strip(" .") + ".")
            if only_trailer or re.fullmatch(r"\s*\x01?\s*Terms?\s+expires?\s+\d{4}\.?\s*\x02?\s*", ptext, re.I):
                yr = int(TERM_EXPIRES_RE.search(ptext.replace("\x01", "").replace("\x02", "")).group(1))
                for r in ctx.block_rows:
                    if r.term_end_year is None:
                        r.term_end_year = yr
                continue
            # Drop phone/e-mail tails before splitting on semicolons.
            pm = PHONE_RE.search(ptext)
            has_contact = bool(pm)
            if pm:
                ptext = ptext[:pm.start()]
            # Group trailer: "A; B; C. Terms expire 2027."
            group_year = None
            gm = TERM_EXPIRES_RE.search(ptext.replace("\x01", "").replace("\x02", ""))
            if gm:
                group_year = int(gm.group(1))
                ptext = re.sub(r"\x01?\s*Terms?\s+expires?\s+[^\x02]*?\d{4}\.?\s*\x02?", "", ptext, flags=re.I)
            entries = _split_top(ptext, ";")
            # Unblocked lines are a single entry ("Name, Title").
            if not ctx.block:
                entries = entries[:1]
            links = piece.links
            line_rows: list[Official] = []
            for e in entries:
                for o in parse_entry(e, links, ctx.block):
                    if group_year and o.term_end_year is None:
                        o.term_end_year = group_year
                    line_rows.append(o)
            kept = []
            for o in line_rows:
                if not ctx.block:
                    linked = bool(o.bio_url and re.search(r"/msa\d+\.html$", o.bio_url, re.I))
                    head = bool(head_titles and head_titles.search(o.role or "")) or bool(
                        o.term_end_year and o.role and OFFICER_ROLES.match(o.role)) or bool(
                        o.role and o.selection_method in ("appointed", "elected", "appointed/elected")
                        and not re.match(r"(?:Deputy|Assistant|Associate)\b", o.role))
                    # The first titled entry at the top of a page is the head.
                    if not ctx.page_head_done and o.role and not o.is_vacancy and \
                            not re.match(r"(?:Deputy|Assistant)\b", o.role):
                        head = True
                        ctx.page_head_done = True
                        o.extra["summary_head"] = True
                    if not ((keep_unblocked_links and linked and (o.role or o.party)) or head):
                        continue
                    if has_contact and not linked and not head:
                        continue
                elif has_contact and not (o.term_end_year or o.party or o.bio_url or o.is_vacancy):
                    continue  # staff line inside a membership block
                kept.append(_finish_row(o, ctx))
            rows.extend(kept)
            if kept:
                ctx.page_head_done = True
                ctx.block_rows.extend(kept)
                ctx.last_rows = kept
    # A head listed in the page's opening summary and again in the roster
    # keeps only the roster entry (it carries the term and selection).
    names = Counter(r.name for r in rows if not r.extra.get("summary_head"))
    return [r for r in rows if not (r.extra.get("summary_head") and names[r.name])]
