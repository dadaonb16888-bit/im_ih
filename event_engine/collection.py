"""Daily collection audit. Checks and routing never generate causal or market labels."""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .engine import CATEGORIES, ROOT, utc, now, reject_extra

CHINA = timezone(timedelta(hours=8))
ROUTES = {'NewParent', 'EventUpdate', 'MarketState', 'Background', 'Pending'}


def text_required(data, fields):
    for field in fields:
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError('收集记录缺少有效的' + field)


def evidence_required(data):
    value = data.get('evidence')
    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError('需要至少一项来源链接或可核查的证据位置')


def normalize_url(value):
    """Only flag likely duplicate originals; never merge distinct reports automatically."""
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ('http', 'https') or not parts.netloc:
        return None
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith('utm_')]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(query), ''))


def defaults(cutoff=None):
    end = datetime.fromisoformat(utc(cutoff or now())).astimezone(CHINA)
    # Monday includes the weekend. Holiday extensions remain explicit, not guessed.
    days = 3 if end.weekday() == 0 else 1
    start = (end - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return {'window_start': start.isoformat(timespec='seconds'),
            'cutoff': end.isoformat(timespec='seconds'),
            'window_reason': '周一补齐周末，从上周五00:00开始' if days == 3
            else '前一自然日00:00至当前；节后请扩大到完整休市期'}


class CollectionLedger:
    def __init__(self, engine):
        self.engine = engine
        self.db = engine.db

    def sources(self):
        row = self.db.execute("SELECT payload FROM legacy_audit WHERE audit_id='reference:sources.json'").fetchone()
        raw = json.loads(row['payload'])['content'] if row else json.loads(
            (ROOT / 'data' / 'source_registry.json').read_text(encoding='utf-8'))
        # Previous access claims describe their old run, never today's coverage.
        return [{k: s.get(k) for k in ('source_id', 'name', 'url', 'categories', 'collect')} for s in raw]

    def plan(self):
        return {'defaults': defaults(), 'categories': sorted(CATEGORIES), 'sources': self.sources()}

    def _batch(self, batch_id, as_of):
        row = self.db.execute('SELECT payload FROM collection_batches WHERE batch_id=? AND known_at<=?',
                              (batch_id, as_of)).fetchone()
        if not row:
            raise ValueError('收集批次不存在或在此时尚不可见')
        return json.loads(row['payload'])

    def _records(self, table, batch_id, as_of):
        return [json.loads(r['payload']) for r in self.db.execute(
            f'SELECT payload FROM {table} WHERE batch_id=? AND known_at<=? ORDER BY known_at,rowid',
            (batch_id, as_of))]

    def _prepare(self, data, key, allowed):
        data = dict(data)
        reject_extra(data, {key, 'batch_id', 'known_at', *allowed})
        text_required(data, (key, 'batch_id'))
        data['known_at'] = utc(data['known_at'])
        batch = self._batch(data['batch_id'], data['known_at'])
        return data, batch

    def create_batch(self, data):
        data = dict(data)
        reject_extra(data, {'batch_id', 'window_start', 'cutoff', 'window_reason', 'known_at'})
        text_required(data, ('batch_id', 'window_reason'))
        for field in ('known_at', 'window_start', 'cutoff'):
            data[field] = utc(data[field])
        if not data['window_start'] < data['cutoff'] <= data['known_at']:
            raise ValueError('窗口起点须早于Cutoff，Cutoff不能晚于创建时刻')
        data['timezone'] = 'Asia/Shanghai'
        # Freeze the source plan so subsequent registry changes cannot rewrite completeness.
        data['sources'] = self.sources()
        data['categories'] = sorted(CATEGORIES)
        data['parent_ids'] = [e['event_id'] for e in self.engine.report(data['known_at'])['events']
                              if e['qualification'] != 'INVALID']
        return self.engine._insert('collection_batches', 'batch_id', data['batch_id'], data,
                                   {'known_at': data['known_at']})

    def list_batches(self, as_of=None):
        at = utc(as_of or now())
        return [json.loads(r['payload']) for r in self.db.execute(
            'SELECT payload FROM collection_batches WHERE known_at<=? ORDER BY known_at DESC,rowid DESC', (at,))]

    def check_source(self, data):
        data, batch = self._prepare(data, 'check_id', {'category', 'source_id', 'status', 'searched_at',
            'search_scope', 'hit_count', 'fulltext_status', 'evidence', 'gaps'})
        text_required(data, ('category', 'source_id', 'search_scope', 'fulltext_status'))
        if data['category'] not in batch['categories']:
            raise ValueError('信息类别无效')
        source = next((s for s in batch['sources'] if s['source_id'] == data['source_id']), None)
        if not source or data['category'] not in source['categories']:
            raise ValueError('此来源未登记为该类别的检查入口')
        if data.get('status') not in ('Complete', 'Partial', 'Blocked'):
            raise ValueError('检查状态必须为Complete/Partial/Blocked')
        if type(data.get('hit_count')) is not int or data['hit_count'] < 0:
            raise ValueError('命中数必须为非负整数；不代表独立事件数')
        if data['fulltext_status'] not in ('Readable', 'NoHits', 'Partial', 'Unavailable'):
            raise ValueError('全文状态无效')
        data['searched_at'] = utc(data['searched_at'])
        if not batch['window_start'] <= data['searched_at'] <= data['known_at']:
            raise ValueError('检索时间必须在窗口开始之后且不晚于记录时间')
        evidence_required(data)
        data.setdefault('gaps', '')
        if not isinstance(data['gaps'], str):
            raise ValueError('缺口必须为文字')
        if data['status'] == 'Complete':
            if data['searched_at'] < batch['cutoff']:
                raise ValueError('完整检查须在Cutoff后完成，才能覆盖整个窗口')
            expected = 'NoHits' if data['hit_count'] == 0 else 'Readable'
            if data['fulltext_status'] != expected or data['gaps'].strip():
                raise ValueError('有未读全文或缺口时不能标记完整；零命中使用NoHits')
        elif not data['gaps'].strip():
            raise ValueError('部分或受阻检查必须说明缺口')
        return self.engine._insert('source_checks', 'check_id', data['check_id'], data,
            {'batch_id': data['batch_id'], 'known_at': data['known_at']})

    def add_item(self, data):
        data, batch = self._prepare(data, 'item_id', {'information_id', 'category', 'notes'})
        text_required(data, ('information_id', 'category'))
        if data['category'] not in batch['categories']:
            raise ValueError('信息类别无效')
        info = self._information(data['information_id'], data['known_at'])
        existing = self.db.execute('SELECT payload FROM collection_items WHERE batch_id=? AND information_id=? ORDER BY known_at DESC,rowid DESC LIMIT 1',
                                   (data['batch_id'], data['information_id'])).fetchone()
        if existing:
            old = json.loads(existing['payload'])
            if old['category'] == data['category'] and old.get('notes', '') == data.get('notes', ''):
                return False
        return self.engine._insert('collection_items', 'item_id', data['item_id'], data,
            {k: data[k] for k in ('batch_id', 'information_id', 'known_at')})

    def _information(self, information_id, as_of):
        row = self.db.execute('SELECT payload FROM information_inbox WHERE information_id=?', (information_id,)).fetchone()
        if not row:
            raise ValueError('原始信息不存在')
        info = json.loads(row['payload'])
        # Existing legacy payloads can have missing/uncertain observation times. Membership's
        # known_at controls their visibility; valid future observation times still cannot leak.
        if info.get('recorded_at'):
            if utc(info['recorded_at']) > as_of:
                raise ValueError('信息在此时尚未录入')
        if info.get('observed_at'):
            try:
                observed = utc(info['observed_at'])
            except ValueError:
                observed = None
            if observed and observed > as_of:
                raise ValueError('信息在此时尚未观察到')
        return info

    def triage(self, data):
        data, batch = self._prepare(data, 'review_id', {'information_id', 'route', 'event_id', 'reason', 'evidence'})
        text_required(data, ('information_id', 'reason'))
        evidence_required(data)
        if data.get('route') not in ROUTES:
            raise ValueError('信息去向无效')
        if not any(x['information_id'] == data['information_id'] for x in
                   self._records('collection_items', data['batch_id'], data['known_at'])):
            raise ValueError('请先把原始信息加入此批次')
        event_id = data.get('event_id')
        if data['route'] in ('NewParent', 'EventUpdate', 'MarketState'):
            text_required(data, ('event_id',))
            parent = self.engine.snapshot(event_id, data['known_at'])
            if parent is None or parent.get('scope', 'Current') == 'Historical':
                raise ValueError('此去向需要当时可见的近期Parent')
            if data['route'] == 'NewParent' and parent.get('reviewed'):
                raise ValueError('已完成因果审核的Parent应归并为EventUpdate')
        elif event_id is not None:
            raise ValueError('背景或待核实信息不指定Parent；需要归并时改用相应去向')
        data['event_id'] = event_id
        with self.engine.atomic():
            inserted = self.engine._insert('information_reviews', 'review_id', data['review_id'], data,
                {k: data[k] for k in ('batch_id', 'information_id', 'event_id', 'known_at')})
            if event_id:
                self.engine.link_information(event_id, data['information_id'])
        return inserted

    def review_parent(self, data):
        data, batch = self._prepare(data, 'review_id', {'event_id', 'result', 'reason', 'evidence'})
        text_required(data, ('event_id', 'reason'))
        evidence_required(data)
        if data.get('result') not in ('NoChange', 'NewInformation', 'Pending'):
            raise ValueError('后续复核结果无效')
        if data['event_id'] not in batch['parent_ids']:
            raise ValueError('此Parent不属于创建批次时的待复核名单')
        return self.engine._insert('parent_reviews', 'review_id', data['review_id'], data,
            {k: data[k] for k in ('batch_id', 'event_id', 'known_at')})

    def report(self, batch_id, as_of=None):
        at = utc(as_of or now())
        batch = self._batch(batch_id, at)
        checks = self._records('source_checks', batch_id, at)
        coverage = []
        for category in batch['categories']:
            required = [s for s in batch['sources'] if category in s['categories']]
            latest = {c['source_id']: c for c in checks if c['category'] == category}
            missing = [s['source_id'] for s in required if s['source_id'] not in latest]
            values = list(latest.values())
            status = 'Unreviewed'
            if values:
                status = ('Complete' if required and not missing and all(c['status'] == 'Complete' for c in values)
                          else 'Blocked' if not missing and all(c['status'] == 'Blocked' for c in values)
                          else 'Partial')
            coverage.append({'category': category, 'status': status, 'required_sources': required,
                             'checks': values, 'missing_source_ids': missing})
        reviews = {r['information_id']: r for r in self._records('information_reviews', batch_id, at)}
        all_info = [json.loads(r['payload']) for r in self.db.execute('SELECT payload FROM information_inbox')]
        url_ids = {}
        for info in all_info:
            try:
                visible = ((not info.get('observed_at') or utc(info['observed_at']) <= at)
                           and (not info.get('recorded_at') or utc(info['recorded_at']) <= at))
            except ValueError:
                visible = False
            url = normalize_url(info.get('url'))
            if visible and url:
                url_ids.setdefault(url, []).append(info['information_id'])
        information = []
        items = {i['information_id']: i for i in self._records('collection_items', batch_id, at)}
        for item in items.values():
            info = self._information(item['information_id'], at)
            try:
                published = utc(info.get('published_at'))
            except (ValueError, TypeError):
                published = None
            relation = ('TimeUnknown' if not published else 'Late' if published < batch['window_start']
                        else 'AfterCutoff' if published > batch['cutoff'] else 'InWindow')
            try:
                found_late = utc(info.get('first_seen_at') or info.get('observed_at')) > batch['cutoff']
            except (ValueError, TypeError):
                found_late = None
            information.append({**info, 'category': item['category'], 'collection_notes': item.get('notes', ''),
                'temporal_relation': relation, 'found_late': found_late,
                'duplicate_ids': [i for i in url_ids.get(normalize_url(info.get('url')), []) if i != item['information_id']],
                'routing': reviews.get(item['information_id'])})
        parent_reviews = {r['event_id']: r for r in self._records('parent_reviews', batch_id, at)}
        followups = []
        for eid in batch['parent_ids']:
            parent = self.engine.snapshot(eid, at)
            followups.append({'event_id': eid, 'name': parent['name'], 'scope': parent.get('scope', 'Current'),
                              'review': parent_reviews.get(eid)})
        counts = {'information': len(information),
            'pending_triage': sum(not i['routing'] or i['routing']['route'] == 'Pending' for i in information),
            'unknown_time': sum(i['temporal_relation'] == 'TimeUnknown' for i in information),
            'late': sum(i['temporal_relation'] == 'Late' or i['found_late'] is True for i in information),
            'after_cutoff': sum(i['temporal_relation'] == 'AfterCutoff' for i in information),
            'missing_categories': sum(c['status'] != 'Complete' for c in coverage),
            'pending_parent_reviews': sum(not p['review'] or p['review']['result'] == 'Pending' for p in followups)}
        gaps = []
        if counts['missing_categories']:
            gaps.append(f"{counts['missing_categories']}类登记来源尚未完成覆盖；空白不代表无事件")
        if counts['pending_triage']:
            gaps.append(f"{counts['pending_triage']}条信息尚未完成分流")
        if counts['unknown_time']:
            gaps.append(f"{counts['unknown_time']}条信息发布时间待核实，不能声称已按时间完整归档")
        if counts['after_cutoff']:
            gaps.append(f"{counts['after_cutoff']}条信息晚于本批Cutoff，请在新批次中检查")
        if counts['pending_parent_reviews']:
            gaps.append(f"{counts['pending_parent_reviews']}个既有Parent后续尚未复核")
        return {'batch': batch, 'as_of': at, 'coverage': coverage, 'information': information,
                'parent_followups': followups, 'counts': counts, 'ready': not gaps, 'gaps': gaps,
                'check_history': checks,
                'routing_history': self._records('information_reviews', batch_id, at),
                'parent_review_history': self._records('parent_reviews', batch_id, at),
                'item_history': self._records('collection_items', batch_id, at),
                'note': '完整仅指登记入口及人工审核清单；不是全网无遗漏证明，也不生成方向或市场确认。'}
