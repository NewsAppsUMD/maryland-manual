"""Officials parsers, run against committed fixtures (no network).

Each fixture is a real Manual page chosen for a markup variant: county
councils with and without districts, courts, municipal wards, boards with
grouped "Terms expire" trailers, party on appointees, cp1252 bytes, etc.
"""

from pathlib import Path

import pytest

from extract import parse_legislature as leg
from extract.officials import dedupe, split_name
from extract.parse_bio import parse_bio
from extract.patterns import decode_page
from extract.roster import parse_entry, parse_roster, tokenize

FIX = Path(__file__).parent / "fixtures"
B = "https://msa.maryland.gov/msa/mdmanual/"


def page(name: str) -> str:
    return decode_page((FIX / name).read_bytes())


def by_name(rows, name):
    hits = [r for r in rows if r.name == name]
    assert hits, f"{name} not found in {[r.name for r in rows]}"
    return hits[0]


# --- decoding --------------------------------------------------------------

def test_decode_page_handles_bom_and_cp1252():
    assert decode_page(b"\xef\xbb\xbfabc") == "abc"
    assert decode_page(b"O\x92Neill") == "O’Neill"


# --- entry grammar ---------------------------------------------------------

@pytest.mark.parametrize("entry,name,party,role,district,year", [
    ("Andrew M. Friedson, (D), \x01Dist. 1\x02", "Andrew M. Friedson", "Democrat", "", "Dist. 1", None),
    ("Bonnie A. Suchman, Esq., 2027", "Bonnie A. Suchman, Esq.", None, "", "", 2027),
    ("Richard Melnick (U), 2026", "Richard Melnick", "Unaffiliated", "", "", 2026),
    ("Paul J. Dollahite,* \x01Register of Wills,\x02 2026", "Paul J. Dollahite", None, "Register of Wills", "", 2026),
    ("Carlos F. Acosta, \x01Associate Judge,\x02 2037", "Carlos F. Acosta", None, "Associate Judge", "", 2037),
    ("Grace Rivera-Oven, \x01President (chosen by Board in Nov., 1-year term), Dist. 1,\x02 2026",
     "Grace Rivera-Oven", None, "President", "Dist. 1", 2026),
    ("Harry M. Huntley (D), \x01Ward 1\x02", "Harry M. Huntley", "Democrat", "", "Ward 1", None),
    ("Kevin M. Atticks, Secretary of Agriculture", "Kevin M. Atticks", None, "Secretary of Agriculture", "", None),
])
def test_parse_entry(entry, name, party, role, district, year):
    (o,) = parse_entry(entry, [], None)
    assert (o.name, o.party, o.role, o.district, o.term_end_year) == (name, party, role, district, year)


def test_parse_entry_vacancies_and_prose():
    assert len(parse_entry("two vacancies", [], None)) == 2
    assert all(o.is_vacancy for o in parse_entry("one vacancy.", [], None))
    assert parse_entry("Circuit Court judges sit as an orphans' court.", [], None) == []
    assert parse_entry("Legislative Committees", [], None) == []


def test_tokenizer_keeps_italics_and_links():
    lines = tokenize('<a href="/x/msa1.html">Jane Q. Doe</a> (D), <i>Sheriff,</i> 2026<br>next')
    assert lines[0].links == [("/x/msa1.html", "Jane Q. Doe")]
    assert "\x01Sheriff,\x02" in lines[0].marked()
    assert lines[1].text == "next"


# --- county pages ----------------------------------------------------------

def test_montgomery_council():
    rows = parse_roster(page("county_mo_l.html"), "Montgomery County")
    council = [r for r in rows if r.body == "County Council" and r.selection_method == "elected"]
    assert len(council) == 11
    pres = by_name(council, "Natali Fani-González")
    assert (pres.party, pres.role, pres.district, pres.term_end_year) == ("Democrat", "President", "Dist. 6", 2026)
    evans = by_name(council, "Shebra L. Evans")
    assert evans.district == "At Large" and "appointed" in evans.note
    # Staff (Clerk with phone) are not members.
    assert not any(r.role == "Clerk" for r in council)
    appeals = [r for r in rows if r.body == "Board of Appeals"]
    assert by_name(appeals, "Richard Melnick").party == "Unaffiliated"


