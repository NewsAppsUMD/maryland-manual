-- The Networked Maryland Manual — graph schema.
-- Datasette-friendly: plain tables, JSON in TEXT columns, explicit provenance.

DROP TABLE IF EXISTS pages;
DROP TABLE IF EXISTS entities;
DROP TABLE IF EXISTS edges;
DROP TABLE IF EXISTS topics;
DROP TABLE IF EXISTS entity_topics;
DROP TABLE IF EXISTS peer_scores;

CREATE TABLE entities (
    id         TEXT PRIMARY KEY,   -- e.g. 'county:howard', 'agency:dhcd', 'person:msa18502'
    name       TEXT NOT NULL,
    type       TEXT NOT NULL,      -- county|municipality|department|agency|office|person|statute|government
    level      TEXT,               -- state|county|municipal|regional|federal
    url        TEXT,
    parent_id  TEXT,
    attrs      TEXT                 -- JSON
);

CREATE TABLE edges (
    id             INTEGER PRIMARY KEY,
    source_id      TEXT NOT NULL,
    target_id      TEXT NOT NULL,
    type           TEXT NOT NULL,   -- adjacent_to|created_by|named_for|leads|serves_in|appoints|part_of|contains|...
    qualifiers     TEXT,            -- JSON
    method         TEXT,            -- regex|link|llm|derived
    confidence     REAL DEFAULT 1.0,
    provenance_url TEXT,
    evidence       TEXT,
    FOREIGN KEY (source_id) REFERENCES entities(id),
    FOREIGN KEY (target_id) REFERENCES entities(id)
);

CREATE TABLE topics (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL
);

CREATE TABLE entity_topics (
    entity_id  TEXT NOT NULL,
    topic_id   TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    method     TEXT,
    evidence   TEXT,
    PRIMARY KEY (entity_id, topic_id)
);

CREATE TABLE peer_scores (
    a          TEXT NOT NULL,
    b          TEXT NOT NULL,
    score      REAL NOT NULL,
    components TEXT,                -- JSON: itemized contribution per criterion
    PRIMARY KEY (a, b)
);

CREATE TABLE pages (
    url         TEXT PRIMARY KEY,
    cache_path  TEXT,
    status      INTEGER,
    page_type   TEXT,
    sha256      TEXT,
    fetched_at  REAL
);

CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_edges_type   ON edges(type);
CREATE INDEX idx_entities_type ON entities(type);
CREATE INDEX idx_entity_topics_topic ON entity_topics(topic_id);
