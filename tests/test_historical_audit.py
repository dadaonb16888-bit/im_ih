import copy
import json
import tempfile
import unittest
from pathlib import Path

from apply_historical_audit import apply
from event_engine.engine import EventEngine, ROOT
from event_engine.csv_io import import_research

T0 = '2026-10-10T12:00:00+08:00'
T1 = '2026-10-11T12:00:00+08:00'
T2 = '2026-10-12T12:00:00+08:00'


class HistoricalAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = EventEngine(Path(self.temp.name) / 'events.sqlite3')
        import_research(self.engine, ROOT / 'data' / 'events', T0)
        self.package = json.loads((ROOT / 'data' / 'historical_audit_v1.json').read_text(encoding='utf-8'))

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def test_audit_does_not_backdate_or_activate_historical_signals(self):
        self.assertEqual(apply(self.engine, self.package, T1),
                         {'information': 7, 'audit_notes': 3, 'draft_updates': 2})
        for card in self.package['cards']:
            before = self.engine.history(card['event_id'], T0)
            after = self.engine.history(card['event_id'], T1)
            self.assertFalse(any(n['claim'].get('audit') for n in before['research_notes']))
            self.assertTrue(any(n['claim'].get('audit') for n in after['research_notes']))
            self.assertIsNone(after['snapshot'].get('bias'))
            self.assertIsNone(after['snapshot'].get('event_time'))
            self.assertFalse(after['snapshot']['reviewed'])
            self.assertEqual(after['snapshot']['qualification'], 'WATCH')
            self.assertFalse(after['market_states'])
        self.assertEqual(self.engine.report(T1)['events'], [])

    def test_repeat_is_idempotent_and_preserves_original_knowledge_time(self):
        apply(self.engine, self.package, T1)
        self.assertEqual(apply(self.engine, self.package, T2),
                         {'information': 0, 'audit_notes': 0, 'draft_updates': 0})
        note = self.engine.history('202409_POLICY_PIVOT', T2)['research_notes'][-1]
        self.assertTrue(note['known_at'].startswith('2026-10-11'))

    def test_unknown_event_rolls_back_sources_notes_and_links(self):
        bad = copy.deepcopy(self.package)
        bad['cards'][-1]['event_id'] = 'UNKNOWN'
        with self.assertRaises(ValueError):
            apply(self.engine, bad, T1)
        for table in ('information_inbox', 'event_information', 'event_updates'):
            self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM research_notes').fetchone()[0], 16)


if __name__ == '__main__':
    unittest.main()
