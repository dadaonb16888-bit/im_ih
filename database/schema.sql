PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS information_inbox (
 information_id TEXT PRIMARY KEY, payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, known_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 payload TEXT NOT NULL CHECK(json_valid(payload)),
 name TEXT GENERATED ALWAYS AS (json_extract(payload, '$.name')) VIRTUAL,
 channel TEXT GENERATED ALWAYS AS (json_extract(payload, '$.channels[0]')) VIRTUAL,
 horizon TEXT GENERATED ALWAYS AS (json_extract(payload, '$.horizon')) VIRTUAL,
 bias TEXT GENERATED ALWAYS AS (json_extract(payload, '$.bias')) VIRTUAL,
 impact REAL GENERATED ALWAYS AS (json_extract(payload, '$.impact_score')) VIRTUAL,
 confidence REAL GENERATED ALWAYS AS (json_extract(payload, '$.confidence_score')) VIRTUAL,
 score REAL GENERATED ALWAYS AS (json_extract(payload, '$.score')) VIRTUAL,
 created_time TEXT GENERATED ALWAYS AS (json_extract(payload, '$.known_at')) VIRTUAL,
 status TEXT GENERATED ALWAYS AS (json_extract(payload, '$.status')) VIRTUAL,
 source TEXT GENERATED ALWAYS AS (json_extract(payload, '$.source')) VIRTUAL,
 source_reliability TEXT GENERATED ALWAYS AS (json_extract(payload, '$.source_reliability')) VIRTUAL,
 persistence_score REAL GENERATED ALWAYS AS (json_extract(payload, '$.persistence_score')) VIRTUAL,
 event_strength REAL GENERATED ALWAYS AS (json_extract(payload, '$.event_strength')) VIRTUAL,
 affected_style TEXT GENERATED ALWAYS AS (json_extract(payload, '$.affected_style')) VIRTUAL
);
CREATE TABLE IF NOT EXISTS event_updates (
 update_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(event_id),
 effective_at TEXT NOT NULL, known_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 payload TEXT NOT NULL CHECK(json_valid(payload)),
 update_time TEXT GENERATED ALWAYS AS (json_extract(payload, '$.effective_at')) VIRTUAL,
 information_gain TEXT GENERATED ALWAYS AS (json_extract(payload, '$.information_gain')) VIRTUAL,
 bias_change TEXT GENERATED ALWAYS AS (json_extract(payload, '$.bias_change')) VIRTUAL,
 channel_change TEXT GENERATED ALWAYS AS (json_extract(payload, '$.channel_change')) VIRTUAL,
 score_change REAL GENERATED ALWAYS AS (json_extract(payload, '$.score_change')) VIRTUAL
);
CREATE TABLE IF NOT EXISTS state_updates (
 state_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(event_id),
 effective_at TEXT NOT NULL, known_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS event_information (
 event_id TEXT NOT NULL REFERENCES events(event_id),
 information_id TEXT NOT NULL REFERENCES information_inbox(information_id),
 PRIMARY KEY(event_id, information_id)
);
CREATE TABLE IF NOT EXISTS legacy_audit (
 audit_id TEXT PRIMARY KEY, payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE INDEX IF NOT EXISTS updates_by_event ON event_updates(event_id, known_at, effective_at);
CREATE INDEX IF NOT EXISTS states_by_event ON state_updates(event_id, known_at, effective_at);
CREATE TABLE IF NOT EXISTS research_notes (
 note_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(event_id),
 kind TEXT NOT NULL CHECK(kind IN ('Parent','EventUpdate','MarketState')),
 known_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS collection_batches (
 batch_id TEXT PRIMARY KEY, known_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS source_checks (
 check_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES collection_batches(batch_id),
 known_at TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS collection_items (
 item_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES collection_batches(batch_id),
 information_id TEXT NOT NULL REFERENCES information_inbox(information_id),
 known_at TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS information_reviews (
 review_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES collection_batches(batch_id),
 information_id TEXT NOT NULL REFERENCES information_inbox(information_id),
 event_id TEXT REFERENCES events(event_id), known_at TEXT NOT NULL,
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS parent_reviews (
 review_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES collection_batches(batch_id),
 event_id TEXT NOT NULL REFERENCES events(event_id), known_at TEXT NOT NULL,
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE INDEX IF NOT EXISTS source_checks_by_batch ON source_checks(batch_id, known_at);
CREATE INDEX IF NOT EXISTS reviews_by_batch ON information_reviews(batch_id, information_id, known_at);
CREATE TABLE IF NOT EXISTS ai_research_runs (
 pack_id TEXT PRIMARY KEY, known_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS ai_assessments (
 assessment_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(event_id),
 pack_id TEXT NOT NULL REFERENCES ai_research_runs(pack_id), known_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE INDEX IF NOT EXISTS ai_assessments_by_event ON ai_assessments(event_id,known_at);

CREATE TABLE IF NOT EXISTS news_screening_runs (
 pack_id TEXT PRIMARY KEY, known_at TEXT NOT NULL,
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS information_screenings (
 screening_id TEXT PRIMARY KEY, information_id TEXT NOT NULL REFERENCES information_inbox(information_id),
 pack_id TEXT NOT NULL REFERENCES news_screening_runs(pack_id), known_at TEXT NOT NULL,
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE INDEX IF NOT EXISTS screenings_by_information ON information_screenings(information_id,known_at);

CREATE TABLE IF NOT EXISTS discovery_runs (
 pack_id TEXT PRIMARY KEY, known_at TEXT NOT NULL,
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS discovery_leads (
 lead_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES collection_batches(batch_id),
 source_id TEXT NOT NULL, normalized_url TEXT NOT NULL, known_at TEXT NOT NULL,
 payload TEXT NOT NULL CHECK(json_valid(payload)),
 UNIQUE(batch_id, source_id, normalized_url)
);
CREATE TABLE IF NOT EXISTS discovery_resolutions (
 resolution_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES collection_batches(batch_id),
 lead_id TEXT NOT NULL REFERENCES discovery_leads(lead_id),
 information_id TEXT REFERENCES information_inbox(information_id), known_at TEXT NOT NULL,
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE INDEX IF NOT EXISTS discovery_by_batch ON discovery_leads(batch_id,known_at);
CREATE INDEX IF NOT EXISTS discovery_history ON discovery_resolutions(lead_id,known_at);

-- Alpha generated columns are added idempotently by database/migrations.py.
-- Values here are append-time snapshots, not scores recalculated at arbitrary as_of.
CREATE VIEW IF NOT EXISTS event_states AS
 SELECT state_id, event_id, effective_at AS timestamp, known_at,
        json_extract(payload, '$.pricing_state') AS pricing_state,
        json_extract(payload, '$.acceptance') AS acceptance,
        json_extract(payload, '$.event_score') AS event_score,
        payload
 FROM state_updates;
