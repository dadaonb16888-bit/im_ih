"""Append source audits without backdating knowledge or asserting verified signals."""
import json
from pathlib import Path
from event_engine.engine import EventEngine, ROOT, now
from event_engine.csv_io import export_research


def apply(engine, package, stamp):
    added = {'information': 0, 'audit_notes': 0, 'draft_updates': 0}
    with engine.atomic():
        for source in package['sources']:
            record = {**source, 'collected_at': stamp, 'collection_mode': 'HistoricalSourceAudit'}
            existing = engine.db.execute('SELECT payload FROM information_inbox WHERE information_id=?',
                                         (record['information_id'],)).fetchone()
            if existing:
                record['collected_at'] = json.loads(existing['payload'])['collected_at']
            added['information'] += engine.add_information(record)
        for card in package['cards']:
            eid = card['event_id']
            if not engine.snapshot(eid, stamp):
                raise ValueError('审核引用不存在的事件: ' + eid)
            for iid in card['source_ids']:
                engine.link_information(eid, iid)
            note_id = package['audit_version'] + ':' + eid
            note = {'note_id': note_id, 'event_id': eid, 'kind': 'Parent', 'known_at': stamp,
                    'source': '历史原文核查 V1（来源与限制逐条记录）', 'claim': {'audit': card}}
            existing = engine.db.execute('SELECT payload FROM research_notes WHERE note_id=?', (note_id,)).fetchone()
            if existing:
                note['known_at'] = json.loads(existing['payload'])['known_at']
            added['audit_notes'] += engine.add_research_note(note)
            if card.get('draft_update'):
                update = {**card['draft_update'], 'update_id': note_id + ':draft', 'event_id': eid,
                          'known_at': stamp, 'effective_at': stamp, 'facts': card['facts'],
                          'reason': '本次原文核查补充事实及初步渠道，不是历史新增信息到达当时的记录。' + card['transmission']
                                    + ' 方向状态：' + card['direction_status'],
                          'evidence': card['source_ids'], 'information_ids': card['source_ids']}
                existing = engine.db.execute('SELECT payload FROM event_updates WHERE update_id=?',
                                             (update['update_id'],)).fetchone()
                if existing:
                    old = json.loads(existing['payload'])
                    update['known_at'], update['effective_at'] = old['known_at'], old['effective_at']
                added['draft_updates'] += engine.update_event(update)
    return added


def write_report(package, stamp):
    lines = ['# 首轮历史事件事实与因果审核', '', '审核记录可获得时间：' + stamp, '', package['boundary'], '',
             '官方事实核实不等于方向证实；渠道与周期是研究解释。两个因果更新保持reviewed=false，未提交正式Bias或市场确认。', '']
    labels = [('fact_status','事实状态'),('direction_status','方向结论'),('facts','已核实事实'),
              ('time_review','时间口径'),('transmission','传导假设'),('im_case','IM路径／反转可能'),
              ('ih_countercase','IH路径／相对影响限制'),('baseline','旧信息与预期基线'),
              ('information_routing','信息分流'),('invalidation','因果失效前提'),('next_action','下一审核动作')]
    sources = {s['information_id']: s for s in package['sources']}
    for card in package['cards']:
        lines += ['## ' + card['name'], '', '研究倾向：' + str(card['candidate_bias'] or '未确定')
                  + '；候选渠道：' + ' → '.join(card['candidate_channels']) + '；周期假设：' + card['candidate_horizon'], '']
        for key, label in labels:
            lines += ['**' + label + '：** ' + card[key], '']
        for key, label in [('corrections','口径修正'),('gaps','待补证据')]:
            lines += ['### ' + label, ''] + ['- ' + x for x in card[key]] + ['']
        lines += ['### 来源与精度', '']
        for iid in card['source_ids']:
            s = sources[iid]
            lines += ['- [' + s['title'] + '](' + s['url'] + ')：' + s['source'] + '；'
                      + s['published_at'] + '；' + s['publication_precision'] + '。' + s['verification']]
        lines += ['']
    (ROOT / 'docs' / '首轮历史事件审核.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    package = json.loads((ROOT / 'data' / 'historical_audit_v1.json').read_text(encoding='utf-8'))
    engine = EventEngine()
    try:
        stamp = now()
        backup = ROOT / 'database' / 'backups' / 'before_historical_audit_v1.sqlite3'
        if not backup.exists():
            import sqlite3
            with sqlite3.connect(backup) as target:
                engine.db.backup(target)
        added = apply(engine, package, stamp)
        first = engine.db.execute('SELECT known_at FROM research_notes WHERE note_id=?',
                    (package['audit_version'] + ':' + package['cards'][0]['event_id'],)).fetchone()[0]
        write_report(package, first)
        export_research(engine, ROOT / 'data' / 'exported_research')
        (ROOT / 'data' / 'knowledge_report.json').write_text(
            json.dumps(engine.report(stamp, include_historical=True), ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(added, ensure_ascii=False))
    finally:
        engine.close()


if __name__ == '__main__':
    main()
