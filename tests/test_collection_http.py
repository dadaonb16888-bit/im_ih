"""Public workbench operations against a disposable database, never the research ledger."""
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
from workbench import make_handler
from event_engine.engine import EventEngine
from event_engine.discovery import DiscoveryLedger


class CollectionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'events.sqlite3'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.database))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.temp.cleanup()

    def request(self, path, data=None):
        req = Request(self.base + path, data=json.dumps(data).encode('utf-8') if data is not None else None,
                      headers={'Content-Type': 'application/json', 'X-Event-Workbench': '1'})
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read())

    def batch(self):
        end = datetime.now(timezone.utc) - timedelta(minutes=1)
        return self.request('/api/collection', {'window_start': (end - timedelta(days=1)).isoformat(),
            'cutoff': end.isoformat(), 'window_reason': '测试窗口',
            'known_at': '2000-01-01T00:00:00Z'})['id']

    def test_discovery_is_visible_asof_and_has_no_public_write_route(self):
        batch = self.batch()
        before = datetime.now(timezone.utc).isoformat()
        engine = EventEngine(self.database)
        try:
            DiscoveryLedger(engine).apply_pack({'pack_id': 'HTTP-fixture', 'leads': [{
                'lead_id': 'L', 'batch_id': batch, 'source_id': 'PBC', 'title': '<script>fixture</script>',
                'url': 'https://example.org/news', 'index_url': 'https://example.org/',
                'captured_at': before, 'evidence': ['fixture:index']}], 'resolutions': []})
        finally:
            engine.close()
        report = self.request('/api/collection?id=' + batch)
        self.assertEqual(report['discovery']['counts']['Pending'], 1)
        self.assertEqual(report['counts']['unresolved_leads'], 1)
        old = self.request('/api/collection?id=' + batch + '&as_of=' + before.replace('+', '%2B'))
        self.assertEqual(old['discovery']['leads'], [])
        with self.assertRaises(HTTPError) as err:
            self.request('/api/apply-discovery', {'actor': 'Codex'})
        self.assertEqual(err.exception.code, 404)

    def test_complete_ui_flow_preserves_draft_and_history(self):
        plan = self.request('/api/collection-plan')
        self.assertEqual(len(plan['categories']), 14)
        self.assertEqual(len(plan['sources']), 26)
        self.assertTrue(all('access_status' not in s for s in plan['sources']))
        event = self.request('/api/parent', {'name': 'fixture', 'detection_mode': 'News'})['id']
        batch = self.batch()
        report = self.request('/api/collection?id=' + batch)
        self.assertNotEqual(report['batch']['known_at'], '2000-01-01T00:00:00Z')
        self.assertEqual(report['counts']['missing_categories'], 14)
        self.assertEqual(report['counts']['pending_parent_reviews'], 1)
        self.assertFalse(report['ready'])
        cutoff = report['batch']['cutoff']
        info = self.request('/api/information', {'title': 'fixture', 'fact': '测试事实',
            'url': 'https://example.com/original', 'published_at': cutoff,
            'first_seen_at': cutoff, 'first_seen_evidence': '测试发现日志',
            'batch_id': batch, 'category': 'TECH'})['id']
        self.request('/api/triage', {'batch_id': batch, 'information_id': info,
            'route': 'EventUpdate', 'event_id': event, 'reason': '归并机制', 'evidence': ['fixture']})
        self.request('/api/parent-review', {'batch_id': batch, 'event_id': event,
            'result': 'NewInformation', 'reason': '发现新增资料，因果待审核', 'evidence': ['fixture']})
        report = self.request('/api/collection?id=' + batch)
        self.assertEqual(report['counts']['pending_triage'], 0)
        self.assertEqual(report['counts']['pending_parent_reviews'], 0)
        self.assertEqual(report['information'][0]['temporal_relation'], 'InWindow')
        self.assertFalse(report['information'][0]['found_late'])
        self.assertGreater(report['information'][0]['recorded_at'], cutoff)
        snapshot = self.request('/api/event?id=' + event)
        self.assertIsNone(snapshot['snapshot']['bias'])
        self.assertEqual(snapshot['market_states'], [])
        self.assertEqual(snapshot['causal_updates'], [])
        self.assertFalse(snapshot['snapshot']['entry_allowed'])
        self.assertEqual(snapshot['linked_information'][0]['information_id'], info)

    def test_information_and_membership_are_atomic(self):
        batch = self.batch()
        with self.assertRaises(HTTPError) as err:
            self.request('/api/information', {'title': 'invalid category', 'batch_id': batch,
                         'category': 'BAD'})
        self.assertEqual(err.exception.code, 400)
        self.assertEqual(self.request('/api/information'), [])
        with self.assertRaises(HTTPError):
            self.request('/api/information', {'title': 'unknown batch', 'batch_id': 'missing', 'category': 'TECH'})
        self.assertEqual(self.request('/api/information'), [])

    def test_first_sighting_requires_evidence_and_known_at_cannot_be_forged(self):
        batch = self.batch()
        with self.assertRaises(HTTPError):
            self.request('/api/information', {'title': 'fixture', 'first_seen_at': '2026-10-01T00:00:00+08:00'})
        cutoff = self.request('/api/collection?id=' + batch)['batch']['cutoff']
        self.request('/api/source-check', {'batch_id': batch, 'category': 'MONETARY', 'source_id': 'PBC',
            'status': 'Complete', 'searched_at': cutoff, 'search_scope': '测试完整窗口原文列表',
            'hit_count': 0, 'fulltext_status': 'NoHits', 'evidence': ['fixture'],
            'gaps': '', 'known_at': cutoff})
        after = self.request('/api/collection?id=' + batch)
        self.assertEqual(len(after['check_history']), 1)
        self.assertGreater(after['check_history'][0]['known_at'], cutoff)
        # An as-of before creation is rejected instead of exposing a later scan.
        with self.assertRaises(HTTPError) as err:
            self.request('/api/collection?id=' + batch + '&as_of=' + cutoff)
        self.assertEqual(err.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
