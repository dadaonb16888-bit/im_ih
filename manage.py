"""JSON-in, JSON-out operations for the local event ledger."""
import argparse
import json
from pathlib import Path
from event_engine.engine import EventEngine, ROOT, now
from event_engine.csv_io import import_research, export_research
from event_engine.collection import CollectionLedger
from event_engine.ai_research import AIResearch
from event_engine.news_screening import NewsScreening
from event_engine.discovery import DiscoveryLedger


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def migrate(engine, folder, migrated_at):
    folder = Path(folder)
    inbox = read_json(folder / 'information_inbox.json')
    legacy_events = read_json(folder / 'events.json')
    audit = [json.loads(line) for line in
             (folder / 'event_updates.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    counts = {'new_information': 0, 'new_draft_events': 0, 'new_legacy_audit': 0}
    for info in inbox:
        counts['new_information'] += engine.add_information(info)
    for old in legacy_events:
        eid = old['event_id']
        # Preserve previous processing in legacy payload; do not invent causality/timestamps.
        draft = {'event_id': eid, 'name': old['title'], 'detection_mode': 'News',
                 'category': old.get('category'), 'known_at': migrated_at,
                 'event_time': old.get('first_public_at'),
                 'first_tradable_time': old.get('first_tradable_time'),
                 'initial_bias': None, 'bias': None, 'channels': [], 'horizon': None,
                 'directness': None, 'independent_cause': None, 'relative_pricing': None,
                 'reviewed': False, 'invalidation': old.get('invalidation'),
                 'notes': '旧卡为待审核Parent候选；P1/P2/P3不是信息增量；旧Trend不是新Horizon。',
                 'legacy': old}
        # On repeated migration retain the first import's known_at.
        existing = engine.db.execute('SELECT payload FROM events WHERE event_id=?', (eid,)).fetchone()
        if existing:
            draft['known_at'] = json.loads(existing['payload'])['known_at']
        counts['new_draft_events'] += engine.create_event(draft)
        for iid in old.get('information_ids', []):
            engine.link_information(eid, iid)
    for index, entry in enumerate(audit, 1):
        counts['new_legacy_audit'] += engine._insert('legacy_audit', 'audit_id', f'legacy-{index:04d}', entry)
    for filename in ('sources.json', 'information_review_20261010.json',
                     'collection_window_20261010.json', 'index_exposure_20260930.json'):
        engine._insert('legacy_audit', 'audit_id', 'reference:' + filename,
                       {'filename': filename, 'content': read_json(folder / filename)})
    totals = {t: engine.db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
              for t in ('information_inbox', 'events', 'event_information', 'event_updates', 'state_updates', 'legacy_audit')}
    return {'migration_changes': counts, 'totals': totals,
            'note': '旧研究版本记录只作审计，未冒充新的因果信息或行情确认。'}


def main():
    parser = argparse.ArgumentParser(description='IM/IH事件处理：保存事实、因果更新、市场状态及当前资格')
    parser.add_argument('--database', default=str(ROOT / 'database' / 'events.sqlite3'))
    sub = parser.add_subparsers(dest='operation', required=True)
    for op in ('add-information', 'create', 'update', 'state', 'collection',
               'source-check', 'collection-item', 'triage', 'parent-review'):
        cmd = sub.add_parser(op)
        cmd.add_argument('json_file')
    migration = sub.add_parser('migrate')
    migration.add_argument('research_folder')
    migration.add_argument('--known-at', default=None)
    report = sub.add_parser('report')
    report.add_argument('--as-of', default=None)
    report.add_argument('--output', default=None)
    report.add_argument('--include-historical', action='store_true')
    alpha = sub.add_parser('alpha-report')
    alpha.add_argument('--as-of', default=None)
    alpha.add_argument('--output', default=None)
    alpha.add_argument('--include-historical', action='store_true')
    research_alpha = sub.add_parser('research-alpha-report')
    research_alpha.add_argument('--as-of', default=None)
    research_alpha.add_argument('--output', default=None)
    research_alpha.add_argument('--include-historical', action='store_true')
    imp = sub.add_parser('import-research')
    imp.add_argument('directory')
    exp = sub.add_parser('export-research')
    exp.add_argument('directory')
    hist = sub.add_parser('history')
    hist.add_argument('event_id')
    hist.add_argument('--as-of', default=None)
    collection_report = sub.add_parser('collection-report')
    collection_report.add_argument('batch_id')
    collection_report.add_argument('--as-of', default=None)
    collection_report.add_argument('--output', default=None)
    sub.add_parser('collection-plan')
    ai_context = sub.add_parser('ai-context')
    ai_context.add_argument('event_id')
    ai_context.add_argument('--output', default=None)
    ai_import = sub.add_parser('apply-ai-research')
    ai_import.add_argument('json_file')
    screening_import = sub.add_parser('apply-news-screening')
    screening_import.add_argument('json_file')
    discovery_import = sub.add_parser('apply-discovery')
    discovery_import.add_argument('json_file')
    screening_report = sub.add_parser('screening-report')
    screening_report.add_argument('--as-of', default=None)
    screening_report.add_argument('--output', default=None)
    args = parser.parse_args()
    engine = EventEngine(args.database)
    try:
        if args.operation == 'migrate':
            result = migrate(engine, args.research_folder, args.known_at or now())
        elif args.operation == 'report':
            result = engine.report(args.as_of or now(), include_historical=args.include_historical)
            if args.output:
                Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        elif args.operation == 'alpha-report':
            result = engine.alpha_report(args.as_of or now(), args.include_historical)
            if args.output:
                Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        elif args.operation == 'research-alpha-report':
            result = AIResearch(engine).scoring_report(args.as_of, args.include_historical)
            if args.output:
                Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        elif args.operation == 'import-research':
            result = import_research(engine, args.directory)
        elif args.operation == 'export-research':
            result = export_research(engine, args.directory)
        elif args.operation == 'history':
            result = engine.history(args.event_id, args.as_of or now())
        elif args.operation == 'collection-plan':
            result = CollectionLedger(engine).plan()
        elif args.operation == 'collection-report':
            result = CollectionLedger(engine).report(args.batch_id, args.as_of)
            if args.output:
                Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        elif args.operation == 'ai-context':
            result = AIResearch(engine).context(args.event_id)
            if args.output:
                Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        elif args.operation == 'apply-ai-research':
            result = AIResearch(engine).apply_pack(read_json(args.json_file))
        elif args.operation == 'apply-news-screening':
            result = NewsScreening(engine).apply_pack(read_json(args.json_file))
        elif args.operation == 'apply-discovery':
            result = DiscoveryLedger(engine).apply_pack(read_json(args.json_file))
        elif args.operation == 'screening-report':
            result = NewsScreening(engine).report(args.as_of)
            if args.output:
                Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        else:
            collection = CollectionLedger(engine)
            operation = {'add-information': engine.add_information, 'create': engine.create_event,
                         'update': engine.update_event, 'state': engine.update_state,
                         'collection': collection.create_batch, 'source-check': collection.check_source,
                         'collection-item': collection.add_item, 'triage': collection.triage,
                         'parent-review': collection.review_parent}[args.operation]
            result = {'inserted': operation(read_json(args.json_file))}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        engine.close()


if __name__ == '__main__':
    main()
