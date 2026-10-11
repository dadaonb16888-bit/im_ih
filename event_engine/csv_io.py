"""CSV research import preserves source labels without activating signals."""
import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from .engine import CHANNELS, HORIZONS, STYLE, GAIN, PRICING, ACCEPTANCE, now, utc, encode

ALIASES = {
 '202210_SEMICONDUCTOR_RESTRICTION': '202210_CHIP_EXPORT',
 '202211_REOPENING_TRANSITION': '202211_REOPENING',
 '202310_STATE_SUPPORT': '202310_HUIJIN',
 '202401_SMALLCAP_LIQUIDITY_STRESS': '202401_SMALLCAP_LIQUIDITY',
 '202402_MARKET_STABILIZATION': '202402_STABILIZATION',
 '202404_NEW_NINE_RULES': '202404_REGULATION',
 '202405_PROPERTY_SUPPORT': '202405_PROPERTY',
 '202501_DEEPSEEK_AI_REPRICING': '202501_DEEPSEEK',
 '202504_TARIFF_CONFLICT': '202504_TARIFF'}
COMPOUND = {'TECH_GROWTH_RISK_OFF': ['TECH_GROWTH', 'RISK_OFF'],
            'LIQUIDITY_RISK_APPETITE': ['MARKET_LIQUIDITY', 'RISK_APPETITE']}


def rows(path, required):
    with Path(path).open(encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not set(required) <= set(reader.fieldnames):
            raise ValueError(str(path) + ': CSV缺少必要列')
        result = []
        for index, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f'{path}:{index} 列数不一致，每条记录须在同一行')
            if not any(row.values()):
                continue
            if any(not row[k].strip() for k in required):
                raise ValueError(f'{path}:{index} 必填项为空')
            result.append({k: v.strip() for k, v in row.items()})
        return result


def date_claim(value):
    if not value:
        return None
    if 'T' in value:
        utc(value)
        return {'value': value, 'precision': 'timestamp', 'verified': False}
    date.fromisoformat(value)
    return {'value': value, 'precision': 'date', 'verified': False}


def bias(value):
    value = value.replace('_', ' ')
    if value and value not in STYLE:
        raise ValueError('Bias枚举无效: ' + value)
    return value or None


def channels(value):
    result = COMPOUND.get(value) or [v for v in value.split('|') if v]
    if set(result) - CHANNELS:
        raise ValueError('Channel枚举无效: ' + value)
    return result


def import_research(engine, directory, known_at=None):
    directory = Path(directory)
    stamp = utc(known_at or now())
    parents = rows(directory / 'events.csv', ['event_id', 'event_name', 'event_type'])
    updates = rows(directory / 'event_updates.csv', ['event_id', 'update_time', 'source_type', 'information_gain', 'description'])
    states = rows(directory / 'event_states.csv', ['event_id', 'timestamp'])
    parsed = []
    parent_ids = set()
    for row in parents:
        eid = ALIASES.get(row['event_id'], row['event_id'])
        if eid in parent_ids:
            raise ValueError('CSV重复Parent: ' + eid)
        parent_ids.add(eid)
        if row['event_type'] not in ('News', 'MarketState') or row.get('horizon') not in HORIZONS:
            raise ValueError('历史事件DetectionMode或Horizon无效')
        if row.get('status') not in ('Active', 'Closed', 'Draft') or row.get('confidence') not in ('High', 'Medium', 'Low'):
            raise ValueError('历史来源Status或Confidence无效')
        event_date = date_claim(row.get('event_time'))
        tradable_date = date_claim(row.get('first_tradable_time'))
        if event_date and tradable_date and tradable_date['value'] < event_date['value']:
            raise ValueError('来源最早可交易日期不能早于来源事件日期')
        claim = {'raw': row, 'source_event_id': row['event_id'], 'source_initial_bias': bias(row.get('initial_bias', '')),
                 'source_channels': channels(row.get('channel', '')), 'source_horizon': row.get('horizon'),
                 'event_time_claim': event_date, 'first_tradable_time_claim': tradable_date}
        parsed.append((eid, 'Parent', claim))
    for row in updates:
        if row['information_gain'] not in GAIN:
            raise ValueError('Update来源InformationGain无效')
        parsed.append((ALIASES.get(row['event_id'], row['event_id']), 'EventUpdate',
            {'raw': row, 'update_time_claim': date_claim(row['update_time']),
             'source_new_bias': bias(row.get('new_bias', '')), 'source_new_channels': channels(row.get('new_channel', ''))}))
    for row in states:
        if row.get('pricing_state') and row['pricing_state'] not in PRICING:
            raise ValueError('State来源PricingState无效')
        if row.get('acceptance') and row['acceptance'] not in ACCEPTANCE:
            raise ValueError('State来源Acceptance无效')
        if row.get('dominant', '').lower() not in ('', 'true', 'false'):
            raise ValueError('State来源dominant无效')
        parsed.append((ALIASES.get(row['event_id'], row['event_id']), 'MarketState',
                       {'raw': row, 'timestamp_claim': date_claim(row['timestamp'])}))
    source = 'ChatGPT Phase 1 工程包CSV（研究标签未重新核实）'
    counts = {'new_parents': 0, 'new_research_notes': 0}
    with engine.atomic():
        for eid, kind, claim in parsed:
            if kind == 'Parent':
                old = engine.db.execute('SELECT payload FROM events WHERE event_id=?', (eid,)).fetchone()
                if old and json.loads(old['payload']).get('scope') != 'Historical':
                    raise ValueError('历史导入与当前事件ID冲突: ' + eid)
                if not old:
                    counts['new_parents'] += engine.create_event({'event_id': eid, 'name': claim['raw']['event_name'],
                        'detection_mode': claim['raw']['event_type'], 'known_at': stamp, 'scope': 'Historical',
                        'initial_bias': None, 'channels': [], 'horizon': None, 'reviewed': False,
                        'notes': '历史知识库，日期与方向保存在来源记录中；正式Bias须经因果审核。'})
            if not engine.db.execute('SELECT 1 FROM events WHERE event_id=?', (eid,)).fetchone():
                raise ValueError('CSV引用的Parent不存在: ' + eid)
            digest = hashlib.sha256(encode({'event_id': eid, 'kind': kind, 'claim': claim}).encode()).hexdigest()[:20]
            nid = 'research-' + digest
            existing = engine.db.execute('SELECT payload FROM research_notes WHERE note_id=?', (nid,)).fetchone()
            note = {'note_id': nid, 'event_id': eid, 'kind': kind, 'known_at': stamp,
                    'source': source, 'claim': claim}
            if existing:
                note['known_at'] = json.loads(existing['payload'])['known_at']
            counts['new_research_notes'] += engine.add_research_note(note)
    return {**counts, 'note': '仅导入历史研究记录；未产生正式因果Update、市场确认或交易信号。'}


def export_research(engine, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    grouped = {'Parent': [], 'EventUpdate': [], 'MarketState': []}
    notes = []
    for row in engine.db.execute('SELECT payload FROM research_notes ORDER BY kind,note_id'):
        note = json.loads(row['payload'])
        notes.append(note)
        if note['claim'].get('raw'):
            grouped[note['kind']].append(note['claim']['raw'])
    for kind, records in grouped.items():
        path = directory / {'Parent': 'events.csv', 'EventUpdate': 'event_updates.csv', 'MarketState': 'event_states.csv'}[kind]
        fields = list(dict.fromkeys(k for row in records for k in row)) or ['event_id_canonical']
        with path.open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
    (directory / 'research_notes.json').write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding='utf-8')
    return {kind: len(records) for kind, records in grouped.items()}
