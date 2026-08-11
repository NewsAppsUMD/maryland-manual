"""Deterministic parser tests against committed fixture HTML.

These run without a crawl — the fixtures are checked in — so a parser change
can't silently regress on the shapes we care about.
"""

from pathlib import Path

import pytest

from extract import parse_agency, parse_county
from extract.registry import load_registry

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def reg():
    return load_registry(index_path=FIX / "index_county.html")


def _edges(result, etype):
    return [e for e in result.edges if e.type == etype]


def test_registry_has_24_counties(reg):
    assert len(reg.counties) == 24


def test_howard_identity(reg):
    html = (FIX / "county_howard.html").read_text()
    r = parse_county.parse(
        "https://msa.maryland.gov/msa/mdmanual/36loc/how/html/how.html", html, reg)
    ent = r.entities[0]
    assert ent.id == "county:howard"
    fog = ent.attrs["form_of_government"]
    assert fog["category"] == "charter"
    assert fog["since"] == 1968
    assert ent.attrs["population"]["2020"] == 332317
    assert ent.attrs["county_seat"].startswith("Ellicott City")


def test_howard_adjacency_includes_baltimore_county(reg):
    """The 'Baltimore & Carroll counties' shared-plural must resolve to
    Baltimore County (not the city), and all five stated neighbors appear."""
    html = (FIX / "county_howard.html").read_text()
    r = parse_county.parse(
        "https://msa.maryland.gov/msa/mdmanual/36loc/how/html/how.html", html, reg)
    neighbors = {e.target_id for e in _edges(r, "adjacent_to")}
    assert neighbors == {
        "county:baltimore", "county:carroll", "county:anne-arundel",
        "county:prince-george-s", "county:montgomery",
    }


def test_howard_created_by_statutes(reg):
    html = (FIX / "county_howard.html").read_text()
    r = parse_county.parse(
        "https://msa.maryland.gov/msa/mdmanual/36loc/how/html/how.html", html, reg)
    laws = _edges(r, "created_by")
    assert any(e.qualifiers.get("year") == 1838 and e.qualifiers.get("chapter") == 22
               for e in laws)
    named = _edges(r, "named_for")
    assert named and named[0].qualifiers["person_name"] == "John Eager Howard"


def test_carroll_is_commission(reg):
    html = (FIX / "county_carroll.html").read_text()
    r = parse_county.parse(
        "https://msa.maryland.gov/msa/mdmanual/36loc/carr/html/carr.html", html, reg)
    assert r.entities[0].attrs["form_of_government"]["category"] == "commission"


def test_aging_department_officials_and_appointment():
    html = (FIX / "agency_aging.html").read_text()
    r = parse_agency.parse(
        "https://msa.maryland.gov/msa/mdmanual/10da/html/da.html", html)
    ent = r.entities[0]
    assert ent.id == "agency:da"
    assert ent.type == "department"
    leads = _edges(r, "leads")
    assert any("Secretary" in e.qualifiers.get("role", "") for e in leads)
    # Governor appoints, with Senate advice & consent somewhere on the page.
    appts = _edges(r, "appoints")
    assert any(e.source_id == "office:governor" for e in appts)
    assert any(e.qualifiers.get("consent") == "senate" for e in appts)
    assert ent.attrs.get("website", "").endswith(("maryland.gov", ".aspx"))
