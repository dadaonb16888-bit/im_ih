import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from apply_daily_collection import apply
from event_engine.engine import EventEngine, utc


class DailyImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = EventEngine(Path(self.temp.name) / 'ledger.sqlite3')
        self.engine._insert('legacy_audit', 'audit_id', 'reference:sources.json', {'content': []})
        self.stamp = '2026-10-14T01:00:00+00:00'
        self.package = {
            'package_id': 'synthetic',
            'batch': {'batch_id': 'B', 'window_start': '2026-10-13T00:00:00+08:00',
                      'cutoff': '2026-10-14T08:20:00+08:00', 'window_reason': 'synthetic'},
            'information': [{'information_id': 'I', 'title': 'Synthetic publication',
                             'published_at': '2026-10-13', 'observed_at': '2020-01-01T00:00:00Z'}],
            'parents': [{'event_id': 'E', 'name': 'Synthetic draft', 'detection_mode': 'News'}],
            'source_checks': [], 'items': [{'item_id': 'M', 'information_id': 'I', 'category': 'TECH'}],
            'triage': [{'review_id': 'R', 'information_id': 'I', 'event_id': 'E',
                        'route': 'NewParent', 'reason': 'Synthetic grouping', 'evidence': ['fixture:read']}],
            'parent_reviews': []}

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def run_import(self, package=None):
        with patch('apply_daily_collection.now', return_value=utc(self.stamp)):
            return apply(self.engine, package or self.package)

    def test_replay_preserves_actual_knowledge_and_never_creates_signal(self):
        first = self.run_import()
        replay = self.run_import()
        self.assertTrue(first['inserted'])
        self.assertFalse(replay['inserted'])
        info = json.loads(self.engine.db.execute('SELECT payload FROM information_inbox').fetchone()[0])
        self.assertEqual(info['observed_at'], utc(self.stamp))
        self.assertEqual(info['published_at'], '2026-10-13')
        self.assertIsNone(self.engine.snapshot('E', self.stamp)['bias'])
        self.assertIsNone(self.engine.snapshot('E', '2026-10-14T00:59:59Z'))
        self.assertEqual(self.engine.db.execute('SELECT count(*) FROM event_updates').fetchone()[0], 0)
        self.assertEqual(self.engine.db.execute('SELECT count(*) FROM state_updates').fetchone()[0], 0)

    def test_failed_routing_rolls_back_whole_batch(self):
        broken = deepcopy(self.package)
        broken['triage'][0]['event_id'] = 'missing'
        with self.assertRaises(ValueError):
            self.run_import(broken)
        for table in ('collection_batches', 'information_inbox', 'events', 'collection_items', 'information_reviews'):
            self.assertEqual(self.engine.db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
        self.assertEqual(self.engine.db.execute("SELECT count(*) FROM legacy_audit WHERE audit_id LIKE 'daily-collection:%'").fetchone()[0], 0)

    def test_changed_content_and_mismatched_batch_are_rejected(self):
        wrong = deepcopy(self.package)
        wrong['items'][0]['batch_id'] = 'different'
        with self.assertRaises(ValueError):
            self.run_import(wrong)
        self.run_import()
        changed = deepcopy(self.package)
        changed['information'][0]['title'] = 'Replacement'
        with self.assertRaises(ValueError):
            self.run_import(changed)
        self.assertEqual(self.engine.db.execute('SELECT count(*) FROM information_inbox').fetchone()[0], 1)

    def test_future_discovery_is_not_accepted(self):
        broken = deepcopy(self.package)
        broken['information'][0]['first_seen_at'] = '2026-10-14T02:00:00Z'
        with self.assertRaises(ValueError):
            self.run_import(broken)
        self.assertEqual(self.engine.db.execute('SELECT count(*) FROM collection_batches').fetchone()[0], 0)
