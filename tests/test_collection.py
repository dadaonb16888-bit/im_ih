"""Independent collection-ledger checks using a temporary, synthetic source plan."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from event_engine.collection import CollectionLedger, defaults
from event_engine.engine import CATEGORIES, EventEngine, utc


START = '2026-10-12T00:00:00+08:00'
CUTOFF = '2026-10-13T10:00:00+08:00'
CREATED = '2026-10-13T10:01:00+08:00'
FIRST = '2026-10-13T10:02:00+08:00'
LATER = '2026-10-13T10:03:00+08:00'
REPORT = '2026-10-13T10:04:00+08:00'
OLD = '2026-10-09T12:00:00+08:00'


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = EventEngine(Path(self.temp.name) / 'events.sqlite3')
        self.ledger = CollectionLedger(self.engine)
        self.source_plan = [
            {'source_id': 'S-' + category, 'name': category + ' primary',
             'url': 'https://example.invalid/' + category.lower(),
             'categories': [category], 'collect': 'official releases',
             'last_access_status': 'Readable', 'last_searched_at': OLD}
            for category in sorted(CATEGORIES)
        ]
        self.source_plan.append({
            'source_id': 'S-TECH-SECOND', 'name': 'independent technology source',
            'url': 'https://example.invalid/tech-second', 'categories': ['TECH'],
            'collect': 'official releases', 'last_access_status': 'Readable'})
        self.engine._insert('legacy_audit', 'audit_id', 'reference:sources.json',
                            {'content': self.source_plan})

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def batch(self, batch_id='batch', **changes):
        data = {'batch_id': batch_id, 'window_start': START, 'cutoff': CUTOFF,
                'window_reason': 'synthetic full-window review', 'known_at': CREATED}
        data.update(changes)
        self.ledger.create_batch(data)
        return data

    def parent(self, eid='existing', scope=None, known_at=OLD):
        data = {'event_id': eid, 'name': eid, 'detection_mode': 'News',
                'known_at': known_at, 'event_time': known_at, 'reviewed': False}
        if scope is not None:
            data['scope'] = scope
        self.engine.create_event(data)
        return eid

    def information(self, iid='info', published_at=CUTOFF, observed_at=CREATED,
                    url=None, batch_id='batch', known_at=FIRST):
        info = {'information_id': iid, 'title': 'synthetic ' + iid,
                'fact': 'Synthetic fact; no directional hypothesis.',
                'source_id': 'S-TECH', 'url': url or 'https://example.invalid/' + iid,
                'published_at': published_at, 'observed_at': observed_at}
        self.engine.add_information(info)
        self.ledger.add_item({'item_id': 'item-' + iid + '-' + batch_id,
            'batch_id': batch_id, 'information_id': iid, 'category': 'TECH',
            'known_at': known_at})
        return info

    def check(self, source_id='S-TECH', category='TECH', check_id=None,
              known_at=FIRST, **changes):
        data = {'check_id': check_id or 'check-' + source_id, 'batch_id': 'batch',
            'category': category, 'source_id': source_id, 'status': 'Complete',
            'searched_at': CUTOFF, 'known_at': known_at,
            'search_scope': 'All original releases in the declared window',
            'hit_count': 0, 'fulltext_status': 'NoHits',
            'evidence': ['fixture:checked-original-publication-index'], 'gaps': ''}
        data.update(changes)
        self.ledger.check_source(data)
        return data

    def triage(self, route='Pending', review_id='triage', eid=None, known_at=FIRST):
        data = {'review_id': review_id, 'batch_id': 'batch', 'information_id': 'info',
                'route': route, 'reason': 'Manual routing only, not causal approval',
                'evidence': ['fixture:original-fact'], 'known_at': known_at}
        if eid is not None:
            data['event_id'] = eid
        self.ledger.triage(data)
        return data

    def coverage(self, category='TECH', as_of=REPORT):
        return next(c for c in self.ledger.report('batch', as_of)['coverage']
                    if c['category'] == category)

    def test_defaults_use_china_calendar_and_expand_monday_weekend(self):
        tuesday = defaults('2026-10-13T02:00:00Z')
        self.assertEqual(tuesday['window_start'], START)
        self.assertEqual(tuesday['cutoff'], CUTOFF)
        monday = defaults('2026-10-12T01:00:00Z')
        self.assertEqual(monday['window_start'], '2026-10-09T00:00:00+08:00')
        self.assertEqual(monday['cutoff'], '2026-10-12T09:00:00+08:00')
        # UTC Sunday evening is already Monday in the user's timezone.
        midnight = defaults('2026-10-11T16:30:00Z')
        self.assertEqual(midnight['window_start'], '2026-10-09T00:00:00+08:00')

    def test_manual_holiday_window_preserves_start_and_reason(self):
        self.batch(window_start='2026-09-30T00:00:00+08:00',
                   window_reason='Explicit full holiday interval')
        batch = self.ledger.report('batch', REPORT)['batch']
        self.assertEqual(batch['window_start'], utc('2026-09-30T00:00:00+08:00'))
        self.assertEqual(batch['window_reason'], 'Explicit full holiday interval')
        self.assertEqual(batch['timezone'], 'Asia/Shanghai')

    def test_invalid_batch_time_order_and_naive_dates_rejected(self):
        for changes in ({'window_start': CUTOFF}, {'cutoff': LATER},
                        {'window_start': '2026-10-12'},
                        {'cutoff': '2026-10-13T10:00:00'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.batch(**changes)
        self.assertEqual(self.ledger.list_batches(REPORT), [])

    def test_inclusive_window_boundaries_unknown_times_and_late_discovery(self):
        self.batch()
        examples = [
            ('start', '2026-10-11T16:00:00Z', CUTOFF, 'InWindow'),
            ('end', '2026-10-13T02:00:00Z', CUTOFF, 'InWindow'),
            ('old', '2026-10-11T15:59:59.999999Z', CUTOFF, 'Late'),
            ('future', '2026-10-13T02:00:00.000001Z', CREATED, 'AfterCutoff'),
            ('unknown', None, CUTOFF, 'TimeUnknown'),
            ('date-only', '2026-10-12', CUTOFF, 'TimeUnknown'),
            ('discovered-late', START, CREATED, 'InWindow')]
        for iid, published, observed, _ in examples:
            self.information(iid, published_at=published, observed_at=observed)
        report = self.ledger.report('batch', REPORT)
        information = {i['information_id']: i for i in report['information']}
        for iid, _, _, relation in examples:
            with self.subTest(information_id=iid):
                self.assertEqual(information[iid]['temporal_relation'], relation)
        self.assertFalse(information['start']['found_late'])
        self.assertTrue(information['discovered-late']['found_late'])
        self.assertEqual(report['counts']['unknown_time'], 2)
        self.assertEqual(report['counts']['after_cutoff'], 1)
        self.assertFalse(report['ready'])

    def test_unreviewed_no_hits_and_blocked_are_distinct(self):
        self.batch()
        self.assertEqual(self.coverage()['status'], 'Unreviewed')
        self.check()
        partial = self.coverage()
        self.assertEqual(partial['status'], 'Partial')
        self.assertEqual(partial['missing_source_ids'], ['S-TECH-SECOND'])
        self.check(source_id='S-TECH-SECOND')
        complete = self.coverage()
        self.assertEqual(complete['status'], 'Complete')
        self.assertTrue(all(c['hit_count'] == 0 and c['fulltext_status'] == 'NoHits'
                            for c in complete['checks']))
        for sid in ('S-TECH', 'S-TECH-SECOND'):
            self.check(source_id=sid, check_id='blocked-' + sid, known_at=LATER,
                       status='Blocked', fulltext_status='Unavailable',
                       gaps='Original source inaccessible')
        blocked = self.coverage()
        self.assertEqual(blocked['status'], 'Blocked')
        self.assertNotEqual(blocked['status'], 'Complete')

    def test_complete_scan_cannot_end_before_cutoff(self):
        self.batch()
        with self.assertRaises(ValueError):
            self.check(searched_at='2026-10-13T09:59:59+08:00')
        self.assertEqual(self.coverage()['checks'], [])
        self.check(status='Partial', fulltext_status='Partial',
                   searched_at='2026-10-13T09:59:59+08:00',
                   gaps='Scan stopped before the declared cutoff')
        self.assertEqual(self.coverage()['checks'][0]['status'], 'Partial')

    def test_complete_scan_rejects_unread_fulltext_or_open_gaps(self):
        self.batch()
        bad = [dict(hit_count=1, fulltext_status='Partial'),
               dict(hit_count=1, fulltext_status='Unavailable'),
               dict(hit_count=1, fulltext_status='NoHits'),
               dict(hit_count=0, fulltext_status='Readable'),
               dict(hit_count=0, fulltext_status='NoHits', gaps='Unresolved source gap')]
        for index, changes in enumerate(bad):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.check(check_id='invalid-' + str(index), **changes)
        self.assertEqual(self.coverage()['checks'], [])
        self.check(hit_count=1, fulltext_status='Readable')
        self.assertEqual(self.coverage()['checks'][0]['fulltext_status'], 'Readable')

    def test_source_plan_is_frozen_and_old_access_claims_do_not_complete_it(self):
        self.batch()
        batch = self.ledger.report('batch', REPORT)['batch']
        self.assertEqual(len(batch['sources']), len(self.source_plan))
        self.assertTrue(all('last_access_status' not in s and 'last_searched_at' not in s
                            for s in batch['sources']))
        with patch.object(self.ledger, 'sources', return_value=[]):
            report = self.ledger.report('batch', REPORT)
        self.assertEqual(len(report['batch']['sources']), len(self.source_plan))
        self.assertEqual(report['counts']['missing_categories'], 14)
        self.assertFalse(report['ready'])

    def test_all_registered_sources_must_be_checked_for_ready_report(self):
        self.batch()
        for source in self.source_plan[:-1]:
            self.check(source_id=source['source_id'], category=source['categories'][0])
        report = self.ledger.report('batch', REPORT)
        self.assertEqual(report['counts']['missing_categories'], 1)
        self.assertFalse(report['ready'])
        self.check(source_id='S-TECH-SECOND')
        finished = self.ledger.report('batch', REPORT)
        self.assertEqual(finished['counts']['missing_categories'], 0)
        self.assertTrue(finished['ready'])
        self.assertEqual(finished['gaps'], [])

    def test_latest_coverage_correction_keeps_history_and_as_of_visibility(self):
        self.batch()
        self.check()
        self.check(source_id='S-TECH-SECOND')
        self.check(check_id='correction', known_at=LATER, status='Partial',
                   fulltext_status='Unavailable', gaps='Original fulltext was not verified')
        before = self.ledger.report('batch', FIRST)
        after = self.ledger.report('batch', REPORT)
        self.assertEqual(next(c for c in before['coverage'] if c['category'] == 'TECH')['status'],
                         'Complete')
        self.assertEqual(next(c for c in after['coverage'] if c['category'] == 'TECH')['status'],
                         'Partial')
        self.assertEqual(len(before['check_history']), 2)
        self.assertEqual(len(after['check_history']), 3)
        self.assertEqual(after['check_history'][0]['status'], 'Complete')

    def test_batch_items_and_later_routing_are_invisible_before_known_time(self):
        self.batch()
        self.assertEqual(self.ledger.list_batches('2026-10-13T10:00:59+08:00'), [])
        with self.assertRaises(ValueError):
            self.ledger.report('batch', CUTOFF)
        self.information(observed_at=CREATED)
        self.assertEqual(self.ledger.report('batch', CREATED)['information'], [])
        self.triage('Background', known_at=LATER)
        before = self.ledger.report('batch', FIRST)
        after = self.ledger.report('batch', REPORT)
        self.assertIsNone(before['information'][0]['routing'])
        self.assertEqual(before['counts']['pending_triage'], 1)
        self.assertEqual(before['routing_history'], [])
        self.assertEqual(after['information'][0]['routing']['route'], 'Background')
        self.assertEqual(after['counts']['pending_triage'], 0)

    def test_future_observation_cannot_be_associated_early(self):
        self.batch()
        info = {'information_id': 'not-yet-seen', 'title': 'future observation',
                'published_at': CUTOFF, 'observed_at': LATER}
        self.engine.add_information(info)
        with self.assertRaises(ValueError):
            self.ledger.add_item({'item_id': 'early', 'batch_id': 'batch',
                'information_id': 'not-yet-seen', 'category': 'TECH', 'known_at': FIRST})
        self.assertEqual(self.ledger.report('batch', FIRST)['information'], [])

    def test_item_category_correction_is_append_only_and_visible_when_known(self):
        self.batch()
        self.information()
        same = self.ledger.add_item({'item_id': 'duplicate-association', 'batch_id': 'batch',
            'information_id': 'info', 'category': 'TECH', 'known_at': LATER})
        self.assertFalse(same)
        self.ledger.add_item({'item_id': 'corrected-association', 'batch_id': 'batch',
            'information_id': 'info', 'category': 'POLICY_GROWTH',
            'notes': 'Original classification corrected after reading the policy',
            'known_at': LATER})
        before = self.ledger.report('batch', FIRST)['information']
        after = self.ledger.report('batch', REPORT)['information']
        self.assertEqual(len(before), 1)
        self.assertEqual(len(after), 1)
        self.assertEqual(before[0]['category'], 'TECH')
        self.assertEqual(after[0]['category'], 'POLICY_GROWTH')
        self.assertIn('corrected', after[0]['collection_notes'])
        rows = self.engine.db.execute(
            'SELECT payload FROM collection_items WHERE information_id=? ORDER BY known_at,rowid',
            ('info',)).fetchall()
        self.assertEqual(len(rows), 2)

    def test_duplicate_urls_warn_but_retain_independent_inbox_records(self):
        self.batch()
        self.information('first', observed_at=FIRST,
                         url='https://EXAMPLE.invalid/story?id=1&utm_source=test#paragraph')
        self.information('second', observed_at=LATER, known_at=LATER,
                         url='https://example.invalid/story?id=1')
        self.information('different', observed_at=LATER, known_at=LATER,
                         url='https://example.invalid/story?id=2')
        early = self.ledger.report('batch', FIRST)
        self.assertEqual(early['information'][0]['duplicate_ids'], [])
        all_records = self.ledger.report('batch', REPORT)['information']
        by_id = {i['information_id']: i for i in all_records}
        self.assertEqual(by_id['first']['duplicate_ids'], ['second'])
        self.assertEqual(by_id['second']['duplicate_ids'], ['first'])
        self.assertEqual(by_id['different']['duplicate_ids'], [])
        self.assertEqual(len(all_records), 3)
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM information_inbox').fetchone()[0], 3)

    def test_five_routing_choices_do_not_create_bias_or_market_state(self):
        # Explicit scope omitted to exercise the established Current default.
        self.parent()
        self.batch()
        self.information()
        for index, route in enumerate(('NewParent', 'EventUpdate', 'MarketState',
                                        'Background', 'Pending')):
            self.triage(route, review_id='route-' + str(index),
                        eid='existing' if route in ('NewParent', 'EventUpdate', 'MarketState') else None)
        report = self.ledger.report('batch', REPORT)
        self.assertEqual(len(report['routing_history']), 5)
        self.assertEqual(report['information'][0]['routing']['route'], 'Pending')
        snapshot = self.engine.snapshot('existing', REPORT)
        self.assertIsNone(snapshot.get('bias'))
        self.assertIsNone(snapshot['acceptance'])
        self.assertIsNone(snapshot['pricing_state'])
        self.assertFalse(snapshot['entry_allowed'])
        self.assertEqual(snapshot['qualification'], 'WATCH')
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
        for table in ('event_updates', 'state_updates'):
            self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)

    def test_latest_routing_correction_preserves_old_judgment(self):
        self.batch()
        self.information()
        self.triage('Background', review_id='first-route')
        self.triage('Pending', review_id='correction-route', known_at=LATER)
        before = self.ledger.report('batch', FIRST)
        after = self.ledger.report('batch', REPORT)
        self.assertEqual(before['information'][0]['routing']['route'], 'Background')
        self.assertEqual(after['information'][0]['routing']['route'], 'Pending')
        self.assertEqual([r['route'] for r in after['routing_history']], ['Background', 'Pending'])

    def test_existing_parent_followups_are_frozen_with_batch(self):
        self.parent('old')
        self.parent('historical', scope='Historical')
        self.parent('closed', scope='Current')
        self.engine.update_event({'update_id': 'invalidate', 'event_id': 'closed',
            'known_at': '2026-10-10T10:00:00+08:00',
            'effective_at': '2026-10-10T10:00:00+08:00', 'source_type': 'Policy',
            'information_gain': 'High', 'facts': 'Original policy withdrawn',
            'reason': 'New causal evidence invalidates the premise',
            'evidence': ['fixture:withdrawal'], 'invalidate': True})
        self.batch()
        self.parent('created-later', known_at=FIRST)
        initial = self.ledger.report('batch', REPORT)
        self.assertEqual(initial['batch']['parent_ids'], ['old'])
        self.assertEqual(initial['counts']['pending_parent_reviews'], 1)
        self.ledger.review_parent({'review_id': 'followup', 'batch_id': 'batch',
            'event_id': 'old', 'result': 'NoChange', 'reason': 'No additional causal facts found',
            'evidence': ['fixture:old-parent-progress-check'], 'known_at': LATER})
        self.assertIsNone(self.ledger.report('batch', FIRST)['parent_followups'][0]['review'])
        final = self.ledger.report('batch', REPORT)
        self.assertEqual(final['counts']['pending_parent_reviews'], 0)
        self.assertEqual(final['parent_followups'][0]['review']['result'], 'NoChange')
        self.assertEqual(final['parent_followups'][0]['scope'], 'Current')
        with self.assertRaises(ValueError):
            self.ledger.review_parent({'review_id': 'wrong-parent', 'batch_id': 'batch',
                'event_id': 'created-later', 'result': 'NoChange', 'reason': 'Not on the original list',
                'evidence': ['fixture:invalid-followup'], 'known_at': REPORT})

    def test_new_collection_tables_reject_updates_and_deletes(self):
        self.parent(scope='Current')
        self.batch()
        self.information()
        self.check()
        self.triage('Background')
        self.ledger.review_parent({'review_id': 'followup', 'batch_id': 'batch',
            'event_id': 'existing', 'result': 'Pending', 'reason': 'Originals not yet readable',
            'evidence': ['fixture:followup-gap'], 'known_at': FIRST})
        tables = ('collection_batches', 'source_checks', 'collection_items',
                  'information_reviews', 'parent_reviews')
        for table in tables:
            original = [tuple(r) for r in self.engine.db.execute('SELECT * FROM ' + table)]
            for sql in ('UPDATE ' + table + ' SET payload=payload', 'DELETE FROM ' + table):
                with self.subTest(table=table, sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    self.engine.db.execute(sql)
                self.engine.db.rollback()
                self.assertEqual([tuple(r) for r in self.engine.db.execute('SELECT * FROM ' + table)], original)


if __name__ == '__main__':
    unittest.main()
