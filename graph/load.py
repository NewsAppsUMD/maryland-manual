"""Load parsed records into manual.db, resolving edge targets to entity ids.

Resolution order for an edge target:
  1. an explicit target_id that names a known entity
  2. a target_url that maps to a known entity's canonical URL
  3. a person/statute stub created on the fly from the target_url + qualifiers

Edges whose target cannot be resolved are dropped (and counted), never guessed.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from crawler import seeds
from extract import patterns
from extract.base import Entity
from extract.parse import parse_all

DB = Path("data/manual.db")
SCHEMA = Path("graph/schema.sql")
MANIFEST = Path("data/cache/crawl.db")

# Entity type precedence when merging duplicate ids (more specific wins).
_TYPE_RANK = {
    "county": 5, "municipality": 5, "department": 5, "agency": 4,
    "government": 4, "office": 3, "person": 3, "statute": 2, "external": 1,
}


def _merge(a: Entity, b: Entity) -> Entity:
    """Merge two entity records sharing an id."""
    name = a.name if len(a.name) >= len(b.name) else b.name
    etype = a.type if _TYPE_RANK.get(a.type, 0) >= _TYPE_RANK.get(b.type, 0) else b.type
    attrs = {**(b.attrs or {}), **(a.attrs or {})}
    return Entity(
        id=a.id, name=name, type=etype,
        level=a.level or b.level, url=a.url or b.url,
        parent_id=a.parent_id or b.parent_id, attrs=attrs,
    )


def build_graph():
    entities, edges, stats = parse_all()

    # 1. Dedup/merge entities by id.
    by_id: dict[str, Entity] = {}
    for e in entities:
        if e.id in by_id:
            by_id[e.id] = _merge(by_id[e.id], e)
        else:
            by_id[e.id] = e

    # 2. URL -> id map for target resolution.
    url_to_id: dict[str, str] = {}
    for e in by_id.values():
        if e.url:
            norm = seeds.normalize(e.url)
            if norm:
                url_to_id[norm] = e.id

    # 3. Resolve edges.
    resolved = []
    dropped = 0
    for edge in edges:
        tid = edge.target_id
        if tid and tid in by_id:
            pass
        elif edge.target_url:
            norm = seeds.normalize(edge.target_url)
            if norm and norm in url_to_id:
                tid = url_to_id[norm]
            else:
                # Create a stub for person/statute targets we can name.
                pid = patterns.person_id_from_url(edge.target_url) if norm else None
                if pid:
                    pname = (edge.qualifiers or {}).get("person_name", pid.split(":")[1])
                    if pid not in by_id:
                        by_id[pid] = Entity(id=pid, name=pname, type="person",
                                            level="state", url=norm)
                    tid = pid
                else:
                    tid = None
        elif tid and tid not in by_id:
            # target_id names an entity we never built (e.g. appointer office
            # referenced but not emitted) — create a minimal stub if we can.
            tid = None

        if not tid or tid not in by_id:
            dropped += 1
            continue
        resolved.append((edge, tid))

    # Symmetrize adjacency: the Manual sometimes describes one side of a border
    # by its river/bay rather than naming the county, so an edge can arrive
    # one-directional. Adjacency is symmetric by definition; add the reciprocal
    # as a derived edge (kept distinct from the regex-extracted originals).
    adj = {(e.source_id, tid) for e, tid in resolved if e.type == "adjacent_to"}
    from extract.base import Edge as _Edge
    for a, b in list(adj):
        if (b, a) not in adj:
            adj.add((b, a))
            resolved.append((_Edge(
                source_id=b, type="adjacent_to", target_id=a,
                method="derived", confidence=1.0,
                evidence="reciprocal of stated adjacency",
            ), a))

    stats["entities"] = len(by_id)
    stats["edges_resolved"] = len(resolved)
    stats["edges_dropped"] = dropped
    return by_id, resolved, stats


def write_db(by_id, resolved, stats):
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA.read_text())

    conn.executemany(
        "INSERT INTO entities (id, name, type, level, url, parent_id, attrs) "
        "VALUES (?,?,?,?,?,?,?)",
        [(e.id, e.name, e.type, e.level, e.url, e.parent_id,
          json.dumps(e.attrs) if e.attrs else None) for e in by_id.values()],
    )
    conn.executemany(
        "INSERT INTO edges (source_id, target_id, type, qualifiers, method, "
        "confidence, provenance_url, evidence) VALUES (?,?,?,?,?,?,?,?)",
        [(edge.source_id, tid, edge.type,
          json.dumps(edge.qualifiers) if edge.qualifiers else None,
          edge.method, edge.confidence, edge.provenance_url, edge.evidence)
         for edge, tid in resolved
         if edge.source_id in by_id],
    )

    # Copy page metadata from the crawl manifest.
    if MANIFEST.exists():
        man = sqlite3.connect(MANIFEST)
        pages = man.execute(
            "SELECT url, cache_path, status, sha256, fetched_at FROM pages"
        ).fetchall()
        man.close()
        conn.executemany(
            "INSERT OR REPLACE INTO pages (url, cache_path, status, sha256, fetched_at) "
            "VALUES (?,?,?,?,?)", pages,
        )

    conn.commit()
    conn.close()


def main():
    by_id, resolved, stats = build_graph()
    write_db(by_id, resolved, stats)
    print(f"Loaded manual.db")
    print(f"  entities: {stats['entities']}")
    print(f"  edges:    {stats['edges_resolved']} resolved, {stats['edges_dropped']} dropped")
    print(f"  by_type:  {stats['by_type']}")
    if stats["zero_yield"]:
        print(f"  zero-yield pages: {len(stats['zero_yield'])}")


if __name__ == "__main__":
    main()
