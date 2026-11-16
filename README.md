# The Networked Maryland Manual

Reimagining the [Maryland Manual On-Line](https://msa.maryland.gov/msa/mdmanual/html/mmtoc.html)
as a **network of governments** — for reporters. Instead of a directory of
counties, municipalities, and state agencies, it surfaces the *relationships*
between them: structural peers, appointment chains, shared officials, and
which entities touch a given beat.

See [`docs/CONCEPT.md`](docs/CONCEPT.md) for the idea.

## Pipeline

Each stage reads only the previous stage's output. Nothing re-fetches the web
once the cache is warm.

```
crawl → parse → resolve → enrich (LLM) → derive → load (SQLite) → build (static site)
```

## Quick start

```bash
python3 -m pip install -e .          # install deps
make crawl-mvp                       # crawl the MVP slice (counties + departments)
make site                            # parse -> load -> peers -> build static site
make serve                           # http://localhost:8000
make datasette                       # browse manual.db as a QA console
make test                            # fixtures + ground-truth assertions
```

## Officials dataset

A list of current state and local office-holders (elected and appointed) with
party, district and term where the Manual gives them: the General Assembly,
constitutional officers and cabinet, department and independent-agency heads,
judges, every state and county board, commission and task force, county
governments (executive, council or commissioners, State's Attorney, Sheriff,
Clerk, Register of Wills, Orphans' Court, Board of Education) and all
municipal mayors and councils. Rank-and-file staff are left out.

```bash
export MDMANUAL_CONTACT="you@example.org"   # optional: identifies you in the User-Agent
make crawl-officials   # roster pages + linked biographies, ~2 hours at 1 req/sec, cached
make officials         # -> data/officials.csv and the officeholders table in data/manual.db
```

One row per person-office; vacancies are rows with `is_vacancy = 1`. Each row
keeps the roster line it came from (`evidence`) and its page (`source_url`).
`data/officials_coverage.txt` summarizes field coverage and lists pages that
produced no rows. Legislative committee seats are `record_type = 'committee'`.

Known limits:

- The Manual is the only source. Term years are as published, and some are
  stale (holdovers still showing 2023 or 2024; pages not yet updated after the
  November 2026 election).
- `term_end_year` is the year the term expires. `term_start` exists only where a
  biography page gives a "since" date, or for legislators (January 11, 2023).
- Party is shown only for partisan offices and a few boards. It is filled from
  biography pages where the roster omits it (`party_source = 'bio'`). Judges,
  school boards and most appointees have none.
- People without a Manual biography get a per-body id
  (`person:<name-slug>@<body-slug>`), so one person on several boards appears
  as several people. Linked people share `person:msaNNNNN` across rows.

## Layout

```
crawler/     polite BFS crawler + scope rules (crawl.py, seeds.py)
extract/     HTML -> records: patterns.py, parse_county.py, parse_agency.py,
             parse_index.py; officials: roster.py (shared roster grammar),
             parse_legislature.py, parse_bio.py, officials.py (orchestrator)
graph/       schema.sql, load.py (records -> SQLite), peers.py (derived edges),
             officials.py (officeholders table + CSV)
site/        build.py (SQLite -> static HTML + JSON), templates/, static/
enrich/      LLM relation + topic tagging (Claude Batch API) — v0.3
tests/       fixtures/ (committed sample HTML), test_parsers.py, test_ground_truth.py,
             test_officials.py, test_officials_ground_truth.py
data/        cache/ (raw HTML mirror, gitignored), manual.db (rebuildable)
```

## Data provenance & etiquette

The crawler identifies itself, runs at 1 request/second, caches every page to
disk so re-runs cost nothing, and only follows links it discovers (it never
constructs URLs). It excludes bulk election-returns and PDF subtrees. Source:
Maryland State Archives, Maryland Manual On-Line — a public reference updated
daily.
