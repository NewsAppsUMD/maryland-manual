# The Networked Maryland Manual

## The problem

The [Maryland Manual On-Line](https://msa.maryland.gov/msa/mdmanual/html/mmtoc.html)
is the authoritative reference on Maryland government — every county, every
municipality, every state department, agency, board, and commission. It is
maintained by the Maryland State Archives and updated daily. It is also, in
form, a **directory**: thousands of pages, each a self-contained listing of
names, addresses, and terms, connected to the rest only by hyperlinks and the
reader's patience.

Reporters don't work in directories. They work in questions:

- *Frederick County just did X. Which counties are its structural peers — who
  should I call for comparison?*
- *Who touches housing in this county? Not just the county housing office —
  the municipal authorities, the regional council, the state department that
  funds them.*
- *This board just made a controversial decision. Who appointed its members?*
- *Is the same person sitting on three different commissions?*

The Manual contains the answers to all of these. It just doesn't **surface**
them, because it stores government as a list of entries rather than a web of
relationships.

## The reframe

> **Every fact in the Manual is an edge, not an entry.**

"Howard County — Form of Government: Charter since 1968" is not a field on a
card. It is an edge that connects Howard to *every other charter county* — its
structural peers. "Appointed by the Governor with Senate advice & consent" is
an edge from the Governor to a board. "Created from Anne Arundel County by
Chapter 22, Acts of 1838" is an edge into the statute genealogy. The
`Boundaries:` paragraph is a set of adjacency edges. A link to a person's
biography page is a `serves-on` edge — and when the same person appears on two
boards, that's an interlock the Manual never names.

This project extracts those edges into a typed graph and builds a reader
experience around the graph instead of around the page.

## Three surfaces for reporters

### 1. Entity pages that lead with connections

Every county, municipality, and agency gets a page whose top matter is not a
contact block but a set of **connection panels**, ordered by reporter value:

- **Structural peers** — who is this jurisdiction *like*, and why
- **Oversees / overseen by** — hierarchy and authority
- **Appoints / appointed by** — the accountability chain
- **Shared people** — who else sits where these people sit
- **Same beat** — entities that work the same topic
- **Adjacent jurisdictions** — the neighbors
- **Created by** — the statute that made it

Every extracted claim carries a **verbatim evidence quote** and a link back to
the exact Manual page it came from. A reporter can trust it because they can
check it.

### 2. Explainable structural peers

"Peer" is not a vibe. It is a weighted, **itemized** score:

- same form of government (charter / code home rule / commissioner)
- same judicial circuit
- similar population (log-scale bucket)
- shared regional bodies (Tri-County Councils, metropolitan commissions)
- adjacency

The peer panel shows the components, so a reporter can see *why* Frederick and
Wicomico came up as comparable — and quote the reasoning.

### 3. The beat lens

A fixed, reporter-first topic taxonomy (housing, policing, courts, health,
education, environment, transportation, land use, taxes & budget, elections,
labor & business, human services, agriculture, technology & records). Every
agency is tagged. Then:

> *"Housing in Frederick County"* → a single page tiering the entities that
> touch housing there: municipal authorities, the county office, the regional
> council, and the state department — with the edges that connect them.

This is the query the current Manual cannot answer and reporters ask constantly.

## Bonus: the Manual as a live wire

Because the Manual updates daily, a monthly re-crawl produces a **diff**: new
appointees, newly vacant seats, renamed or reorganized agencies. That diff is
itself a tip sheet.

## How it's built

A staged, cache-first pipeline — see [`README.md`](../README.md) and the build
plan. The short version:

```
crawl → parse → resolve → enrich (LLM) → derive → load (SQLite) → build (static site)
```

Deterministic regex extraction does the heavy lifting on the Manual's
remarkably consistent markup; a quote-verified LLM pass classifies fuzzier
relationships and assigns beats; everything lands in a Datasette-browsable
SQLite database and a static site with an interactive network explorer.
