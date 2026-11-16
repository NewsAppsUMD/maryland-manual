"""Dispatcher: walk the crawl cache and run the right parser on each page.

Reads only the crawl manifest + cached HTML (never the network). Produces a
flat list of Entity and Edge records for the load stage.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import parse_agency, parse_county, parse_index, patterns
from .base import Entity, Edge, PageResult
from .registry import Registry, load_registry

MANIFEST = Path("data/cache/crawl.db")


def dispatch(url: str, html: str, reg: Registry) -> PageResult | None:
    if patterns.COUNTY_URL_RE.search(url):
        return parse_county.parse(url, html, reg)
    if patterns.AGENCY_URL_RE.search(url):
        return parse_agency.parse(url, html)
    if parse_index.DEPT_INDEX_RE.search(url):
        return parse_index.parse_dept_index(url, html)
    if parse_index.MUNI_LIST_RE.search(url):
        return parse_index.parse_muni_list(url, html, reg)
    return None


def parse_all() -> tuple[list[Entity], list[Edge], dict]:
    reg = load_registry()
    conn = sqlite3.connect(MANIFEST)
    rows = conn.execute(
        "SELECT url, cache_path FROM pages WHERE status=200 AND cache_path IS NOT NULL"
    ).fetchall()
    conn.close()

    entities: list[Entity] = []
    edges: list[Edge] = []
    stats = {"pages": 0, "parsed": 0, "zero_yield": [], "by_type": {}}

    for url, cache_path in rows:
        stats["pages"] += 1
        p = Path(cache_path)
        if not p.exists():
            continue
        html = patterns.decode_page(p.read_bytes())
        result = dispatch(url, html, reg)
        if result is None:
            continue
        stats["parsed"] += 1
        stats["by_type"][result.page_type] = stats["by_type"].get(result.page_type, 0) + 1
        if not result.edges and result.page_type in ("county", "agency"):
            stats["zero_yield"].append(url)
        entities.extend(result.entities)
        edges.extend(result.edges)

    return entities, edges, stats


if __name__ == "__main__":
    ents, eds, stats = parse_all()
    print(f"pages={stats['pages']} parsed={stats['parsed']}")
    print(f"entities={len(ents)} edges={len(eds)}")
    print(f"by_type={stats['by_type']}")
    if stats["zero_yield"]:
        print(f"ZERO-YIELD ({len(stats['zero_yield'])}):")
        for u in stats["zero_yield"][:10]:
            print("  ", u)
