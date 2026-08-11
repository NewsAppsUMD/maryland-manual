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

## Layout

```
crawler/     polite BFS crawler + scope rules (crawl.py, seeds.py)
extract/     HTML -> records: patterns.py, parse_county.py, parse_agency.py,
             parse_index.py, links.py
graph/       schema.sql, load.py (records -> SQLite), peers.py (derived edges)
site/        build.py (SQLite -> static HTML + JSON), templates/, static/
enrich/      LLM relation + topic tagging (Claude Batch API) — v0.3
tests/       fixtures/ (committed sample HTML), test_parsers.py, test_ground_truth.py
data/        cache/ (raw HTML mirror, gitignored), manual.db (rebuildable)
```

## Data provenance & etiquette

The crawler identifies itself, runs at 1 request/second, caches every page to
disk so re-runs cost nothing, and only follows links it discovers (it never
constructs URLs). It excludes bulk election-returns and PDF subtrees. Source:
Maryland State Archives, Maryland Manual On-Line — a public reference updated
daily.
