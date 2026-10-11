import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from event_engine.engine import EventEngine, utc
from manage import migrate

T0 = '2026-10-09T10:00:00+08:00'
T1 = '2026-10-09T10:01:00+08:00'
T2 = '2026-10-09T10:02:00+08:00'
T3 = '2026-10-09T10:03:00+08:00'
T4 = '2026-10-09T10:04:00+08:00'


class EventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = EventEngine(Path(self.temp.name) / 'test.sqlite3')

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def parent(self, eid='test'):
        self.engine.create_event({'event_id': eid, 'name': '测试事件', 'detection_mode': 'News',
                                  'known_at': T0, 'event_time': T0})

    def initial(self, eid='test', bias='IH', horizon='Fast'):
        self.parent(eid)
        self.engine.update_event({'update_id': eid + '-u1', 'event_id': eid,
            'known_at': T1, 'effective_at': T1, 'source_type': 'Policy',
            'information_gain': 'High', 'facts': '测试事实', 'reason': '测试独立传导',
            'evidence': ['fixture:政策原文'], 'changes': {'bias': bias, 'channels': ['MARKET_LIQUIDITY'],
            'horizon': horizon, 'directness': 2, 'independent_cause': True, 'relative_pricing': True,
            'reviewed': True, 'first_tradable_time': T1, 'invalidation': '政策撤回'}})

    def state(self, eid='test', acceptance='Confirmed', pricing='Diffusing', stamp=T2, known=None, sid=None):
        return self.engine.update_state({'state_id': sid or eid + '-s1', 'event_id': eid,
            'known_at': known or stamp, 'effective_at': stamp, 'acceptance': acceptance,
            'pricing_state': pricing, 'method': '测试同步相对价格', 'evidence': ['fixture:行情']})

    def test_price_rejection_does_not_change_event(self):
        self.initial()
        self.state(acceptance='Rejected')
        s = self.engine.snapshot('test', T3)
        self.assertEqual(s['bias'], 'IH')
        self.assertEqual(s['initial_bias'], 'IH')
        self.assertEqual(s['causal_status'], 'Active')
        self.assertEqual(s['qualification'], 'WATCH')

    def test_state_forbids_bias_and_price_forbids_event_update(self):
        self.initial()
        with self.assertRaises(ValueError):
            self.engine.update_state({'state_id': 'bad', 'event_id': 'test', 'bias': 'IM'})
        with self.assertRaises(ValueError):
            self.engine.update_event({'update_id': 'bad', 'event_id': 'test', 'source_type': 'MarketPrice',
                'information_gain': 'High', 'facts': '涨了', 'reason': '所以改方向', 'evidence': ['price']})

    def test_rotation_same_parent_resets_old_confirmation(self):
        self.initial()
        self.state()
        self.engine.update_event({'update_id': 'rotate', 'event_id': 'test', 'known_at': T3,
            'effective_at': T3, 'source_type': 'Policy', 'information_gain': 'High',
            'facts': '新的扩散机制', 'reason': '传导从信用转向风险偏好', 'evidence': ['fixture:new'],
            'changes': {'bias': 'IM', 'channels': ['RISK_APPETITE']}})
        s = self.engine.snapshot('test', T4)
        self.assertEqual((s['initial_bias'], s['bias']), ('IH', 'IM'))
        self.assertIsNone(s['acceptance'])
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)

    def test_low_repeat_does_not_erase_meaningful_gain(self):
        self.initial()
        self.engine.update_event({'update_id': 'repeat', 'event_id': 'test', 'known_at': T2,
            'effective_at': T2, 'source_type': 'News', 'information_gain': 'Low',
            'facts': '重复报道', 'reason': '无新增事实', 'evidence': ['fixture:repeat']})
        self.assertEqual(self.engine.snapshot('test', T3)['information_gain'], 'High')

    def test_same_timestamp_rotation_does_not_reuse_old_state(self):
        self.initial()
        self.state(stamp=T3)
        self.engine.update_event({'update_id':'rotate-same-time','event_id':'test',
            'known_at':T3,'effective_at':T3,'source_type':'Policy','information_gain':'High',
            'facts':'新的风险偏好机制','reason':'同时间戳的后续信息','evidence':['fixture'],
            'changes':{'bias':'IM'}})
        self.assertIsNone(self.engine.snapshot('test', T4)['acceptance'])

    def test_future_annotation_is_invisible(self):
        self.initial()
        self.state(stamp=T2, known=T4)
        self.assertIsNone(self.engine.snapshot('test', T3)['acceptance'])
        self.assertEqual(self.engine.snapshot('test', T4)['acceptance'], 'Confirmed')
        self.assertIsNone(self.engine.snapshot('test', '2026-10-09T09:59:00+08:00'))

    def test_conflicting_equal_rank_has_no_dominant(self):
        self.initial('im', 'IM')
        self.initial('ih', 'IH')
        self.state('im')
        self.state('ih')
        d = self.engine.report(T3)['dominant']['Intraday']
        self.assertTrue(d['conflict'])
        self.assertIsNone(d['event_id'])

    def test_horizon_separation_and_not_an_order(self):
        self.initial('trend', 'IM', 'Trend')
        self.state('trend')
        r = self.engine.report(T3)
        self.assertEqual(r['dominant']['Trend']['event_id'], 'trend')
        self.assertIsNone(r['dominant']['Intraday']['event_id'])
        self.assertFalse(r['dominant']['Trend']['entry_allowed'])

    def test_missing_market_state_and_draft_never_tradeable(self):
        self.initial()
        self.parent('draft')
        r = self.engine.report(T3)
        self.assertTrue(all(e['qualification'] == 'WATCH' for e in r['events']))
        self.assertIsNone(r['dominant']['Intraday']['event_id'])

    def test_causal_invalidation_requires_new_facts(self):
        self.initial()
        self.engine.update_event({'update_id': 'withdrawn', 'event_id': 'test', 'known_at': T2,
            'effective_at': T2, 'source_type': 'Announcement', 'information_gain': 'High',
            'facts': '政策已撤回', 'reason': '因果依据消失', 'evidence': ['fixture:撤回公告'], 'invalidate': True})
        self.assertEqual(self.engine.snapshot('test', T3)['qualification'], 'INVALID')

    def test_ledger_immutable_and_duplicates(self):
        self.parent()
        data = {'information_id': 'i1', 'title': '原文'}
        self.assertTrue(self.engine.add_information(data))
        self.assertFalse(self.engine.add_information(data))
        with self.assertRaises(ValueError):
            self.engine.add_information({**data, 'title': '改写'})
        with self.assertRaises(sqlite3.IntegrityError):
            self.engine.db.execute('UPDATE events SET payload=?', (json.dumps({}),))

    def test_date_only_rejected(self):
        with self.assertRaises(ValueError):
            utc('2024-09-26')
        with self.assertRaises(ValueError):
            utc('2024-09-26T09:30:00')

    def test_update_information_link_and_time_validation(self):
        self.initial()
        self.engine.add_information({'information_id': 'i1', 'title': '新增原文'})
        update = {'update_id': 'linked', 'event_id': 'test', 'known_at': T2,
            'effective_at': T2, 'source_type': 'News', 'information_gain': 'Medium',
            'facts': '新增机制证据', 'reason': '原逻辑仍成立', 'evidence': ['fixture'],
            'information_ids': ['i1']}
        self.engine.update_event(update)
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM event_information').fetchone()[0], 1)
        with self.assertRaises(ValueError):
            self.engine.update_event({**update, 'update_id': 'bad-time',
                'changes': {'first_tradable_time': '2026-10-09T09:59:00+08:00'}})
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM event_updates').fetchone()[0], 2)

    def test_crowded_stops_new_qualification_without_causal_reversal(self):
        self.initial()
        self.state(pricing='Crowded')
        event = self.engine.snapshot('test', T3)
        self.assertEqual(event['qualification'], 'LATE')
        self.assertEqual(event['bias'], 'IH')
        self.assertEqual(event['causal_status'], 'Active')

    def test_legacy_migration_idempotent(self):
        folder = Path(__file__).resolve().parents[2] / 'analysis' / 'ih_im_event_research'
        first = migrate(self.engine, folder, T3)
        second = migrate(self.engine, folder, T4)
        self.assertEqual(first['totals']['information_inbox'], 36)
        self.assertEqual(first['totals']['events'], 7)
        self.assertEqual(first['totals']['event_updates'], 0)
        self.assertTrue(all(v == 0 for v in second['migration_changes'].values()))


if __name__ == '__main__':
    unittest.main()
