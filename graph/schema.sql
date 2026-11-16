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

-- Office-holders (built by graph/officials.py from the "officials" crawl).
-- One row per person-office; vacancies are rows with is_vacancy = 1.
DROP TABLE IF EXISTS officeholders;
CREATE TABLE officeholders (
    id                   TEXT PRIMARY KEY,   -- sha1 of person, body, office, jurisdiction
    person_id            TEXT,               -- person:msaNNNNN when the Manual has a bio
    person_id_method     TEXT,               -- bio_link | name_match | local (name@body)
    name_full            TEXT,
    name_first           TEXT,
    name_middle          TEXT,
    name_last            TEXT,
    name_suffix          TEXT,
    nickname             TEXT,
    office_title         TEXT,               -- Delegate, Sheriff, Member, Associate Judge...
    role                 TEXT,               -- Chair, President, leadership posts
    role_note            TEXT,               -- e.g. "chosen by Council in Dec., 1-year term"
    body_name            TEXT,               -- County Council, Board of Appeals...
    parent_body          TEXT,               -- page-level agency or branch
    jurisdiction_level   TEXT,               -- state | county | municipal
    jurisdiction         TEXT,
    jurisdiction_id      TEXT,               -- state:md, county:howard, municipality:rockville
    branch               TEXT,               -- executive | legislative | judicial | municipal
    record_type          TEXT,               -- office | committee (legislative committee seats)
    selection_method     TEXT,               -- elected | appointed | appointed/elected | ex officio | other
    appointing_authority TEXT,
    selection_text       TEXT,               -- the Manual's label, verbatim
    party                TEXT,
    party_source         TEXT,               -- roster | bio
    district             TEXT,
    counties             TEXT,               -- legislators: counties in the district
    term_length_years    INTEGER,
    term_start           TEXT,               -- ISO date, from roster or bio "since" line
    term_start_title     TEXT,               -- the office named in that bio line
    term_end_year        INTEGER,            -- year the term expires, as published
    is_vacancy           INTEGER,
    is_ex_officio        INTEGER,
    note                 TEXT,               -- footnotes (appointed to fill vacancy, etc.)
    bio_url              TEXT,
    source_url           TEXT,
    evidence             TEXT,               -- the roster line the row came from
    page_date            TEXT                -- bio page "Copyright" date
);
CREATE INDEX idx_officeholders_person ON officeholders(person_id);
CREATE INDEX idx_officeholders_juris ON officeholders(jurisdiction_id);
CREATE INDEX idx_officeholders_body ON officeholders(body_name);
