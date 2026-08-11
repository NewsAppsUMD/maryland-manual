"""Record types shared by all parsers.

A parser turns one cached HTML page into a PageResult: the primary Entity the
page is about, any secondary entities it introduces (people, statutes,
municipalities), and typed Edges. Every edge carries provenance (the source URL
and a verbatim evidence snippet) and a `method` so the front end and QA can
tell regex facts from LLM inferences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Canonical office nodes for state-level appointers, so the appointment web is
# navigable rather than a pile of strings.
APPOINTER_OFFICE = {
    "Governor": ("office:governor", "Governor of Maryland", "state"),
    "General Assembly": ("office:general-assembly", "General Assembly", "state"),
    "Senate President": ("office:senate-president", "President of the Senate", "state"),
    "House Speaker": ("office:house-speaker", "Speaker of the House", "state"),
    "Attorney General": ("office:attorney-general", "Attorney General", "state"),
    "Comptroller": ("office:comptroller", "Comptroller of Maryland", "state"),
    "Board of Public Works": ("office:board-of-public-works", "Board of Public Works", "state"),
    "Chief Judge": ("office:chief-judge", "Chief Judge, Court of Appeals", "state"),
}


@dataclass
class Entity:
    id: str
    name: str
    type: str                       # county|municipality|department|agency|office|person|statute
    level: str = "state"            # state|county|municipal|regional|federal
    url: str | None = None
    parent_id: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    source_id: str
    type: str
    target_id: str | None = None    # resolved entity id, if known
    target_url: str | None = None   # resolve via URL->id map at load time
    target_name: str | None = None  # resolve via name (e.g. adjacency) at load
    qualifiers: dict[str, Any] = field(default_factory=dict)
    method: str = "regex"           # regex|link|llm|derived
    confidence: float = 1.0
    provenance_url: str | None = None
    evidence: str | None = None


@dataclass
class PageResult:
    page_type: str
    entities: list[Entity] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def add_entity(self, e: Entity) -> Entity:
        self.entities.append(e)
        return e

    def add_edge(self, e: Edge) -> Edge:
        self.edges.append(e)
        return e
