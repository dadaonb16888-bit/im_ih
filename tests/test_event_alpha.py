"""Event Alpha acceptance and integration tests; all evidence is fictional."""
import json
import math
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from contextlib import closing
from pathlib import Path
from urllib.request import urlopen

from event_engine.channel import CHANNEL_MAPPING, resolve_bias
from event_engine.confidence import confidence_score
from event_engine.decay import freshness
from event_engine.dominance import dominant_event
from event_engine.engine import EventEngine, utc
from workbench import make_handler

T0 = '2026-10-09T10:00:00+08:00'
T1 = '2026-10-09T10:01:00+08:00'
T2 = '2026-10-09T10:02:00+08:00'
T3 = '2026-10-09T10:03:00+08:00'
T4 = '2026-10-09T10:04:00+08:00'


class EventAlphaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'alpha.sqlite3'
        self.engine = EventEngine(self.path)

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def initial(self, eid='ai', channel='TECH_GROWTH', impact=4, confidence=0.8,
                horizon='Trend', scope='Current', bias='default'):
        self.engine.create_event({'event_id': eid, 'event_name': 'Fixture ' + eid,
            'detection_mode': 'News', 'event_time': T0, 'known_at': T0, 'scope': scope})
        changes = {'channel': channel, 'horizon': horizon, 'reviewed': True, 'directness': 2,
            'independent_cause': True, 'relative_pricing': True, 'first_tradable_time': T1,
            'invalidation': 'Fixture fact withdrawn', 'source': 'https://fixture.invalid/policy',
            'source_reliability': 'A', 'impact_score': impact, 'confidence_score': confidence}
        if bias != 'default':
            changes['bias'] = bias
            if bias is None:
                changes['reviewed'] = False
        update = {'update_id': eid + '-u1', 'event_id': eid, 'known_at': T1, 'effective_at': T1,
            'source_type': 'Policy', 'information_gain': 'High', 'facts': 'Fictional policy',
            'reason': 'Fictional expectation and exposure', 'evidence': ['fixture:policy'], 'changes': changes}
        self.engine.update_event(update)
        return update

    def state(self, sid, stamp=T2, **extra):
        return self.engine.update_state({'state_id': sid, 'event_id': 'ai', 'known_at': stamp,
            'effective_at': stamp, 'method': 'Fixture synchronized market observations',
            'evidence': ['fixture:market'], **extra})

    def test_required_tech_growth_strong_im(self):
        self.initial()
        event = self.engine.snapshot('ai', T2)
        self.assertEqual(event['bias'], 'Strong IM')
        self.assertEqual(event['affected_style'], 'IM')
        self.assertAlmostEqual(event['score'], 4 * .8 * math.exp(-2 / 1440 / 20))
        self.assertEqual(event['alpha_state'], 'Fresh')
        self.assertIsNone(event['pricing_state'])
        result = self.engine.alpha_report(T2)
        self.assertEqual(result['dominant_event'], 'ai')
        self.assertFalse(result['trade_permission'])
        self.assertFalse(result['entry_allowed'])

    def test_required_smallcap_liquidity_strong_ih(self):
        self.initial(channel='DIRECT_SMALLCAP_LIQUIDITY')
        self.assertEqual(self.engine.snapshot('ai', T2)['bias'], 'Strong IH')

    def test_required_event_decay(self):
        self.initial(horizon='Fast')
        early = self.engine.snapshot('ai', T2)['score']
        later = self.engine.snapshot('ai', '2026-10-10T10:02:00+08:00')['score']
        self.assertAlmostEqual(later / early, math.exp(-1))

    def test_required_multiple_events_ranking(self):
        self.initial('ai', impact=5)
        self.initial('risk', channel='RISK_OFF', impact=3)
        self.initial('liquidity', channel='MARKET_LIQUIDITY', impact=2)
        result = self.engine.alpha_report(T2)
        self.assertEqual(result['dominant_event'], 'ai')
        self.assertEqual([r['event_id'] for r in result['ranking']], ['ai', 'risk', 'liquidity'])
        self.assertEqual(result['by_horizon']['Trend']['dominant_event'], 'ai')

    def test_channel_overrides_and_null_not_forced(self):
        self.assertEqual(resolve_bias(['TECH_GROWTH'], 'IH'), 'IH')
        self.assertIsNone(resolve_bias(['TECH_GROWTH'], None))
        self.assertIsNone(resolve_bias(['TECH_GROWTH', 'RISK_OFF']))
        self.initial(bias='IH')
        self.assertEqual(self.engine.alpha_report(T2)['bias'], 'IH')
        self.initial('unknown', bias=None)
        self.assertIsNone(self.engine.snapshot('unknown', T2)['bias'])

    def test_all_required_channel_priors_exist(self):
        self.assertTrue({'TECH_GROWTH', 'DIRECT_SMALLCAP_LIQUIDITY', 'DIRECT_LARGECAP',
            'MARKET_LIQUIDITY', 'CREDIT_LARGECAP', 'REGULATION_QUALITY', 'RISK_APPETITE',
            'RISK_OFF', 'MARKET_STABILIZATION'} <= set(CHANNEL_MAPPING))

    def test_unknown_components_are_gaps_not_zero(self):
        self.engine.create_event({'event_id': 'draft', 'name': 'Unknown', 'detection_mode': 'News', 'known_at': T0})
        event = self.engine.snapshot('draft', T2)
        self.assertIsNone(event['score'])
        self.assertIn('impact_score', event['alpha']['score_gaps'])
        self.assertIsNone(self.engine.alpha_report(T2)['dominant_event'])

    def test_source_quality_caps_confidence(self):
        self.assertEqual(confidence_score(.9, 'D'), .3)
        self.assertIsNone(confidence_score(.9, None))
        self.assertIsNone(confidence_score(None, 'A'))

    def test_numeric_validation_rejects_nan_inf_bool_outside_range(self):
        for field, value in [('impact_score', 6), ('impact_score', -1), ('confidence_score', 1.01),
                             ('confidence_score', float('nan')), ('persistence_score', float('inf')),
                             ('source_reliability', True), ('confidence_score', True)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.engine.create_event({'event_id': 'invalid', 'name': 'Bad', 'detection_mode': 'News', 'known_at': T0, field: value})

    def test_freshness_is_timezone_aware_and_future_not_active(self):
        self.assertEqual(freshness(T0, '2026-10-09T02:00:00Z', 'Fast'), 1)
        self.assertEqual(freshness(T1, T0, 'Fast'), 0)
        for stamp in ('2026-10-09', '2026-10-09T10:00:00'):
            with self.assertRaises(ValueError):
                freshness(stamp, T2, 'Fast')
        self.initial()
        self.assertIsNone(self.engine.alpha_report(T0)['dominant_event'])
        event = self.engine.snapshot('ai', T2)
        self.assertIsNone(dominant_event([{**event, 'first_tradable_time': T4}], T2)['dominant_event'])

    def test_update_measures_changes_at_same_time_and_replays_idempotently(self):
        self.initial()
        update = {'update_id': 'ai-u2', 'event_id': 'ai', 'known_at': T2, 'effective_at': T2,
            'source_type': 'Announcement', 'information_gain': 'High', 'facts': 'Fictional order confirmed',
            'reason': 'Higher impact', 'evidence': ['fixture:order'], 'changes': {'impact_score': 5}}
        self.assertTrue(self.engine.update_event(update))
        self.assertFalse(self.engine.update_event(update))
        last = self.engine.history('ai', T3)['causal_updates'][-1]
        self.assertFalse(last['bias_change']['changed'])
        self.assertFalse(last['channel_change']['changed'])
        self.assertAlmostEqual(last['score_change'], .8 * math.exp(-2 / 1440 / 20))
        self.assertEqual(self.engine.snapshot('ai', T1)['impact_score'], 4)

    def test_update_records_bias_and_channel_rotation(self):
        self.initial()
        self.state('confirmed', acceptance='Confirmed', auto_transition=True)
        self.engine.update_event({'update_id': 'rotation', 'event_id': 'ai', 'known_at': T3, 'effective_at': T3,
            'source_type': 'Policy', 'information_gain': 'High', 'facts': 'New shock', 'reason': 'Changed transmission',
            'evidence': ['fixture:new'], 'changes': {'channel': 'RISK_OFF'}})
        history = self.engine.history('ai', T4)
        self.assertTrue(history['causal_updates'][-1]['bias_change']['changed'])
        self.assertTrue(history['causal_updates'][-1]['channel_change']['changed'])
        self.assertIsNone(history['snapshot']['acceptance'])
        self.assertEqual(history['snapshot']['bias'], 'Strong IH')

    def test_low_gain_cannot_inflate_score_or_reset_decay(self):
        self.initial(horizon='Fast')
        repeat = {'update_id': 'repeat', 'event_id': 'ai', 'known_at': T2, 'effective_at': T2,
            'source_type': 'News', 'information_gain': 'Low', 'facts': 'Repeated story', 'reason': 'No new fact', 'evidence': ['fixture:repeat']}
        before = self.engine.snapshot('ai', T3)['score']
        self.engine.update_event(repeat)
        self.assertEqual(self.engine.snapshot('ai', T3)['score'], before)
        self.assertEqual(self.engine.history('ai', T3)['causal_updates'][-1]['score_change'], 0)
        with self.assertRaises(ValueError):
            self.engine.update_event({**repeat, 'update_id': 'inflate', 'changes': {'impact_score': 5}})

    def test_automatic_four_states_with_evidence_and_no_bias_rewrite(self):
        self.initial()
        self.state('fresh', acceptance='Unconfirmed', auto_transition=True)
        self.assertEqual(self.engine.snapshot('ai', T2)['pricing_state'], 'Fresh')
        self.state('diffuse', T3, acceptance='Confirmed', auto_transition=True)
        self.assertEqual(self.engine.snapshot('ai', T3)['pricing_state'], 'Diffusing')
        self.state('crowded', T4, observations={'priced_in': True}, auto_transition=True)
        self.assertEqual(self.engine.snapshot('ai', T4)['pricing_state'], 'Crowded')
        self.state('reverse', '2026-10-09T10:05:00+08:00', observations={'impact_weakening': True}, auto_transition=True)
        latest = self.engine.snapshot('ai', '2026-10-09T10:06:00+08:00')
        self.assertEqual(latest['pricing_state'], 'Reversing')
        self.assertEqual(latest['bias'], 'Strong IM')
        self.assertFalse(self.engine.alpha_report(T4)['trade_permission'])
        self.assertEqual(latest['qualification'], 'LATE')

    def test_auto_state_needs_observation_and_respects_known_time(self):
        self.initial()
        with self.assertRaises(ValueError):
            self.state('empty', auto_transition=True)
        with self.assertRaises(ValueError):
            self.state('invent', observations={'priced_in': 'yes'}, auto_transition=True)
        with self.assertRaises(ValueError):
            self.state('mismatch', pricing_state='Fresh', acceptance='Confirmed', auto_transition=True)
        self.engine.update_state({'state_id': 'later', 'event_id': 'ai', 'known_at': T4, 'effective_at': T2,
            'acceptance': 'Confirmed', 'auto_transition': True, 'method': 'Fixture', 'evidence': ['fixture']})
        self.assertIsNone(self.engine.snapshot('ai', T3)['pricing_state'])
        self.assertEqual(self.engine.snapshot('ai', T4)['pricing_state'], 'Diffusing')

    def test_market_confirmed_event_permission_is_not_order_permission(self):
        self.initial()
        self.state('confirmation', acceptance='Confirmed', auto_transition=True)
        output = self.engine.alpha_report(T3)
        self.assertTrue(output['trade_permission'])
        self.assertFalse(output['entry_allowed'])

    def test_historical_invalidated_and_future_updates_never_lead_current_pool(self):
        self.initial('old', impact=5, scope='Historical')
        self.initial('current', impact=2)
        self.assertEqual(self.engine.alpha_report(T2, True)['dominant_event'], 'current')
        self.engine.update_event({'update_id': 'future', 'event_id': 'current', 'known_at': T4, 'effective_at': T2,
            'source_type': 'Policy', 'information_gain': 'High', 'facts': 'Future new fact', 'reason': 'Higher impact',
            'evidence': ['fixture'], 'changes': {'impact_score': 5}})
        self.assertEqual(self.engine.snapshot('current', T3)['impact_score'], 2)
        self.engine.update_event({'update_id': 'close', 'event_id': 'current', 'known_at': T3, 'effective_at': T3,
            'source_type': 'Policy', 'information_gain': 'High', 'facts': 'Withdrawal', 'reason': 'Invalidation',
            'evidence': ['fixture'], 'invalidate': True})
        self.assertIsNone(self.engine.alpha_report(T3, True)['dominant_event'])

    def test_equal_opposite_scores_return_conflict_not_arbitrary_bias(self):
        self.initial('im')
        self.initial('ih', channel='RISK_OFF')
        result = self.engine.alpha_report(T2)
        self.assertTrue(result['conflict'])
        self.assertIsNone(result['dominant_event'])
        self.assertIsNone(result['bias'])
        self.assertEqual(set(result['candidates']), {'im', 'ih'})

    def test_generated_sql_fields_state_view_and_immutability(self):
        self.initial()
        self.state('state', acceptance='Confirmed', auto_transition=True)
        update = self.engine.db.execute('SELECT information_gain,bias_change,channel_change,score_change FROM event_updates').fetchone()
        self.assertEqual(update['information_gain'], 'High')
        self.assertTrue(json.loads(update['bias_change'])['changed'])
        state = self.engine.db.execute('SELECT pricing_state,acceptance,event_score FROM event_states').fetchone()
        self.assertEqual(state['pricing_state'], 'Diffusing')
        self.assertGreater(state['event_score'], 0)
        with self.assertRaises(sqlite3.IntegrityError):
            self.engine.db.execute("UPDATE events SET payload='{}'")

    def test_schema_migration_preserves_legacy_payload_and_reopen_idempotent(self):
        path = Path(self.temp.name) / 'legacy.sqlite3'
        payload = json.dumps({'event_id': 'old', 'name': 'Legacy', 'detection_mode': 'News', 'known_at': utc(T0)})
        with closing(sqlite3.connect(path)) as legacy:
            legacy.execute('CREATE TABLE events (event_id TEXT PRIMARY KEY,known_at TEXT,recorded_at TEXT,payload TEXT)')
            legacy.execute('INSERT INTO events VALUES (?,?,?,?)', ('old', utc(T0), 'original recorded time', payload))
            legacy.commit()
        for _ in range(2):
            engine = EventEngine(path)
            try:
                old = engine.db.execute('SELECT payload,recorded_at,name FROM events').fetchone()
                self.assertEqual(old['payload'], payload)
                self.assertEqual(old['recorded_at'], 'original recorded time')
                self.assertEqual(old['name'], 'Legacy')
                self.assertIsNone(engine.snapshot('old', T3)['score'])
                self.assertEqual(engine.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            finally:
                engine.close()

    def test_state_replay_is_idempotent_after_transition(self):
        self.initial()
        data = {'state_id': 'retry', 'event_id': 'ai', 'known_at': T2, 'effective_at': T2,
            'acceptance': 'Confirmed', 'auto_transition': True, 'method': 'Fixture', 'evidence': ['fixture']}
        self.assertTrue(self.engine.update_state(data))
        self.assertFalse(self.engine.update_state(data))

    def test_acceptance_only_auto_transitions_and_crowding_needs_clearance(self):
        self.initial()
        self.state('acceptance-only', acceptance='Confirmed')
        self.assertEqual(self.engine.snapshot('ai', T2)['pricing_state'], 'Diffusing')
        self.state('priced-in', T3, observations={'priced_in': True})
        self.state('still-confirmed', T4, acceptance='Confirmed')
        self.assertEqual(self.engine.snapshot('ai', T4)['pricing_state'], 'Crowded')
        self.state('clear', '2026-10-09T10:05:00+08:00', acceptance='Confirmed', observations={'priced_in': False})
        self.assertEqual(self.engine.snapshot('ai', '2026-10-09T10:06:00+08:00')['pricing_state'], 'Diffusing')

    def test_standalone_schema_contains_required_alpha_fields(self):
        from event_engine.engine import ROOT
        with closing(sqlite3.connect(':memory:')) as database:
            database.executescript((ROOT / 'database/schema.sql').read_text(encoding='utf-8'))
            columns = {r[1] for r in database.execute('PRAGMA table_xinfo(events)')}
            self.assertTrue({'event_id', 'name', 'channel', 'horizon', 'bias', 'impact', 'confidence', 'score', 'created_time', 'status'} <= columns)

    def test_scored_update_cannot_reference_future_evidence(self):
        self.initial()
        self.engine.add_information({'information_id': 'future-info', 'title': 'Future fixture', 'observed_at': T4})
        with self.assertRaises(ValueError):
            self.engine.update_event({'update_id': 'leak', 'event_id': 'ai', 'known_at': T2, 'effective_at': T2,
                'source_type': 'News', 'information_gain': 'High', 'facts': 'Future fixture', 'reason': 'Bad timing',
                'evidence': ['fixture'], 'information_ids': ['future-info'], 'changes': {'impact_score': 5}})
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM event_updates').fetchone()[0], 1)

    def test_http_alpha_and_existing_research_still_work(self):
        self.initial()
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.path))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/api/alpha?as_of=' + utc(T2).replace('+', '%2B'), timeout=10) as response:
                result = json.load(response)
            self.assertEqual(result['dominant_event'], 'ai')
            with urlopen(base + '/api/events', timeout=10) as response:
                events = json.load(response)
            self.assertIn('event_alpha', events)
            with urlopen(base + '/api/event?id=ai', timeout=10) as response:
                self.assertEqual(json.load(response)['snapshot']['bias'], 'Strong IM')
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
