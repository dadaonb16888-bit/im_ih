"""Discovery cannot turn an unread headline into facts, coverage, or alpha."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from event_engine.collection import CollectionLedger
from event_engine.discovery import DiscoveryLedger
from event_engine.engine import EventEngine, utc


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.engine = EventEngine(self.path)
        self.ledger = DiscoveryLedger(self.engine)
        self.stamp = utc('2026-10-15T10:00:00Z')
        CollectionLedger(self.engine).create_batch({'batch_id': 'B',
            'window_start': '2026-10-14T00:00:00Z', 'cutoff': '2026-10-15T08:00:00Z',
            'known_at': '2026-10-15T08:01:00Z', 'window_reason': 'synthetic'})
        self.lead = {'lead_id': 'L', 'batch_id': 'B', 'source_id': 'PBC',
            'title': '<untrusted headline>', 'url': 'https://example.org/news?utm_source=x#top',
            'index_url': 'https://example.org/', 'captured_at': '2026-10-15T08:00:00Z',
            'date_clue': '10月15日，时刻未核', 'evidence': ['fixture:index-capture']}

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def apply(self, leads=None, resolutions=None, pack_id='P'):
        pack = {'pack_id': pack_id, 'leads': leads or [], 'resolutions': resolutions or []}
        with patch('event_engine.discovery.now', return_value=self.stamp):
            return self.ledger.apply_pack(pack)

    def resolution(self, **changes):
        return {'resolution_id': 'R', 'lead_id': 'L', 'batch_id': 'B',
            'prior_resolution_id': None, 'status': 'Blocked', 'reason': 'Original blocked',
            'evidence': ['fixture:403'], **changes}

    def info(self, **changes):
        self.engine.add_information({'information_id': 'I', 'title': 'Read original',
            'url': 'https://example.org/news', 'read_status': 'Read',
            'recorded_at': self.stamp, 'observed_at': self.stamp, **changes})

    def test_unread_lead_is_not_raw_fact_and_never_backdated(self):
        result = self.apply([self.lead])
        self.assertEqual(result['known_at'], self.stamp)
        self.assertEqual(self.ledger.report('B', '2026-10-15T09:59:59Z')['leads'], [])
        report = CollectionLedger(self.engine).report('B', self.stamp)
        self.assertEqual(report['counts']['unresolved_leads'], 1)
        self.assertEqual(report['discovery']['leads'][0]['url'], 'https://example.org/news')
        self.assertFalse(report['ready'])
        for table in ('information_inbox', 'information_screenings', 'events', 'event_updates', 'state_updates'):
            self.assertEqual(self.engine.db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)

    def test_exact_pack_replay_and_changed_content(self):
        self.apply([self.lead])
        self.assertFalse(self.apply([self.lead])['inserted'])
        changed = {**self.lead, 'title': 'Different'}
        with self.assertRaisesRegex(ValueError, '内容不同'):
            self.apply([changed])

    def test_same_source_normalized_duplicate_rejected(self):
        self.apply([self.lead])
        with self.assertRaisesRegex(ValueError, 'URL已登记'):
            self.apply([{**self.lead, 'lead_id': 'L2', 'url': 'https://example.org/news'}], pack_id='P2')
        self.assertEqual(self.engine.db.execute('SELECT count(*) FROM discovery_runs').fetchone()[0], 1)

    def test_all_or_nothing_invalid_source_and_future_capture(self):
        for bad in ({'source_id': 'UNREGISTERED'}, {'captured_at': '2027-01-01T00:00:00Z'},
                    {'url': 'javascript:alert(1)'}, {'url': 'https://user:secret@example.org/'},
                    {'known_at': '2000-01-01T00:00:00Z'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.apply([self.lead, {**self.lead, 'lead_id': 'L2', **bad}])
            self.assertEqual(self.engine.db.execute('SELECT count(*) FROM discovery_leads').fetchone()[0], 0)
            self.assertEqual(self.engine.db.execute('SELECT count(*) FROM discovery_runs').fetchone()[0], 0)

    def test_missing_or_future_batch_rejected(self):
        for change in ({'batch_id': 'missing'},):
            with self.assertRaises(ValueError):
                self.apply([{**self.lead, **change}])
        self.stamp = utc('2026-10-15T07:00:00Z')
        with self.assertRaises(ValueError):
            self.apply([self.lead])

    def test_append_history_optimistic_revision_and_asof(self):
        self.apply([self.lead], [self.resolution()])
        first = self.stamp
        self.stamp = utc('2026-10-15T11:00:00Z')
        self.apply(resolutions=[self.resolution(resolution_id='R2', prior_resolution_id='R',
            status='Excluded', reason='Index navigation link, no news article')], pack_id='P2')
        self.assertEqual(self.ledger.report('B', first)['leads'][0]['status'], 'Blocked')
        self.assertEqual(self.ledger.report('B', self.stamp)['unresolved'], 0)
        with self.assertRaisesRegex(ValueError, '过时'):
            self.apply(resolutions=[self.resolution(resolution_id='R3')], pack_id='P3')
        self.assertEqual(len(self.ledger.report('B', self.stamp)['history']), 2)

    def test_link_requires_matching_visible_read_original(self):
        self.apply([self.lead])
        resolution = self.resolution(status='Linked', information_id='I')
        with self.assertRaisesRegex(ValueError, '不存在'):
            self.apply(resolutions=[resolution], pack_id='P2')
        self.info(url='https://example.org/unrelated')
        with self.assertRaisesRegex(ValueError, 'URL'):
            self.apply(resolutions=[resolution], pack_id='P2')

    def test_unread_and_future_original_cannot_be_linked(self):
        for changes in ({'read_status': 'Unavailable'}, {'recorded_at': '2027-01-01T00:00:00Z'}):
            with self.subTest(changes=changes):
                # Use distinct ids; source rows are immutable.
                iid = 'I-' + str(len(changes)) + next(iter(changes))
                self.info(information_id=iid, **changes)
                if not self.ledger.report('B', self.stamp)['leads']:
                    self.apply([self.lead])
                with self.assertRaises(ValueError):
                    self.apply(resolutions=[self.resolution(status='Linked', information_id=iid)], pack_id='P2')

    def test_partial_original_still_counts_gap(self):
        self.info(read_status='Partial')
        self.apply([self.lead], [self.resolution(status='Linked', information_id='I')])
        report = self.ledger.report('B', self.stamp)
        self.assertEqual(report['counts']['Linked'], 1)
        self.assertEqual(report['counts']['PartialRead'], 1)
        self.assertEqual(report['unresolved'], 1)

    def test_read_original_closes_lead_but_does_not_create_screening(self):
        self.info()
        self.apply([self.lead], [self.resolution(status='Linked', information_id='I')])
        self.assertEqual(self.ledger.report('B', self.stamp)['unresolved'], 0)
        self.assertEqual(self.engine.db.execute('SELECT count(*) FROM information_screenings').fetchone()[0], 0)

    def test_database_upgrade_and_immutable_history(self):
        self.info()
        self.engine.close()
        # Simulate an older installation lacking every discovery table.
        with closing(sqlite3.connect(self.path)) as db:
            for table in ('discovery_resolutions', 'discovery_leads', 'discovery_runs'):
                db.execute('DROP TABLE ' + table)
            db.commit()
        self.engine = EventEngine(self.path)
        self.ledger = DiscoveryLedger(self.engine)
        self.assertEqual(self.engine.db.execute('SELECT count(*) FROM information_inbox').fetchone()[0], 1)
        self.apply([self.lead], [self.resolution()])
        self.engine.close()
        self.engine = EventEngine(self.path)
        self.ledger = DiscoveryLedger(self.engine)
        self.assertEqual(len(self.ledger.report('B', self.stamp)['leads']), 1)
        for table in ('discovery_leads', 'discovery_runs', 'discovery_resolutions'):
            for sql in ('DELETE FROM ' + table, 'UPDATE ' + table + ' SET payload=payload'):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.engine.db.execute(sql)
                self.engine.db.rollback()

    def test_older_resolution_cannot_hide_newer_decision(self):
        self.apply([self.lead], [self.resolution()])
        self.stamp = utc('2026-10-15T11:00:00Z')
        self.apply(resolutions=[self.resolution(resolution_id='R2', prior_resolution_id='R')], pack_id='P2')
        self.stamp = utc('2026-10-15T10:30:00Z')
        with self.assertRaisesRegex(ValueError, '倒插'):
            self.apply(resolutions=[self.resolution(resolution_id='R3', prior_resolution_id='R2')], pack_id='P3')

    def test_nonlinked_reference_and_missing_predecessor_rejected(self):
        self.apply([self.lead])
        for record in (self.resolution(information_id='I'),
                       {k: v for k, v in self.resolution().items() if k != 'prior_resolution_id'}):
            with self.assertRaises(ValueError):
                self.apply(resolutions=[record], pack_id='P2')
