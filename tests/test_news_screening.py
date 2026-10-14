import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from event_engine.engine import EventEngine, utc
from event_engine.news_screening import NewsScreening, evaluate, VERSION

KNOWN = utc('2026-10-14T09:00:00+08:00')
OLD = utc('2026-10-13T10:00:00+08:00')
LATER = utc('2026-10-14T09:01:00+08:00')


def rounds():
    return {'round1': {'duplicate': False, 'time_relevance': 'Current', 'source_quality': 'A', 'reason': 'Synthetic reliable publication'},
            'round2': {'scope': 'Style', 'potential': 'Medium', 'spillover': 'Clear', 'reason': 'Synthetic style impact'},
            'round3': {'novelty': 'New', 'transmission': 'Clear', 'fact_support': 'Supported', 'reason': 'Synthetic new mechanism'}}


class RoundTests(unittest.TestCase):
    def test_three_rounds_allow_research_but_never_bias(self):
        result = evaluate(rounds())
        self.assertEqual(result['decision'], 'DeepReview')
        self.assertEqual(len(result['rounds']), 3)
        self.assertTrue(result['deep_review_allowed'])
        self.assertIsNone(result['bias'])
        self.assertFalse(result['trade_permission'])
        self.assertFalse(result['entry_allowed'])

    def test_first_stop_needs_no_later_analysis_and_rejects_extra_work(self):
        r = rounds()['round1']; r['duplicate'] = True
        result = evaluate({'round1': r})
        self.assertEqual(result['decision'], 'Background')
        self.assertEqual(len(result['rounds']), 1)
        later = rounds(); later['round1'] = r
        with self.assertRaises(ValueError): evaluate(later)

    def test_low_impact_stops_second_round(self):
        r = rounds(); r.pop('round3'); r['round2']['potential'] = 'Low'
        self.assertEqual(evaluate(r)['decision'], 'Background')

    def test_important_company_spillover_can_pass_but_local_minor_stops(self):
        r = rounds(); r['round2']['scope'] = 'Company'
        self.assertEqual(evaluate(r)['decision'], 'DeepReview')
        r['round2']['spillover'] = 'None'; r.pop('round3')
        self.assertEqual(evaluate(r)['decision'], 'Background')

    def test_unknown_is_watch_not_zero_impact(self):
        for field, value in [('novelty', 'Unknown'), ('transmission', 'Possible'), ('fact_support', 'Unverified')]:
            r = rounds();r['round3'][field] = value
            self.assertEqual(evaluate(r)['decision'], 'Watch')
        r = rounds();r['round1']['time_relevance'] = 'Unknown'
        self.assertEqual(evaluate(r)['decision'], 'Watch')
        self.assertEqual(evaluate({'round1': rounds()['round1']})['decision'], 'Watch')

    def test_future_schedule_and_rumour_never_go_directly_to_deep_review(self):
        for field,value in [('source_quality','D'),('time_relevance','Upcoming')]:
            r = rounds()['round1'];r[field] = value
            self.assertEqual(evaluate({'round1': r})['decision'], 'Watch')

    def test_reaffirmation_and_no_transmission_stop_third_round(self):
        for field,value in [('novelty','Repeat'),('transmission','None')]:
            r = rounds();r['round3'][field] = value
            self.assertEqual(evaluate(r)['decision'], 'Background')

    def test_long_reasons_and_unknown_fields_are_rejected(self):
        r=rounds();r['round1']['reason']='x'*241
        with self.assertRaises(ValueError): evaluate(r)
        r=rounds();r['round2']['bias']='IM'
        with self.assertRaises(ValueError): evaluate(r)


class ScreeningLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.engine=EventEngine(Path(self.temp.name)/'screen.sqlite3')
        self.screen=NewsScreening(self.engine)
        self.engine.add_information({'information_id':'I','title':'Synthetic news','observed_at':OLD,'recorded_at':OLD})
        self.pack={'pack_id':'P','actor':'Codex','version':VERSION,'generated_at':OLD,
                   'screenings':[{'screening_id':'S','information_id':'I','summary':'Short synthetic summary','input_rounds':rounds()}]}

    def tearDown(self): self.engine.close();self.temp.cleanup()

    def apply(self,pack=None):
        with patch('event_engine.news_screening.now',return_value=KNOWN):return self.screen.apply_pack(pack or self.pack)

    def test_replay_revisions_history_and_old_time_preserved(self):
        self.assertTrue(self.apply()['inserted']);self.assertFalse(self.apply()['inserted'])
        changed=copy.deepcopy(self.pack);changed['screenings'][0]['summary']='Changed'
        with self.assertRaises(ValueError):self.apply(changed)
        later=copy.deepcopy(self.pack);later['pack_id']='P2';later['screenings'][0]['screening_id']='S2'
        r=rounds();r['round3']['novelty']='Unknown';later['screenings'][0]['input_rounds']=r
        with patch('event_engine.news_screening.now',return_value=LATER):self.screen.apply_pack(later)
        self.assertEqual(self.screen.latest(KNOWN)['I']['decision'],'DeepReview')
        self.assertEqual(self.screen.latest(LATER)['I']['decision'],'Watch')
        self.assertEqual(len(self.screen.history('I',LATER)),2)
        self.assertFalse(self.screen.active(OLD));self.assertTrue(self.screen.active(KNOWN))
        self.assertIsNone(self.screen.report(OLD)['information'][0]['screening'])
        with self.assertRaises(sqlite3.IntegrityError):self.engine.db.execute("DELETE FROM information_screenings")

    def test_invalid_second_record_rolls_back_whole_run(self):
        bad=copy.deepcopy(self.pack);bad['screenings'].append({'screening_id':'BAD','information_id':'missing','summary':'Bad','input_rounds':rounds()})
        with self.assertRaises(ValueError):self.apply(bad)
        self.assertEqual(self.engine.db.execute('SELECT count(*) FROM news_screening_runs').fetchone()[0],0)
        self.assertEqual(self.screen.latest(KNOWN),{})

    def test_future_source_and_future_pack_rejected(self):
        self.engine.add_information({'information_id':'future','title':'future','observed_at':LATER})
        bad=copy.deepcopy(self.pack);bad['screenings'][0]['information_id']='future'
        with self.assertRaises(ValueError):self.apply(bad)
        bad=copy.deepcopy(self.pack);bad['generated_at']=LATER
        with self.assertRaises(ValueError):self.apply(bad)

    def test_current_research_gate_starts_after_policy_old_packs_replay(self):
        import test_ai_research as fixture
        helper=fixture.AIResearchTests();helper.setUp()
        try:
            original=helper.pack(helper.assessment())
            helper.research.apply_pack(original)
            p=copy.deepcopy(self.pack);p['screenings'][0].update(information_id='fixture-news',input_rounds={'round1':{**rounds()['round1'],'duplicate':True}})
            gate=NewsScreening(helper.engine)
            with patch('event_engine.news_screening.now',return_value=fixture.KNOWN):gate.apply_pack(p)
            self.assertFalse(helper.research.apply_pack(original)['inserted'])
            new=helper.pack(helper.assessment('new'),pack_id='new')
            with self.assertRaisesRegex(ValueError,'三轮初筛'):helper.research.apply_pack(new)
            helper.engine.add_information(helper.make_source('unrelated'))
            unrelated=copy.deepcopy(p);unrelated['pack_id']='unrelated';unrelated['screenings'][0].update(screening_id='unrelated',information_id='unrelated',input_rounds=rounds())
            with patch('event_engine.news_screening.now',return_value=fixture.KNOWN):gate.apply_pack(unrelated)
            wrong=helper.pack(helper.assessment('wrong',source_ids=['unrelated']),pack_id='wrong')
            with self.assertRaisesRegex(ValueError,'与事件关联'):helper.research.apply_pack(wrong)
            p['pack_id']='allow';p['screenings'][0].update(screening_id='allow',input_rounds=rounds())
            with patch('event_engine.news_screening.now',return_value=fixture.KNOWN):gate.apply_pack(p)
            self.assertTrue(helper.research.apply_pack(new)['inserted'])
        finally:helper.tearDown()

    def test_unavailable_source_cannot_claim_short_supported_evidence(self):
        self.engine.add_information({'information_id':'blocked','title':'blocked','read_status':'Unavailable'})
        bad=copy.deepcopy(self.pack);bad['screenings'][0]['information_id']='blocked'
        with self.assertRaisesRegex(ValueError,'未取得原文'):self.apply(bad)
