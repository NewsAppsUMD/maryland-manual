"""Ground-truth assertions against the built graph (data/manual.db).

These require a crawl + load to have run (the cache and DB are gitignored), so
they skip gracefully when the DB is absent. Run `make site` first, then
`make test`.
"""

import json
import sqlite3
from pathlib import Path

import pytest

DB = Path("data/manual.db")
def _graph_built() -> bool:
    if not DB.exists():
        return False
    with sqlite3.connect(DB) as c:
        return c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entities'").fetchone() is not None


pytestmark = pytest.mark.skipif(not _graph_built(),
                                reason="data/manual.db not built (run `make load`)")


@pytest.fixture(scope="module")
def conn():
    c = sqlite3.connect(DB)
    yield c
    c.close()


def q(conn, sql, *args):
    return conn.execute(sql, args).fetchall()


def test_24_counties(conn):
    (n,) = q(conn, "SELECT COUNT(*) FROM entities WHERE type='county'")[0]
    assert n == 24


def test_all_edges_resolve_to_entities(conn):
    """No dangling edge endpoints — every source/target is a known entity."""
    dangling = q(conn, """
        SELECT COUNT(*) FROM edges e
        WHERE NOT EXISTS (SELECT 1 FROM entities WHERE id = e.source_id)
           OR NOT EXISTS (SELECT 1 FROM entities WHERE id = e.target_id)
    """)[0][0]
    assert dangling == 0


def test_adjacency_is_symmetric(conn):
    adj = set(q(conn, "SELECT source_id, target_id FROM edges WHERE type='adjacent_to'"))
    asym = [(a, b) for (a, b) in adj if (b, a) not in adj]
    assert asym == [], f"asymmetric adjacency: {asym[:5]}"


def test_howard_regex_adjacency_matches_its_own_page(conn):
    """The neighbors stated on Howard's own page (regex method, not the derived
    reciprocals) are exactly the five expected counties."""
    rows = q(conn, """
        SELECT target_id FROM edges
        WHERE source_id='county:howard' AND type='adjacent_to' AND method='regex'
    """)
    stated = {r[0] for r in rows}
    assert stated == {
        "county:baltimore", "county:carroll", "county:anne-arundel",
        "county:prince-george-s", "county:montgomery",
    }


def test_every_county_has_a_form_of_government(conn):
    """No silent gaps: all 24 jurisdictions — including the sui-generis
    Baltimore City — get a parsed form of government, and the mix matches the
    Manual (11 charter counties + chartered Baltimore City, plus code-home-rule
    and commissioner counties)."""
    rows = q(conn, "SELECT attrs FROM entities WHERE type='county'")
    cats = {}
    for (attrs,) in rows:
        a = json.loads(attrs) if attrs else {}
        cat = (a.get("form_of_government") or {}).get("category", "unknown")
        cats[cat] = cats.get(cat, 0) + 1
    assert cats.get("unknown", 0) == 0
    assert cats.get("charter", 0) >= 11        # 11 charter counties + Baltimore City
    assert cats.get("commission", 0) >= 5
    assert cats.get("code-home-rule", 0) >= 5
    assert sum(cats.values()) == 24


def test_governor_appoints_multiple_departments(conn):
    n = q(conn, """
        SELECT COUNT(DISTINCT target_id) FROM edges
        WHERE source_id='office:governor' AND type='appoints'
    """)[0][0]
    assert n >= 15


def test_every_edge_has_provenance_or_is_derived(conn):
    bad = q(conn, """
        SELECT COUNT(*) FROM edges
        WHERE method != 'derived' AND (provenance_url IS NULL OR provenance_url = '')
    """)[0][0]
    assert bad == 0
