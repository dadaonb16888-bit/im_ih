"""AI research integration checks use invented evidence in temporary databases."""
import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from event_engine.ai_research import AIResearch, METHOD
from event_engine.engine import EventEngine, utc
from workbench import make_handler


KNOWN = utc('2026-10-13T12:00:00+08:00')
OLD = utc('2026-10-10T09:00:00+08:00')
BEFORE = utc('2026-10-13T11:59:59+08:00')
FUTURE = utc('2026-10-13T12:01:00+08:00')


class AIResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = EventEngine(Path(self.temp.name) / 'ai-test.sqlite3')
        self.research = AIResearch(self.engine)
        self.clock = patch('event_engine.ai_research.now', return_value=KNOWN)
        self.clock.start()
        self.engine.create_event({'event_id': 'fixture-event', 'name': '虚构研究事件',
            'detection_mode': 'News', 'category': 'MONETARY', 'known_at': OLD})
        self.source = self.make_source('fixture-news')
        self.engine.add_information(self.source)

    def tearDown(self):
        self.clock.stop()
        self.engine.close()
        self.temp.cleanup()

    @staticmethod
    def make_source(iid):
        return {'information_id': iid, 'title': '仅用于测试的虚构资料 ' + iid,
            'url': 'https://fixture.invalid/' + iid, 'published_at': '2026-10-10',
            'observed_at': OLD, 'recorded_at': OLD, 'fact': '虚构资料的原文摘要'}

    def assessment(self, aid='fixture-assessment', source_ids=None, additional=None,
                   event_id='fixture-event'):
        ids = source_ids or ['fixture-news']
        context = self.research.context(event_id, ids, additional_sources=additional)
        sources = {s['information_id']: s for s in additional or []}
        checks = []
        for iid in ids:
            source = sources.get(iid) or self.research._source(iid)
            checks.append({'information_id': iid, 'url': source['url'], 'status': 'Read',
                'checked_at': BEFORE, 'fact_summary': '测试夹具已提供原文摘要',
                'capture_mode': 'DirectWebText'})
        return {'assessment_id': aid, 'event_id': event_id, 'source_ids': ids,
            'source_checks': checks, 'facts': [{'statement': '资料声明一项虚构政策变化',
                'source_ids': [ids[0]]}], 'information_gain': None, 'surprise': None,
            'bias': 'IM', 'decision': 'Directional', 'confidence': 'Medium',
            'channels': ['MARKET_LIQUIDITY'], 'horizon': 'Swing',
            'conflicts': [], 'gaps': ['公开时间只有日期精度'],
            'research_mode': 'CurrentReview', 'input_digest': context['input_digest'],
            'expected_last_update_id': context['expected_last_update_id'],
            'baseline_source_ids': [], 'exposure_source_ids': [], 'directness': 2,
            'independent_cause': True, 'relative_pricing': True, 'event_time': None,
            'first_tradable_time': None, 'increment_reason': '基线不足，增量暂不能确定',
            'expectation_baseline': '未取得可核查的事前预期',
            'transmission': '虚构政策影响资金成本，研究假设成长风格相对受益',
            'im_case': 'IM相关风格存在相对受益的研究路径',
            'ih_case': '金融权重受益是需要保留的相反解释',
            'exposure_evidence': '成分暴露证据尚未核实',
            'pre_move': '未接入行情，不推断提前定价',
            'invalidation': '政策机制被新的事实否定',
            'next_action': '补齐精确时间、事前基线及成分暴露'}

    @staticmethod
    def pack(assessment, pack_id='fixture-pack', sources=None):
        return {'pack_id': pack_id, 'actor': 'Codex', 'method_version': METHOD,
            'generated_at': OLD, 'sources': sources or [],
            'assessments': assessment if isinstance(assessment, list) else [assessment]}

    def count(self, table):
        return self.engine.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

    def formal_assessment(self):
        for iid in ('fixture-baseline', 'fixture-exposure'):
            self.engine.add_information(self.make_source(iid))
        assessment = self.assessment(source_ids=['fixture-news', 'fixture-baseline', 'fixture-exposure'])
        assessment.update({'promote_causal': True, 'information_gain': 'Medium',
            'gaps': [], 'baseline_source_ids': ['fixture-baseline'],
            'exposure_source_ids': ['fixture-exposure'], 'event_time': OLD,
            'first_tradable_time': utc('2026-10-10T09:30:00+08:00'),
            'increment_reason': '虚构基线对照显示机制变化',
            'exposure_evidence': '虚构成分暴露表显示差异，引用独立证据'})
        return assessment

    def test_real_known_at_does_not_backdate_or_invent_date_only_timestamp(self):
        self.research.apply_pack(self.pack(self.assessment()))
        saved = self.research.list_assessments('fixture-event')[0]
        self.assertEqual(saved['known_at'], KNOWN)
        self.assertIsNone(saved['event_time'])
        self.assertIsNone(saved['first_tradable_time'])
        self.assertEqual(self.research._source('fixture-news')['published_at'], '2026-10-10')
        self.assertEqual(self.research.list_assessments('fixture-event', as_of=BEFORE), [])
        self.assertEqual(saved['actor'], 'Codex')
        self.assertEqual(saved['method_version'], METHOD)
        self.assertEqual(self.count('event_updates'), 0)

    def test_unknown_information_gain_can_save_research_without_formal_bias(self):
        self.research.apply_pack(self.pack(self.assessment()))
        saved = self.research.list_assessments('fixture-event')[0]
        self.assertIsNone(saved['information_gain'])
        self.assertEqual(saved['bias'], 'IM')
        self.assertFalse(saved['promote_causal'])
        self.assertIsNone(saved['causal_projection'])
        formal = self.engine.snapshot('fixture-event', KNOWN)
        self.assertIsNone(formal['bias'])
        self.assertIsNone(formal['D'])
        self.assertFalse(formal['reviewed'])
        self.assertEqual(formal['qualification'], 'WATCH')

    def test_null_and_neutral_retain_different_conclusions(self):
        unknown = self.assessment('unknown')
        unknown.update({'bias': None, 'decision': 'InsufficientEvidence'})
        neutral = self.assessment('neutral')
        neutral.update({'bias': 'Neutral', 'decision': 'Neutral'})
        self.research.apply_pack(self.pack([unknown, neutral]))
        records = self.research.list_assessments('fixture-event')
        self.assertEqual([(a['decision'], a['bias']) for a in records],
                         [('InsufficientEvidence', None), ('Neutral', 'Neutral')])

    def test_inconsistent_direction_or_unknown_without_gaps_is_rejected(self):
        for changes in ({'bias': 'Neutral'}, {'bias': None},
                        {'decision': 'InsufficientEvidence', 'bias': None, 'gaps': []}):
            with self.subTest(changes=changes):
                a = self.assessment()
                a.update(changes)
                with self.assertRaises(ValueError):
                    self.research.apply_pack(self.pack(a))
                self.assertEqual(self.count('ai_research_runs'), 0)

    def test_missing_or_invisible_parent_is_rejected_cleanly(self):
        self.engine.create_event({'event_id': 'future-parent', 'name': '未来不可见事件',
            'detection_mode': 'News', 'known_at': FUTURE})
        for eid in ('missing-parent', 'future-parent'):
            with self.subTest(event=eid):
                with self.assertRaises(ValueError):
                    self.research.context(eid, ['fixture-news'])
                a = self.assessment()
                a['event_id'] = eid
                with self.assertRaises(ValueError):
                    self.research.apply_pack(self.pack(a))
                self.assertEqual(self.count('ai_research_runs'), 0)

    def test_missing_source_is_rejected(self):
        with self.assertRaises(ValueError):
            self.research.context('fixture-event', ['missing-source'])

    def test_sources_not_yet_recorded_or_observed_are_invisible(self):
        for time_field in ('recorded_at', 'observed_at', 'known_at'):
            with self.subTest(time_field=time_field):
                source = self.make_source('future-' + time_field)
                source[time_field] = FUTURE
                self.engine.add_information(source)
                with self.assertRaises(ValueError):
                    self.research.context('fixture-event', [source['information_id']])

    def test_stale_digest_is_rejected_without_writing(self):
        a = self.assessment()
        a['input_digest'] = '0' * 64
        with self.assertRaises(ValueError):
            self.research.apply_pack(self.pack(a))
        self.assertEqual(self.count('ai_research_runs'), 0)
        self.assertEqual(self.count('ai_assessments'), 0)

    def test_changed_event_update_requires_new_research(self):
        a = self.assessment()
        self.engine.update_event({'update_id': 'new-causal-fact', 'event_id': 'fixture-event',
            'known_at': BEFORE, 'effective_at': BEFORE, 'source_type': 'Policy',
            'information_gain': 'Medium', 'facts': '虚构新增事实', 'reason': '机制改变',
            'evidence': ['https://fixture.invalid/new'], 'changes': {}})
        with self.assertRaises(ValueError):
            self.research.apply_pack(self.pack(a))
        self.assertEqual(self.count('ai_research_runs'), 0)

    def test_same_pack_is_idempotent_and_changed_content_is_rejected(self):
        package = self.pack(self.assessment())
        self.assertTrue(self.research.apply_pack(package)['inserted'])
        saved = self.research.list_assessments('fixture-event')
        with patch('event_engine.ai_research.now', return_value=FUTURE):
            self.assertFalse(self.research.apply_pack(copy.deepcopy(package))['inserted'])
        self.assertEqual(self.research.list_assessments('fixture-event'), saved)
        self.assertEqual((self.count('ai_research_runs'), self.count('ai_assessments')), (1, 1))
        changed = copy.deepcopy(package)
        changed['assessments'][0]['transmission'] = '修改过的推断'
        with self.assertRaises(ValueError):
            self.research.apply_pack(changed)
        self.assertEqual(self.research.list_assessments('fixture-event'), saved)

    def test_invalid_second_assessment_rolls_back_sources_run_and_first_assessment(self):
        source = self.make_source('new-source')
        good = self.assessment('first', ['new-source'], additional=[source])
        bad = self.assessment('second')
        bad['input_digest'] = 'bad-input'
        before = {t: self.count(t) for t in ('information_inbox', 'event_information',
                                           'ai_research_runs', 'ai_assessments', 'event_updates')}
        with self.assertRaises(ValueError):
            self.research.apply_pack(self.pack([good, bad], sources=[source]))
        self.assertEqual({t: self.count(t) for t in before}, before)

    def test_later_failure_also_rolls_back_formal_causal_projection(self):
        good = self.formal_assessment()
        bad = self.assessment('second')
        bad['input_digest'] = 'deliberately-invalid'
        before = {t: self.count(t) for t in ('event_information', 'event_updates',
                                           'ai_research_runs', 'ai_assessments', 'state_updates')}
        with self.assertRaises(ValueError):
            self.research.apply_pack(self.pack([good, bad]))
        self.assertEqual({t: self.count(t) for t in before}, before)
        self.assertIsNone(self.engine.snapshot('fixture-event', KNOWN)['bias'])

    def test_ai_tables_are_append_only(self):
        self.research.apply_pack(self.pack(self.assessment()))
        for table, key, value in (('ai_research_runs', 'pack_id', 'fixture-pack'),
                                  ('ai_assessments', 'assessment_id', 'fixture-assessment')):
            for action in ('UPDATE', 'DELETE'):
                with self.subTest(table=table, action=action):
                    sql = ('UPDATE ' + table + ' SET payload=payload WHERE ' + key + '=?'
                           if action == 'UPDATE' else 'DELETE FROM ' + table + ' WHERE ' + key + '=?')
                    with self.assertRaises(sqlite3.IntegrityError):
                        with self.engine.db:
                            self.engine.db.execute(sql, (value,))
        self.assertEqual((self.count('ai_research_runs'), self.count('ai_assessments')), (1, 1))

    def test_unread_source_cannot_be_evidence_fact(self):
        a = self.assessment()
        a['source_checks'][0]['status'] = 'Unavailable'
        with self.assertRaises(ValueError):
            self.research.apply_pack(self.pack(a))
        self.assertEqual(self.count('ai_assessments'), 0)

    def test_direction_requires_at_least_one_read_source(self):
        a = self.assessment()
        a['source_checks'][0]['status'] = 'Partial'
        with self.assertRaises(ValueError):
            self.research.apply_pack(self.pack(a))

    def test_unread_sources_can_only_support_explicitly_insufficient_record(self):
        a = self.assessment()
        a.update({'decision': 'InsufficientEvidence', 'bias': None, 'facts': []})
        a['source_checks'][0]['status'] = 'Unavailable'
        self.research.apply_pack(self.pack(a))
        saved = self.research.list_assessments('fixture-event')[0]
        self.assertIsNone(saved['bias'])
        self.assertEqual(saved['decision'], 'InsufficientEvidence')
        self.assertEqual(self.count('event_updates'), 0)

    def test_unreferenced_fact_source_and_future_read_time_are_rejected(self):
        for change in ('unknown-fact', 'future-read'):
            with self.subTest(change=change):
                a = self.assessment()
                if change == 'unknown-fact':
                    a['facts'][0]['source_ids'] = ['not-in-assessment']
                else:
                    a['source_checks'][0]['checked_at'] = FUTURE
                with self.assertRaises(ValueError):
                    self.research.apply_pack(self.pack(a))

    def test_read_address_must_match_original_source(self):
        a = self.assessment()
        a['source_checks'][0]['url'] = 'https://other-fixture.invalid/unrelated'
        with self.assertRaises(ValueError):
            self.research.apply_pack(self.pack(a))

    def test_search_snippets_and_supplied_text_cannot_claim_original_read(self):
        for capture_mode in ('OfficialSearchIndex', 'UserProvided', 'Unavailable'):
            with self.subTest(capture_mode=capture_mode):
                a = self.assessment()
                a['source_checks'][0]['capture_mode'] = capture_mode
                with self.assertRaises(ValueError):
                    self.research.apply_pack(self.pack(a))
                self.assertEqual(self.count('ai_assessments'), 0)

    def test_research_does_not_change_existing_market_state(self):
        self.engine.update_state({'state_id': 'fixture-market', 'event_id': 'fixture-event',
            'effective_at': OLD, 'known_at': OLD, 'acceptance': 'Rejected',
            'pricing_state': 'Reversing', 'method': '虚构同步行情夹具',
            'evidence': ['fixture:market-data']})
        before = self.engine.history('fixture-event', KNOWN)['market_states']
        self.research.apply_pack(self.pack(self.assessment()))
        after = self.engine.history('fixture-event', KNOWN)['market_states']
        self.assertEqual(after, before)
        self.assertEqual(self.count('state_updates'), 1)
        self.assertIsNone(self.engine.snapshot('fixture-event', KNOWN)['bias'])

    def test_formal_projection_rejects_missing_research_requirements(self):
        a = self.formal_assessment()
        cases = {'low-confidence': {'confidence': 'Low'},
                 'unknown-gain': {'information_gain': None},
                 'low-gain': {'information_gain': 'Low'},
                 'no-baseline': {'baseline_source_ids': []},
                 'no-exposure': {'exposure_source_ids': []},
                 'missing-public-time': {'event_time': None},
                 'missing-tradable-time': {'first_tradable_time': None},
                 'date-only-public-time': {'event_time': '2026-10-10'},
                 'remaining-gaps': {'gaps': ['未核实来源缺口']}}
        for name, changes in cases.items():
            with self.subTest(case=name):
                invalid = copy.deepcopy(a)
                invalid.update(changes)
                with self.assertRaises(ValueError):
                    self.research.apply_pack(self.pack(invalid))
                self.assertEqual(self.count('event_updates'), 0)
                self.assertEqual(self.count('ai_assessments'), 0)
                self.assertEqual(self.count('ai_research_runs'), 0)

    def test_formal_projection_rejects_partial_source(self):
        a = self.formal_assessment()
        a['source_checks'][1]['status'] = 'Partial'
        with self.assertRaises(ValueError):
            self.research.apply_pack(self.pack(a))
        self.assertEqual(self.count('event_updates'), 0)

    def test_valid_formal_projection_does_not_invent_market_confirmation(self):
        a = self.formal_assessment()
        self.research.apply_pack(self.pack(a))
        saved = self.research.list_assessments('fixture-event')[0]
        self.assertEqual(saved['causal_projection'], 'AI-U-fixture-assessment')
        snapshot = self.engine.snapshot('fixture-event', KNOWN)
        self.assertEqual(snapshot['bias'], 'IM')
        self.assertTrue(snapshot['reviewed'])
        self.assertEqual(snapshot['D'], 1)
        self.assertIsNone(snapshot['acceptance'])
        self.assertIsNone(snapshot['pricing_state'])
        self.assertEqual(snapshot['qualification'], 'WATCH')
        self.assertFalse(snapshot['entry_allowed'])
        self.assertEqual(self.count('state_updates'), 0)
        update = self.engine.history('fixture-event', KNOWN)['causal_updates'][0]
        self.assertEqual((update['known_at'], update['effective_at']), (KNOWN, KNOWN))

    def test_historical_mode_cannot_be_mislabeled_current(self):
        self.engine.create_event({'event_id': 'history', 'name': '虚构历史事件',
            'detection_mode': 'News', 'scope': 'Historical', 'known_at': OLD})
        a = self.assessment(event_id='history')
        with self.assertRaises(ValueError):
            self.research.apply_pack(self.pack(a))
        a['research_mode'] = 'HistoricalReview'
        self.research.apply_pack(self.pack(a))
        self.assertEqual(self.research.list_assessments('history')[0]['research_mode'], 'HistoricalReview')

    def test_causal_or_market_override_fields_are_not_accepted_as_ai_labels(self):
        for key, value in (('reviewed', True), ('verified', True),
                           ('acceptance', 'Confirmed'), ('pricing_state', 'Fresh')):
            with self.subTest(field=key):
                a = self.assessment()
                a[key] = value
                with self.assertRaises(ValueError):
                    self.research.apply_pack(self.pack(a))
                self.assertEqual(self.count('ai_research_runs'), 0)

    def test_http_exposes_ai_results_and_never_imports_forged_actor_labels(self):
        self.research.apply_pack(self.pack(self.assessment()))
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.engine.path))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/api/events', timeout=10) as response:
                report = json.loads(response.read())
            self.assertEqual(report['counts']['ai_assessments'], 1)
            self.assertEqual(report['events'][0]['ai_assessment_count'], 1)
            self.assertIsNone(report['events'][0]['bias'])
            with urlopen(base + '/api/event?id=fixture-event', timeout=10) as response:
                history = json.loads(response.read())
            self.assertEqual(history['ai_assessments'][0]['bias'], 'IM')
            self.assertEqual(history['market_states'], [])
            forged = Request(base + '/api/ai-assessment', data=b'{"actor":"Codex","reviewed":true}',
                headers={'Content-Type': 'application/json', 'X-Event-Workbench': '1'})
            with self.assertRaises(HTTPError) as error:
                urlopen(forged, timeout=10)
            self.assertEqual(error.exception.code, 404)
            self.assertEqual(self.count('ai_assessments'), 1)
        finally:
            server.shutdown()
            worker.join()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
