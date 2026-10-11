import csv
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from event_engine.engine import EventEngine, ROOT
from event_engine.csv_io import import_research, export_research
from workbench import make_handler

T0 = '2026-10-11T10:00:00+08:00'
T1 = '2026-10-11T11:00:00+08:00'


class Phase1Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.engine = EventEngine(self.path / 'events.sqlite3')

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def test_import_preserves_unverified_labels_without_signals(self):
        result = import_research(self.engine, ROOT / 'data' / 'events', T0)
        self.assertEqual(result['new_parents'], 11)
        self.assertEqual(result['new_research_notes'], 16)
        historical = self.engine.report(T1, include_historical=True)
        self.assertTrue(all(e['qualification'] == 'WATCH' and e['bias'] is None for e in historical['events']))
        self.assertEqual(self.engine.report(T1)['events'], [])
        history = self.engine.history('202409_POLICY_PIVOT', T1)
        parent = next(n for n in history['research_notes'] if n['kind'] == 'Parent')
        self.assertEqual(parent['claim']['source_initial_bias'], 'IM')
        self.assertEqual(parent['claim']['event_time_claim']['precision'], 'date')
        self.assertEqual(history['causal_updates'], [])
        self.assertEqual(history['market_states'], [])
        self.assertEqual(self.engine.history('202504_TARIFF', T1)['research_notes'][1]['kind'], 'EventUpdate')

    def test_repeat_import_and_export_roundtrip(self):
        import_research(self.engine, ROOT / 'data' / 'events', T0)
        second = import_research(self.engine, ROOT / 'data' / 'events', T1)
        self.assertEqual((second['new_parents'], second['new_research_notes']), (0, 0))
        output = self.path / 'export'
        self.assertEqual(export_research(self.engine, output), {'Parent':11,'EventUpdate':3,'MarketState':2})
        again = import_research(self.engine, output, T1)
        self.assertEqual((again['new_parents'], again['new_research_notes']), (0, 0))

    def test_unknown_parent_rolls_back_entire_batch(self):
        source = self.path / 'csv'
        shutil.copytree(ROOT / 'data' / 'events', source)
        with (source / 'event_updates.csv').open('a', encoding='utf-8') as file:
            file.write('UNKNOWN,2024-09-26,Policy,High,不存在的Parent,IM,\n')
        with self.assertRaises(ValueError):
            import_research(self.engine, source, T0)
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM research_notes').fetchone()[0], 0)

    def test_research_time_query_prevents_early_visibility(self):
        import_research(self.engine, ROOT / 'data' / 'events', T1)
        self.assertEqual(self.engine.report(T0, include_historical=True)['events'], [])

    def test_invalid_csv_enum_and_multiline_rejected(self):
        source = self.path / 'csv'
        shutil.copytree(ROOT / 'data' / 'events', source)
        path = source / 'events.csv'
        path.write_text(path.read_text(encoding='utf-8').replace('Strong_IM', 'Strong_BAD'), encoding='utf-8')
        with self.assertRaises(ValueError):
            import_research(self.engine, source, T0)
        path.write_text('event_id,event_name,event_type\nx,\nname,News\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            import_research(self.engine, source, T0)

    def test_historical_event_never_becomes_current_dominant(self):
        import_research(self.engine, ROOT / 'data' / 'events', T0)
        eid = '202409_POLICY_PIVOT'
        self.engine.update_event({'update_id':'fixture-u','event_id':eid,'known_at':T0,'effective_at':T0,
            'source_type':'Policy','information_gain':'High','facts':'fixture','reason':'fixture',
            'evidence':['fixture'], 'changes':{'reviewed':True,'bias':'IH','horizon':'Swing',
            'channels':['MARKET_LIQUIDITY'],'directness':3,'independent_cause':True,'relative_pricing':True,
            'event_time':T0,'first_tradable_time':T0,'invalidation':'fixture'}})
        self.engine.update_state({'state_id':'fixture-s','event_id':eid,'known_at':T1,'effective_at':T1,
            'pricing_state':'Diffusing','acceptance':'Confirmed','method':'fixture','evidence':['fixture']})
        r = self.engine.report(T1, include_historical=True)
        self.assertEqual(next(e for e in r['events'] if e['event_id']==eid)['qualification'], 'TRADEABLE')
        self.assertIsNone(r['dominant']['Swing']['event_id'])

    def test_http_workflow_and_error_recovery(self):
        server = ThreadingHTTPServer(('127.0.0.1',0), make_handler(self.path / 'events.sqlite3'))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def request(path, data=None, origin=None):
            headers = {'Content-Type':'application/json','X-Event-Workbench':'1'}
            if origin: headers['Origin']=origin
            req = Request(base+path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
            with urlopen(req, timeout=10) as res:
                return res.read()
        try:
            self.assertIn('事件工作台', request('/').decode())
            event = json.loads(request('/api/parent', {'name':'测试录入','detection_mode':'News'}))['id']
            info = json.loads(request('/api/information', {'title':'测试事实','fact':'fixture'}))['id']
            request('/api/link', {'event_id':event,'information_id':info})
            history = json.loads(request('/api/event?id='+event))
            self.assertEqual(history['linked_information'][0]['information_id'], info)
            self.assertEqual(history['snapshot']['qualification'], 'WATCH')
            with self.assertRaises(HTTPError) as rejected:
                request('/api/state', {'event_id':event,'bias':'IM'})
            self.assertEqual(rejected.exception.code, 400)
            with self.assertRaises(HTTPError) as rejected:
                request('/api/parent', {'name':'bad','detection_mode':'News'}, 'https://external.invalid')
            self.assertEqual(rejected.exception.code, 403)
            self.assertEqual(len(json.loads(request('/api/events'))['events']), 1)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
