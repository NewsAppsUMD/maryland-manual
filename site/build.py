"""Build the static site from manual.db.

Emits, into site/dist/:
  index.html                       browse + search landing
  explorer.html                    interactive network graph
  entity/<id>.html                 one page per entity, connection panels first
  data/graph.json                  nodes + typed edges for the explorer
  data/search.json                 lightweight client-side search index
Everything is self-contained: no external scripts or fonts.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

DB = Path("data/manual.db")
DIST = Path("site/dist")
TEMPLATES = Path("site/templates")
STATIC = Path("site/static")

# Edge presentation rules: (edge_type, direction) -> (panel title, priority).
# direction: "out" = entity is source, "in" = entity is target.
PANEL_RULES = {
    ("adjacent_to", "out"): ("Adjacent jurisdictions", 20),
    ("appoints", "in"): ("Appointed by", 30),
    ("appoints", "out"): ("Appoints", 31),
    ("leads", "in"): ("Leadership", 40),
    ("leads", "out"): ("Leads", 41),
    ("serves_in", "in"): ("Officials & members", 42),
    ("serves_in", "out"): ("Serves in", 43),
    ("created_by", "out"): ("Created by", 50),
    ("created_by", "in"): ("Entities it created", 51),
    ("contains", "out"): ("Municipalities", 60),
    ("contains", "in"): ("Part of", 10),
    ("part_of", "out"): ("Part of", 11),
    ("part_of", "in"): ("Component agencies", 61),
    ("named_for", "out"): ("Named for", 70),
    ("named_for", "in"): ("Namesake of", 71),
}

TYPE_LABEL = {
    "county": "County", "municipality": "Municipality", "department": "Department",
    "agency": "Agency", "office": "Office", "person": "Person",
    "statute": "Statute", "government": "Government",
}


def safe_id(eid: str) -> str:
    return eid.replace(":", "__").replace("/", "_")


def qualifier_text(q: dict) -> str:
    if not q:
        return ""
    bits = []
    if "role" in q:
        bits.append(q["role"])
    if q.get("consent") == "senate":
        bits.append("Senate advice & consent")
    if "term_years" in q:
        bits.append(f"{q['term_years']}-year term")
    if q.get("voting") is False:
        bits.append("nonvoting")
    if "person_name" in q and "role" not in q:
        bits.append(q["person_name"])
    return " · ".join(bits)


def load_graph(conn):
    entities = {}
    for eid, name, etype, level, url, parent, attrs in conn.execute(
        "SELECT id, name, type, level, url, parent_id, attrs FROM entities"
    ):
        entities[eid] = {
            "id": eid, "name": name, "type": etype, "level": level,
            "url": url, "parent_id": parent,
            "attrs": json.loads(attrs) if attrs else {},
        }
    edges = []
    for row in conn.execute(
        "SELECT source_id, target_id, type, qualifiers, method, confidence, "
        "provenance_url, evidence FROM edges"
    ):
        s, t, typ, q, method, conf, prov, ev = row
        edges.append({
            "source": s, "target": t, "type": typ,
            "qualifiers": json.loads(q) if q else {},
            "method": method, "confidence": conf,
            "provenance": prov, "evidence": ev,
        })
    peers = {}
    for a, b, score, comp in conn.execute(
        "SELECT a, b, score, components FROM peer_scores"
    ):
        peers.setdefault(a, []).append({
            "id": b, "score": score, "why": json.loads(comp).get("why", []),
        })
    for a in peers:
        peers[a].sort(key=lambda x: x["score"], reverse=True)
    return entities, edges, peers


def build_panels(eid, entities, edges, peers):
    panels: dict[str, dict] = {}

    def add(title, prio, item):
        p = panels.setdefault(title, {"title": title, "prio": prio, "items": []})
        p["items"].append(item)

    # Structural peers (counties).
    if eid in peers:
        for pr in peers[eid][:8]:
            tgt = entities.get(pr["id"])
            if not tgt:
                continue
            add("Structural peers", 5, {
                "name": tgt["name"], "href": f"{safe_id(pr['id'])}.html",
                "meta": f"peer score {pr['score']:.2f} — " + ", ".join(pr["why"]),
                "evidence": None, "provenance": None, "score": pr["score"],
            })

    for e in edges:
        if e["source"] == eid:
            direction, other = "out", e["target"]
        elif e["target"] == eid:
            direction, other = "in", e["source"]
        else:
            continue
        rule = PANEL_RULES.get((e["type"], direction))
        if not rule:
            continue
        title, prio = rule
        tgt = entities.get(other)
        if not tgt:
            continue
        add(title, prio, {
            "name": tgt["name"],
            "href": f"{safe_id(other)}.html",
            "type": tgt["type"],
            "meta": qualifier_text(e["qualifiers"]),
            "evidence": e["evidence"],
            "provenance": e["provenance"],
            "method": e["method"],
        })

    ordered = sorted(panels.values(), key=lambda p: p["prio"])
    for p in ordered:
        # Sort peers by score, others alphabetically.
        if p["title"] == "Structural peers":
            p["items"].sort(key=lambda i: i.get("score", 0), reverse=True)
        else:
            p["items"].sort(key=lambda i: i["name"])
    return ordered


def identity_facts(ent):
    """Human-readable identity block for an entity."""
    a = ent["attrs"]
    facts = []
    if ent["type"] == "county":
        fog = a.get("form_of_government")
        if fog:
            s = fog["raw"] if fog.get("raw") else fog.get("category", "")
            facts.append(("Form of government", s))
        if a.get("county_seat"):
            facts.append(("County seat", a["county_seat"]))
        if a.get("population_latest"):
            facts.append(("Population",
                          f"{a['population_latest']:,} ({a.get('population_year')})"))
    if a.get("website"):
        facts.append(("Website", a["website"]))
    return facts


def main():
    conn = sqlite3.connect(DB)
    entities, edges, peers = load_graph(conn)
    conn.close()

    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "entity").mkdir(parents=True)
    (DIST / "data").mkdir(parents=True)
    if STATIC.exists():
        for f in STATIC.iterdir():
            shutil.copy(f, DIST / f.name)

    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )
    env.globals["safe_id"] = safe_id
    env.globals["TYPE_LABEL"] = TYPE_LABEL

    # Degree (for explorer node sizing) and typed-edge counts.
    degree = {eid: 0 for eid in entities}
    for e in edges:
        if e["source"] in degree:
            degree[e["source"]] += 1
        if e["target"] in degree:
            degree[e["target"]] += 1

    # --- Entity pages ---
    entity_tmpl = env.get_template("entity.html")
    for eid, ent in entities.items():
        panels = build_panels(eid, entities, edges, peers)
        conn_count = sum(len(p["items"]) for p in panels)
        html = entity_tmpl.render(
            ent=ent, panels=panels, facts=identity_facts(ent),
            type_label=TYPE_LABEL.get(ent["type"], ent["type"].title()),
            conn_count=conn_count, root="../",
        )
        (DIST / "entity" / f"{safe_id(eid)}.html").write_text(html)

    # --- Home / browse ---
    groups = {}
    for eid, ent in entities.items():
        groups.setdefault(ent["type"], []).append(ent)
    for t in groups:
        groups[t].sort(key=lambda e: e["name"])
    counts = {t: len(v) for t, v in groups.items()}
    index_tmpl = env.get_template("index.html")
    (DIST / "index.html").write_text(index_tmpl.render(
        groups=groups, counts=counts, total_entities=len(entities),
        total_edges=len(edges), type_label=TYPE_LABEL, root="",
        order=["county", "department", "agency", "office", "municipality",
               "person", "statute", "government"],
    ))

    # --- Explorer ---
    explorer_tmpl = env.get_template("explorer.html")
    edge_types = sorted({e["type"] for e in edges})
    (DIST / "explorer.html").write_text(explorer_tmpl.render(edge_types=edge_types, root=""))

    # --- JSON for explorer + search ---
    # Keep the explorer graph to the typed, meaningful nodes (skip lone munis
    # with only a containment edge to reduce hairball; they're still on the site).
    graph_nodes = [{
        "id": eid, "name": ent["name"], "type": ent["type"],
        "level": ent["level"], "degree": degree.get(eid, 0),
        "href": f"entity/{safe_id(eid)}.html",
    } for eid, ent in entities.items()]
    graph_edges = [{
        "source": e["source"], "target": e["target"], "type": e["type"],
    } for e in edges]
    (DIST / "data" / "graph.json").write_text(json.dumps(
        {"nodes": graph_nodes, "edges": graph_edges}))

    search = [{
        "id": eid, "name": ent["name"], "type": ent["type"],
        "href": f"entity/{safe_id(eid)}.html",
    } for eid, ent in entities.items()]
    (DIST / "data" / "search.json").write_text(json.dumps(search))

    print(f"Built site/dist/ — {len(entities)} entity pages, "
          f"{len(edges)} edges, explorer + search.")


if __name__ == "__main__":
    main()
