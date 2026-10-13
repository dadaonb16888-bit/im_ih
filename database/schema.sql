PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS information_inbox (
 information_id TEXT PRIMARY KEY, payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, known_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS event_updates (
 update_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(event_id),
 effective_at TEXT NOT NULL, known_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 payload TEXT NOT NULL CHECK(json_valid(payload))
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
