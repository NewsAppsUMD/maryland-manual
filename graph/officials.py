"""Write the officials dataset: an `officeholders` table in data/manual.db and
data/officials.csv.

    python -m graph.officials

Reads only the crawl cache (run `python -m crawler.crawl --profile officials`
first). Safe to run on its own: it replaces just the officeholders table, so it
can follow `make load` or run without it.
"""

from __future__ import annotations

import csv
import hashlib
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from extract.officials import build

DB = Path("data/manual.db")
CSV = Path("data/officials.csv")
REPORT = Path("data/officials_coverage.txt")
SCHEMA = Path(__file__).with_name("schema.sql")

COLUMNS = [
    "id", "person_id", "person_id_method", "name_full", "name_first", "name_middle", "name_last", "name_suffix",
    "nickname", "office_title", "role", "role_note", "body_name", "parent_body",
    "jurisdiction_level", "jurisdiction", "jurisdiction_id", "branch", "record_type",
    "selection_method", "appointing_authority", "selection_text", "party", "party_source",
    "district", "counties", "term_length_years", "term_start", "term_start_title",
    "term_end_year", "is_vacancy", "is_ex_officio", "note", "bio_url", "source_url",
    "evidence", "page_date",
]


def _row_id(r: dict, i: int) -> str:
    key = "|".join(str(r.get(k) or "") for k in
                   ("person_id", "body_name", "office_title", "jurisdiction_id", "source_url"))
    if r.get("is_vacancy"):
        key += f"|vacancy|{i}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def officeholders_ddl() -> str:
    text = SCHEMA.read_text()
    return text[text.index("-- Office-holders"):]


def write(rows: list[dict]) -> None:
    seen: Counter = Counter()
    for i, r in enumerate(rows):
        rid = _row_id(r, i)
        seen[rid] += 1
        r["id"] = rid if seen[rid] == 1 else f"{rid}-{seen[rid]}"

    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript(officeholders_ddl())
    conn.executemany(
        f"INSERT INTO officeholders ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})",
        [[r.get(c) for c in COLUMNS] for r in rows],
    )
    conn.commit()
    conn.close()

    with CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def coverage_report(rows: list[dict], info: dict) -> str:
    out = []
    s = info["stats"]
    out.append(f"pages parsed: {s.get('pages')}  bios: {s.get('bios')}  rows: {len(rows)}")
    out.append("")
    for field in ("jurisdiction_level", "branch", "record_type", "selection_method", "party"):
        c = Counter(r.get(field) or "(blank)" for r in rows)
        out.append(f"{field}: " + ", ".join(f"{k}={v}" for k, v in c.most_common()))
    filled = lambda k: sum(1 for r in rows if r.get(k))  # noqa: E731
    people = [r for r in rows if not r["is_vacancy"]]
    out.append("")
    out.append(f"people rows: {len(people)}  vacancies: {len(rows) - len(people)}")
    for k in ("party", "district", "term_end_year", "term_start", "bio_url", "appointing_authority"):
        out.append(f"  with {k}: {filled(k)}")
    zero = sorted(u for u, n in info["page_counts"].items() if n == 0)
    out.append("")
    out.append(f"pages with no rows ({len(zero)}):")
    out.extend(f"  {u}" for u in zero)
    return "\n".join(out)


def main() -> None:
    rows, info = build()
    if not rows:
        sys.exit("No rows: run `python -m crawler.crawl --profile officials` first.")
    write(rows)
    report = coverage_report(rows, info)
    REPORT.write_text(report + "\n")
    print(report.split("\npages with no rows")[0])
    print(f"\nWrote {len(rows)} rows to {CSV} and {DB}:officeholders; report in {REPORT}")


if __name__ == "__main__":
    main()