def test_commissioner_counties():
    ga = [r for r in parse_roster(page("county_ga_l.html"), "Garrett County")
          if r.body == "Board of County Commissioners"]
    assert [r.district for r in ga] == ["Dist. 2", "Dist. 1", "Dist. 3"]
    assert all(r.party == "Republican" and r.term_end_year == 2026 for r in ga)
    ke = [r for r in parse_roster(page("county_ke_l.html"), "Kent County")
          if r.body == "Board of County Commissioners"]
    assert len(ke) == 3 and all(r.district == "" for r in ke)


def test_baltimore_county_drops_photo_captions():
    rows = parse_roster(page("county_bco_l.html"), "Baltimore County")
    council = [r for r in rows if r.body == "County Council"]
    assert len(council) == 7
    assert all(r.district.startswith("Councilmanic Dist.") for r in council)


def test_county_judicial_page():
    rows = parse_roster(page("county_mo_j.html"), "Montgomery County")
    sheriff = [r for r in rows if r.role == "Sheriff"]
    assert sheriff[0].name == "Maxwell C. Uy" and sheriff[0].party == "Democrat"
    judges = [r for r in rows if r.body == "Circuit Court" and "Judge" in r.role]
    assert len(judges) > 20
    assert all(r.party is None and r.term_end_year for r in judges)
    bc = parse_roster(page("county_bcity_j.html"), "Baltimore City")
    assert not any("Courthouse" in (r.name + r.role) for r in bc)
    orphans = [r for r in bc if r.body == "Orphans' Court"]
    assert len(orphans) == 3 and orphans[0].role == "Chief Judge"


def test_county_executive_page():
    rows = parse_roster(page("county_mo_e.html"), "Montgomery County")
    exe = by_name(rows, "Marc B. Elrich")
    assert (exe.role, exe.party, exe.term_end_year) == ("County Executive", "Democrat", 2026)
    boe = [r for r in rows if r.body == "Board of Education" and r.selection_method == "elected"]
    assert len(boe) >= 7
    assert by_name(boe, "Natalie J. Zimmerman").district == "Dist. 2"
    sa = [r for r in rows if r.role == "State's Attorney" and r.selection_method == "elected"]
    assert sa and sa[0].name == "John J. McCarthy, Esq."


# --- municipalities --------------------------------------------------------

def test_municipalities():
    ann = [r for r in parse_roster(page("muni_annapolis.html"), "Annapolis")
           if r.body == "Mayor & City Council"]
    assert by_name(ann, "Jared S. Littmann").role == "Mayor"
    assert [r.district for r in ann[1:]] == [f"Ward {i}" for i in range(1, 9)]
    assert by_name(ann, "Karma O'Neill").party == "Democrat"
    acc = parse_roster(page("muni_accident.html"), "Accident")
    assert [r.term_end_year for r in acc] == [2027, 2027, 2027, 2028, 2028]
    rock = [r for r in parse_roster(page("muni_rockville.html"), "Rockville") if r.body == "City Council"]
    assert len(rock) == 7 and all(r.term_end_year == 2027 for r in rock)


# --- state pages -----------------------------------------------------------

def test_legislature_district_pages():
    sen = leg.parse_district_page(B + "05sen/html/sendist.html", page("leg_sendist.html"))
    hse = leg.parse_district_page(B + "06hse/html/hsedist.html", page("leg_hsedist.html"))
    assert len(sen) == 47 and len(hse) == 141
    assert all(r.party and r.district and r.bio_url for r in sen + hse)
    v = by_name(hse, "William M. Valentine")
    assert (v.district, v.party, v.extra["counties_text"]) == ("2A", "Republican", "Frederick & Washington Counties")
    assert all(r.term_end_year == 2027 for r in sen)


def test_legislative_leadership():
    rows = parse_roster(page("leg_sen.html"), "Senate")
    assert by_name(rows, "Bill Ferguson").role == "Senate President"


def test_supreme_court_and_committee_trailers():
    rows = parse_roster(page("court_ap.html"), "Supreme Court of Maryland")
    justices = [r for r in rows if r.body == "Supreme Court of Maryland" and r.term_end_year]
    assert len(justices) == 7
    fader = by_name(justices, "Matthew J. Fader")
    assert fader.district == "3rd Appellate Judicial Circuit" and fader.term_length_years == 10
    ethics = [r for r in rows if r.body == "Judicial Ethics Committee"]
    assert by_name(ethics, "Graham McAleer, Ph.D.").term_end_year == 2027


