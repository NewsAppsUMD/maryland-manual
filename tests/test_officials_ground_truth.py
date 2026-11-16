"""Completeness checks on the built officials dataset.

Skipped unless `make crawl-officials officials` has produced the
officeholders table. Counts are facts about Maryland government, not about
the parser, so a failure here means rows were lost or invented.
"""

import sqlite3
from pathlib import Path

import pytest

DB = Path("data/manual.db")


def _built() -> bool:
    if not DB.exists():
        return False
    with sqlite3.connect(DB) as c:
        return bool(c.execute("SELECT count(*) FROM sqlite_master WHERE name='officeholders'").fetchone()[0]) \
            and bool(c.execute("SELECT count(*) FROM officeholders WHERE jurisdiction_level='county'").fetchone()[0])


pytestmark = pytest.mark.skipif(not _built(), reason="officials dataset not built (run `make officials`)")


@pytest.fixture(scope="module")
def db():
    c = sqlite3.connect(DB)
    yield c
    c.close()


def one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def test_legislature_size(db):
    assert one(db, "SELECT count(*) FROM officeholders WHERE office_title='State Senator'") == 47
    assert one(db, "SELECT count(*) FROM officeholders WHERE office_title='Delegate'") == 141
    assert one(db, """SELECT count(*) FROM officeholders WHERE office_title IN ('State Senator','Delegate')
                      AND is_vacancy=0 AND (party IS NULL OR district = '')""") == 0


def test_every_county_has_core_offices(db):
    counties = [r[0] for r in db.execute(
        "SELECT DISTINCT jurisdiction_id FROM officeholders WHERE jurisdiction_level='county'")]
    assert len(counties) == 24
    missing = []
    for cid in counties:
        for label, cond in [
            ("governing body", "branch='legislative' AND selection_method='elected'"),
            ("State's Attorney", "office_title LIKE '%State''s Attorney%' AND selection_method='elected'"),
            ("Sheriff", "office_title LIKE '%Sheriff%' AND selection_method='elected'"),
            ("Clerk", "office_title LIKE '%Clerk%' AND selection_method='elected'"),
            ("Register of Wills", "office_title LIKE '%Register of Wills%'"),
        ]:
            if not one(db, f"SELECT count(*) FROM officeholders WHERE jurisdiction_id=? AND {cond}", cid):
                missing.append((cid, label))
    assert missing == []


def test_every_municipality_has_officials(db):
    n = one(db, "SELECT count(DISTINCT jurisdiction_id) FROM officeholders WHERE jurisdiction_level='municipal'")
    assert n >= 150


def test_supreme_court_and_psc(db):
    assert one(db, """SELECT count(*) FROM officeholders WHERE body_name='Supreme Court of Maryland'
                      AND office_title IN ('Justice','Chief Justice') AND is_vacancy=0""") == 7
    assert one(db, """SELECT count(*) FROM officeholders WHERE body_name='Public Service Commission'
                      AND selection_method='appointed' AND is_vacancy=0""") == 5


def test_statewide_elected(db):
    for title in ("Governor", "Lt. Governor", "Attorney General", "Comptroller of Maryland"):
        assert one(db, "SELECT count(*) FROM officeholders WHERE office_title=?", title) >= 1, title
