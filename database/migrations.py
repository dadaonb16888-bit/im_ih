"""Idempotent additive JSON projections; immutable ledger payloads stay intact."""

EVENT_COLUMNS = {
    'name': ('TEXT', '$.name'), 'channel': ('TEXT', '$.channels[0]'),
    'horizon': ('TEXT', '$.horizon'), 'bias': ('TEXT', '$.bias'),
    'impact': ('REAL', '$.impact_score'), 'confidence': ('REAL', '$.confidence_score'),
    'score': ('REAL', '$.score'), 'created_time': ('TEXT', '$.known_at'),
    'status': ('TEXT', '$.status'), 'source': ('TEXT', '$.source'),
    'source_reliability': ('TEXT', '$.source_reliability'),
    'persistence_score': ('REAL', '$.persistence_score'),
    'event_strength': ('REAL', '$.event_strength'), 'affected_style': ('TEXT', '$.affected_style'),
}
UPDATE_COLUMNS = {
    'update_time': ('TEXT', '$.effective_at'), 'information_gain': ('TEXT', '$.information_gain'),
    'bias_change': ('TEXT', '$.bias_change'), 'channel_change': ('TEXT', '$.channel_change'),
    'score_change': ('REAL', '$.score_change'),
}


def upgrade_alpha_schema(db):
    db.execute('SAVEPOINT alpha_schema_upgrade')
    try:
        for table, columns in [('events', EVENT_COLUMNS), ('event_updates', UPDATE_COLUMNS)]:
            existing = {r[1] for r in db.execute('PRAGMA table_xinfo(' + table + ')')}
            for name, (kind, path) in columns.items():
                if name not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind} GENERATED ALWAYS AS (json_extract(payload, '{path}')) VIRTUAL")
        if db.execute('PRAGMA user_version').fetchone()[0] < 2:
            db.execute('PRAGMA user_version = 2')
        db.execute('RELEASE SAVEPOINT alpha_schema_upgrade')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT alpha_schema_upgrade')
        db.execute('RELEASE SAVEPOINT alpha_schema_upgrade')
        raise
