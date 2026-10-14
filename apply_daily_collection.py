"""Trusted local, append-only import of a reviewed collection package; no fetching."""
import argparse
import json
from copy import deepcopy
from pathlib import Path

from event_engine.collection import CollectionLedger
from event_engine.engine import EventEngine, ROOT, encode, now, reject_extra, utc

SECTIONS = ('information', 'parents', 'source_checks', 'items', 'triage', 'parent_reviews')


def apply(engine, package):
    reject_extra(package, {'package_id', 'batch', *SECTIONS})
    if not isinstance(package.get('package_id'), str) or not package['package_id'].strip():
        raise ValueError('需要收集包编号')
    if not isinstance(package.get('batch'), dict):
        raise ValueError('需要收集批次')
    for key in SECTIONS:
        if not isinstance(package.get(key), list):
            raise ValueError(key + '需要列表')
    # Store exact submitted content so changed packages cannot silently skip writes.
    audit_id = 'daily-collection:' + package['package_id']
    old = engine.db.execute('SELECT payload FROM legacy_audit WHERE audit_id=?', (audit_id,)).fetchone()
    if old:
        previous = json.loads(old['payload'])
        if encode(previous['submitted_package']) != encode(package):
            raise ValueError('收集包已存在且内容不同；修订须使用新编号')
        return {'inserted': False, 'known_at': previous['known_at'], 'batch_id': previous['batch_id']}
    stamp = now()
    p = deepcopy(package)
    batch_id = p['batch']['batch_id']
    # Submitted dates are publication annotations, never authority to backdate knowledge.
    with engine.atomic():
        ledger = CollectionLedger(engine)
        ledger.create_batch({**p['batch'], 'known_at': stamp})
        for info in p['information']:
            # first_seen_at is the actual read timestamp from the audit, if available.
            if info.get('first_seen_at') and utc(info['first_seen_at']) > stamp:
                raise ValueError('发现时刻不能晚于入库时刻')
            engine.add_information({**info, 'observed_at': stamp, 'recorded_at': stamp,
                                    'added_by': 'Codex'})
        for parent in p['parents']:
            engine.create_event({**parent, 'known_at': stamp})
        operations = (('source_checks', ledger.check_source), ('items', ledger.add_item),
                      ('triage', ledger.triage), ('parent_reviews', ledger.review_parent))
        for section, operation in operations:
            for record in p[section]:
                if record.get('batch_id', batch_id) != batch_id:
                    raise ValueError('收集记录的批次不一致')
                operation({**record, 'batch_id': batch_id, 'known_at': stamp})
        engine._insert('legacy_audit', 'audit_id', audit_id,
                       {'submitted_package': package, 'known_at': stamp, 'batch_id': batch_id})
    return {'inserted': True, 'known_at': stamp, 'batch_id': batch_id,
            'added': {key: len(p[key]) for key in SECTIONS}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--database', type=Path, default=ROOT / 'database' / 'events.sqlite3')
    args = parser.parse_args()
    engine = EventEngine(args.database)
    try:
        result = apply(engine, json.loads(args.package.read_text(encoding='utf-8')))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        engine.close()


if __name__ == '__main__':
    main()
