"""Local-only Phase 1 workbench. No external assets, market feeds or trading."""
import argparse
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from event_engine.engine import EventEngine, ROOT, now, utc
from event_engine.collection import CollectionLedger
from event_engine.ai_research import AIResearch


def identifier(prefix):
    day = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    return prefix + '-' + day + '-' + secrets.token_hex(4)


def detail(engine, eid):
    history = engine.history(eid, now())
    library = json.loads((ROOT / 'data' / 'historical_library.json').read_text(encoding='utf-8'))
    history['original_research'] = next((p for p in library['parents'] if p['event_id'] == eid), None)
    history['linked_information'] = [json.loads(r['payload']) for r in engine.db.execute(
        '''SELECT i.payload FROM information_inbox i JOIN event_information l
           ON i.information_id=l.information_id WHERE l.event_id=? ORDER BY i.information_id''', (eid,))]
    history['ai_assessments'] = AIResearch(engine).list_assessments(eid)
    history['research_alpha'] = AIResearch(engine).preview(eid)
    return history


def make_handler(database):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, content, status=200, content_type='application/json; charset=utf-8'):
            body = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def safe_host(self):
            # Reject DNS rebinding and requests claiming an external host.
            host = self.headers.get('Host', '')
            return host in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.safe_host():
                return self.respond({'error': '仅允许本机访问'}, 403)
            path = urlsplit(self.path)
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8'),
                      '/collection.js': ('collection.js', 'text/javascript; charset=utf-8')}
            if path.path in assets:
                file, mime = assets[path.path]
                return self.respond((ROOT / 'dashboard' / file).read_bytes(), content_type=mime)
            engine = EventEngine(database)
            try:
                if path.path == '/api/events':
                    result = engine.report(now(), include_historical=True)
                    result['counts'] = {table: engine.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                                        for table in ('events', 'information_inbox', 'research_notes', 'event_updates', 'state_updates', 'ai_assessments')}
                    ai = AIResearch(engine)
                    for event in result['events']:
                        assessments = ai.list_assessments(event['event_id'], result['as_of'])
                        event['ai_assessment_count'] = len(assessments)
                        event['ai_latest_known_at'] = assessments[-1]['known_at'] if assessments else None
                    self.respond(result)
                elif path.path == '/api/event':
                    self.respond(detail(engine, parse_qs(path.query).get('id', [''])[0]))
                elif path.path == '/api/alpha':
                    query = parse_qs(path.query)
                    self.respond(engine.alpha_report(query.get('as_of', [now()])[0],
                                                      query.get('include_historical', ['false'])[0] == 'true'))
                elif path.path == '/api/research-alpha':
                    query = parse_qs(path.query)
                    self.respond(AIResearch(engine).scoring_report(query.get('as_of', [None])[0],
                                                      query.get('include_historical', ['false'])[0] == 'true'))
                elif path.path == '/api/source-snapshot':
                    query = parse_qs(path.query)
                    self.respond(AIResearch(engine).source_snapshot(query.get('id', [''])[0]),
                                 content_type='application/pdf')
                elif path.path == '/api/information':
                    self.respond([json.loads(r['payload']) for r in engine.db.execute('SELECT payload FROM information_inbox ORDER BY information_id')])
                elif path.path == '/api/collection-plan':
                    self.respond(CollectionLedger(engine).plan())
                elif path.path == '/api/collections':
                    self.respond(CollectionLedger(engine).list_batches())
                elif path.path == '/api/collection':
                    query = parse_qs(path.query)
                    self.respond(CollectionLedger(engine).report(query.get('id', [''])[0], query.get('as_of', [None])[0]))
                else:
                    self.respond({'error': '页面不存在'}, 404)
            except (ValueError, KeyError, TypeError) as exc:
                self.respond({'error': str(exc)}, 400)
            finally:
                engine.close()

        def do_POST(self):
            if not self.safe_host() or self.headers.get('X-Event-Workbench') != '1':
                return self.respond({'error': '请求来源无效'}, 403)
            origin = self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
                return self.respond({'error': '跨来源写入被拒绝'}, 403)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.respond({'error': '需要JSON输入'}, 400)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024 * 1024:
                    raise ValueError('输入长度无效')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('需要对象输入')
            except (ValueError, json.JSONDecodeError) as exc:
                return self.respond({'error': str(exc)}, 400)
            engine = EventEngine(database)
            try:
                if self.path == '/api/information':
                    # Keep first sighting separate from the server's actual entry timestamp.
                    data.setdefault('information_id', identifier('I'))
                    data['recorded_at'] = now()
                    data['observed_at'] = data['recorded_at']
                    data['observation_time_basis'] = 'WorkbenchEntry'
                    if data.get('first_seen_at'):
                        data['first_seen_at'] = utc(data['first_seen_at'])
                        if data['first_seen_at'] > data['recorded_at']:
                            raise ValueError('首次发现时间不能晚于实际录入时间')
                        if not isinstance(data.get('first_seen_evidence'), str) or not data['first_seen_evidence'].strip():
                            raise ValueError('填写首次发现时间时必须提供依据')
                    if data.get('published_at'):
                        # Full timestamps are normalized. Explicit date precision stays a draft.
                        if 'T' in data['published_at']:
                            data['published_at'] = utc(data['published_at'])
                        else:
                            datetime.strptime(data['published_at'], '%Y-%m-%d')
                    batch_id = data.pop('batch_id', None)
                    category = data.pop('category', None)
                    notes = data.pop('notes', '')
                    with engine.atomic():
                        inserted = engine.add_information(data)
                        if batch_id:
                            CollectionLedger(engine).add_item({'item_id': identifier('CI'), 'batch_id': batch_id,
                                'information_id': data['information_id'], 'category': category,
                                'notes': notes, 'known_at': data['recorded_at']})
                    return self.respond({'inserted': inserted, 'id': data['information_id']})
                if self.path == '/api/link':
                    eid, iid = data.get('event_id'), data.get('information_id')
                    if not eid or not iid:
                        raise ValueError('关联需要事件和信息编号')
                    engine.link_information(eid, iid)
                    return self.respond({'inserted': True, 'id': iid})
                collection = CollectionLedger(engine)
                operations = {'/api/parent': ('event_id', 'E', engine.create_event),
                    '/api/update': ('update_id', 'EU', engine.update_event),
                    '/api/state': ('state_id', 'ES', engine.update_state),
                    '/api/note': ('note_id', 'RN', engine.add_research_note),
                    '/api/collection': ('batch_id', 'CB', collection.create_batch),
                    '/api/source-check': ('check_id', 'SC', collection.check_source),
                    '/api/collection-item': ('item_id', 'CI', collection.add_item),
                    '/api/triage': ('review_id', 'TR', collection.triage),
                    '/api/parent-review': ('review_id', 'PR', collection.review_parent)}
                if self.path not in operations:
                    return self.respond({'error': '操作不存在'}, 404)
                key, prefix, operation = operations[self.path]
                data.setdefault(key, identifier(prefix))
                # UI judgments are known now. Earlier public times never backdate their annotation.
                data['known_at'] = now()
                inserted = operation(data)
                self.respond({'inserted': inserted, 'id': data[key]})
            except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as exc:
                self.respond({'error': str(exc)}, 400)
            finally:
                engine.close()
    return Handler


def main():
    parser = argparse.ArgumentParser(description='本地IM/IH事件录入工作台')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--database', default=str(ROOT / 'database' / 'events.sqlite3'))
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(args.database))
    print(f'事件工作台：http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
