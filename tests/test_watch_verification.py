import copy
import unittest
from unittest.mock import patch

import test_news_screening as fixtures
from test_news_screening import rounds, KNOWN, LATER, OLD


class WatchVerificationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ScreeningLedgerTests();self.f.setUp()
        self.screen=self.f.screen;self.engine=self.f.engine
        p=copy.deepcopy(self.f.pack);p['screenings'][0]['input_rounds']['round3']['novelty']='Unknown'
        self.f.apply(p)
        self.engine.add_information({'information_id':'proof','title':'Synthetic checked evidence',
            'url':'https://fixture.invalid/proof','read_status':'Read','recorded_at':OLD})
        self.pack=copy.deepcopy(p);self.pack['pack_id']='follow';self.pack['screenings'][0]['screening_id']='follow'
        self.pack['screenings'][0]['follow_up']={'prior_screening_id':'S','group_id':'topic','priority':'Normal',
            'question':'Which fact is missing?', 'evidence_source_ids':['proof'], 'finding':'Synthetic facts remain incomplete',
            'next_trigger':'New official evidence', 'outcome':'WaitEvidence'}

    def tearDown(self): self.f.tearDown()

    def apply(self,p=None):
        with patch('event_engine.news_screening.now',return_value=LATER):return self.screen.apply_pack(p or self.pack)

    def test_waiting_note_append_replay_and_historical_visibility(self):
        self.assertTrue(self.apply()['inserted']);self.assertFalse(self.apply()['inserted'])
        self.assertNotIn('follow_up',self.screen.latest(KNOWN)['I'])
        saved=self.screen.latest(LATER)['I']
        self.assertEqual(saved['follow_up']['question'],'Which fact is missing?')
        self.assertFalse(saved['deep_review_allowed']);self.assertFalse(saved['entry_allowed'])

    def test_stale_prior_or_non_watch_rejected_without_run(self):
        p=copy.deepcopy(self.pack);p['screenings'][0]['follow_up']['prior_screening_id']='wrong'
        with self.assertRaisesRegex(ValueError,'已变化'):self.apply(p)
        self.assertEqual(self.engine.db.execute('SELECT count(*) FROM news_screening_runs').fetchone()[0],1)
        self.apply()
        p=copy.deepcopy(self.pack);p['pack_id']='stale';p['screenings'][0]['screening_id']='stale'
        with self.assertRaisesRegex(ValueError,'已变化'):self.apply(p)

    def test_missing_future_or_unlabelled_evidence_rejected(self):
        for iid,extra in [('missing',None),('future',{'recorded_at':LATER}),('unlabelled',{'recorded_at':OLD})]:
            if extra is not None:self.engine.add_information({'information_id':iid,'title':'Synthetic', 'url':'https://fixture.invalid/'+iid,**extra})
            p=copy.deepcopy(self.pack);p['screenings'][0]['follow_up']['evidence_source_ids']=[iid]
            if iid=='future':
                with patch('event_engine.news_screening.now',return_value=KNOWN):
                    with self.assertRaises(ValueError):self.screen.apply_pack(p)
            else:
                with self.assertRaises(ValueError):self.apply(p)

    def test_archive_unknown_or_wrong_decision_is_rejected(self):
        p=copy.deepcopy(self.pack);p['screenings'][0]['follow_up']['outcome']='Archive'
        with self.assertRaisesRegex(ValueError,'Background'):self.apply(p)
        p['screenings'][0]['input_rounds']={'round1':{**rounds()['round1'],'time_relevance':'Background'}}
        p['screenings'][0]['follow_up']['evidence_source_ids']=[]
        with self.assertRaisesRegex(ValueError,'可读取证据'):self.apply(p)
        p['screenings'][0]['follow_up']['evidence_source_ids']=['proof']
        self.apply(p);self.assertEqual(self.screen.latest(LATER)['I']['decision'],'Background')

    def test_waiting_can_stop_without_repeated_fetch_but_rescreen_needs_readable_source(self):
        p=copy.deepcopy(self.pack);p['screenings'][0]['follow_up']['evidence_source_ids']=[]
        self.assertTrue(self.apply(p)['inserted'])
        p=copy.deepcopy(self.pack);p['pack_id']='again';p['screenings'][0]['screening_id']='again'
        p['screenings'][0]['follow_up'].update(prior_screening_id='follow',outcome='Rescreen',evidence_source_ids=[])
        with self.assertRaisesRegex(ValueError,'可读取证据'):self.apply(p)

    def test_maximum_sources_short_text_and_unknown_fields(self):
        for mutation in ('long','extra','many'):
            p=copy.deepcopy(self.pack);note=p['screenings'][0]['follow_up']
            if mutation=='long':note['finding']='x'*241
            if mutation=='extra':note['bias']='IH'
            if mutation=='many':note['evidence_source_ids']=['a','b','c','d']
            with self.assertRaises(ValueError):self.apply(p)

    def test_duplicate_target_and_shared_topic_budget_roll_back(self):
        p=copy.deepcopy(self.pack);p['screenings'].append(copy.deepcopy(p['screenings'][0]));p['screenings'][1]['screening_id']='duplicate'
        with self.assertRaisesRegex(ValueError,'重复筛选'):self.apply(p)
        from event_engine.watch_verification import validate_group_budgets
        records=[{'follow_up':{'group_id':'g','evidence_source_ids':['a','b']}},
                 {'follow_up':{'group_id':'g','evidence_source_ids':['c','d']}}]
        with self.assertRaisesRegex(ValueError,'共享'):validate_group_budgets(records)
        records=[{'follow_up':{'group_id':str(i),'evidence_source_ids':[str(i)]}} for i in range(13)]
        with self.assertRaisesRegex(ValueError,'12'):validate_group_budgets(records)
        self.assertEqual(self.engine.db.execute('SELECT count(*) FROM news_screening_runs').fetchone()[0],1)

    def test_follow_up_does_not_bypass_original_source_read_gate(self):
        self.engine.add_information({'information_id':'blocked','title':'Synthetic blocked','read_status':'Unavailable'})
        p=copy.deepcopy(self.pack);p['pack_id']='blocked-watch';p['screenings'][0].update(information_id='blocked',screening_id='blocked-watch');p['screenings'][0].pop('follow_up')
        self.apply(p)
        p=copy.deepcopy(p);p['pack_id']='bad-deep';p['screenings'][0]['screening_id']='bad-deep';p['screenings'][0]['input_rounds']=rounds()
        p['screenings'][0]['follow_up']={**self.pack['screenings'][0]['follow_up'],'prior_screening_id':'blocked-watch','outcome':'Rescreen'}
        with self.assertRaisesRegex(ValueError,'未取得原文'):self.apply(p)
