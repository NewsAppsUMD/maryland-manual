"""Derived structural-peer scores between counties.

"Peer" is an explainable, itemized score — not a black box. Each component's
contribution is stored so the entity page can show *why* two counties are peers
(the feature reporters need to trust and quote it).

Components (weights sum to 1.0):
  form_of_government  0.45   same charter / commission / code-home-rule class
  population          0.35   closeness on a log scale
  adjacency           0.20   share a border

Judicial circuit and shared regional bodies are planned additional components
(they need circuit + commission-membership extraction) and slot in here with
their own weights once available.
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

DB = Path("data/manual.db")

WEIGHTS = {"form_of_government": 0.45, "population": 0.35, "adjacency": 0.20}


def _load_counties(conn) -> dict:
    out = {}
    for cid, name, attrs in conn.execute(
        "SELECT id, name, attrs FROM entities WHERE type='county'"
    ):
        a = json.loads(attrs) if attrs else {}
        fog = (a.get("form_of_government") or {}).get("category")
        pop = a.get("population_latest")
        out[cid] = {"name": name, "fog": fog, "pop": pop}
    return out


def _adjacency(conn) -> set:
    return {
        (s, t) for s, t in conn.execute(
            "SELECT source_id, target_id FROM edges WHERE type='adjacent_to'"
        )
    }


def _population_similarity(pa, pb) -> float:
    if not pa or not pb:
        return 0.0
    # Log-scale distance; MD county populations span ~2 orders of magnitude
    # (Kent ~19k to Montgomery ~1M => ln range ~4). Normalize by that.
    d = abs(math.log(pa) - math.log(pb))
    return max(0.0, 1.0 - d / 4.0)


def compute():
    conn = sqlite3.connect(DB)
    counties = _load_counties(conn)
    adj = _adjacency(conn)
    ids = list(counties)

    rows = []
    for i, a in enumerate(ids):
        for b in ids:
            if a == b:
                continue
            ca, cb = counties[a], counties[b]
            comp = {}

            comp["form_of_government"] = (
                WEIGHTS["form_of_government"]
                if ca["fog"] and ca["fog"] == cb["fog"] else 0.0
            )
            comp["population"] = round(
                WEIGHTS["population"] * _population_similarity(ca["pop"], cb["pop"]), 4
            )
            comp["adjacency"] = WEIGHTS["adjacency"] if (a, b) in adj else 0.0

            score = round(sum(comp.values()), 4)
            # Human-readable "why".
            why = []
            if comp["form_of_government"]:
                why.append(f"both {ca['fog']}")
            if ca["pop"] and cb["pop"]:
                why.append(f"pop {ca['pop']:,} vs {cb['pop']:,}")
            if comp["adjacency"]:
                why.append("adjacent")
            rows.append((a, b, score, json.dumps(
                {"components": comp, "why": why})))

    conn.execute("DELETE FROM peer_scores")
    conn.executemany(
        "INSERT INTO peer_scores (a, b, score, components) VALUES (?,?,?,?)", rows
    )
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM peer_scores").fetchone()[0]
    print(f"peer_scores: {n} directed pairs across {len(ids)} counties")

    # Spot check.
    print("\nTop peers of Howard County:")
    for b, score, comp in conn.execute(
        "SELECT b, score, components FROM peer_scores WHERE a='county:howard' "
        "ORDER BY score DESC LIMIT 5"
    ):
        why = json.loads(comp)["why"]
        print(f"  {score:.2f}  {b:26} {', '.join(why)}")
    conn.close()


if __name__ == "__main__":
    compute()