def test_boards_with_party_and_terms():
    psc = parse_roster(page("agency_psc.html"), "Public Service Commission")
    comm = [r for r in psc if r.body == "Public Service Commission" and r.selection_method == "appointed"]
    assert len(comm) == 5 and by_name(comm, "Kumar P. Barve").role == "Chair"
    sbe = parse_roster(page("agency_elections.html"), "State Board of Elections")
    board = [r for r in sbe if r.body == "State Board of Elections"]
    assert [r.party for r in board] == ["Democrat", "Republican", "Republican", "Democrat", "Democrat"]
    dag = parse_roster(page("agency_dag.html"), "Department of Agriculture")
    mac = [r for r in dag if r.body == "Maryland Agricultural Commission"]
    assert by_name(mac, "Marianne Bailey, D.V.M.").term_end_year == 2024
    assert any(r.is_vacancy for r in mac)
    assert any(r.is_ex_officio for r in mac)


def test_cabinet():
    rows = parse_roster(page("exec_cabinet.html"), "Executive Council")
    names = [r.name for r in rows]
    assert "Wes Moore" in names and "Kevin M. Atticks" in names
    assert not any("Defunct" in n for n in names)


# --- biographies, names, dedupe -------------------------------------------

def test_bios():
    sen = parse_bio(page("bio_senator.html"))
    assert sen["party"] == "Democrat" and sen["district"] == "3" and sen["counties"] == ["fr"]
    assert sen["since_title"] == "Member of Senate" and sen["since_date"] == "2023-01-11"
    sec = parse_bio(page("bio_secretary.html"))
    assert sec["since_title"] == "Secretary of Labor" and sec["party"] is None


def test_split_name():
    n = split_name("Yaakov (Jake) Weissmann, Esq.")
    assert (n["name_first"], n["name_last"], n["nickname"], n["name_suffix"]) == ("Yaakov", "Weissmann", "Jake", "Esq.")
    n = split_name("Kurt Van der Walde")
    assert n["name_last"] == "Van der Walde"
    n = split_name("Lt. Col. Joseph F. Scott, Jr.")
    assert (n["name_first"], n["name_middle"], n["name_last"], n["name_suffix"]) == ("Joseph", "F.", "Scott", "Jr.")
    assert split_name("James A. Kenny III")["name_suffix"] == "III"


def test_dedupe_keeps_richest_and_role():
    base = dict(person_id="person:msa1", body_name="X", jurisdiction_id="state:md", office_title="Member",
                is_vacancy=0, selection_method="", term_end_year=None, party=None, district="",
                role="Chair", bio_url=None, term_length_years=None)
    rich = dict(base, role="", selection_method="appointed", term_end_year=2028)
    (out,) = dedupe([base, rich])
    assert out["term_end_year"] == 2028 and out["role"] == "Chair"


def _row(**kw):
    base = dict(person_id="person:x@b", name_full="Aruna K. Miller", office_title="Lt. Governor",
                role="Lt. Governor", role_note="", body_name="Maryland 250 Commission", parent_body="",
                selection_method="", is_ex_officio=0, bio_url=None, is_vacancy=0)
    base.update(kw)
    return base


def test_officer_on_other_body_is_ex_officio():
    from extract.officials import mark_ex_officio_officers
    seat = _row()
    own = _row(body_name="Lieutenant Governor")
    judge = _row(office_title="Chief Justice", role="Chief Justice", body_name="Supreme Court of Maryland",
                 selection_method="appointed/elected")
    mark_ex_officio_officers([seat, own, judge])
    assert (seat["office_title"], seat["is_ex_officio"], seat["role_note"]) == ("Member (ex officio)", 1, "Lt. Governor")
    assert own["office_title"] == "Lt. Governor"
    assert judge["office_title"] == "Chief Justice"


def test_unlinked_names_join_unique_bio():
    from extract.officials import link_names_to_bios
    linked = _row(person_id="person:msa15449", bio_url="https://x/msa15449.html")
    same = _row()
    short = _row(name_full="John Smith", person_id="person:john-smith@b")
    link_names_to_bios([linked, same, short])
    assert same["person_id"] == "person:msa15449" and same["person_id_method"] == "name_match"
    assert short["person_id_method"] == "local"
