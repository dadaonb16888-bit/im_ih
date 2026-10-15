"""Unverified index leads, separate from read facts and three-round screening.

No fetching or model calls. Only the trusted local import stamps knowledge time.
"""
import json
from copy import deepcopy
from urllib.parse import urlsplit

from .collection import CollectionLedger, evidence_required, normalize_url, text_required
from .engine import encode, now, reject_extra, utc

STATUSES = ('Pending', 'Blocked', 'Linked', 'Excluded')


def safe_url(value):
    normalized = normalize_url(value)
    if not normalized or urlsplit(normalized).username or urlsplit(normalized).password:
        raise ValueError('线索和入口需要不含登录凭据的HTTP/HTTPS链接')
    return normalized


class DiscoveryLedger:
    def __init__(self, engine):
        self.engine = engine
        self.db = engine.db
        self.collection = CollectionLedger(engine)

    def add_lead(self, data):
        data, batch = self.collection._prepare(data, 'lead_id', {
            'source_id', 'title', 'url', 'index_url', 'captured_at', 'date_clue', 'evidence'})
        text_required(data, ('source_id', 'title'))
        if data['source_id'] not in {s['source_id'] for s in batch['sources']}:
            raise ValueError('线索来源不在本批冻结登记清单中')
        data['url'] = safe_url(data.get('url'))
        data['index_url'] = safe_url(data.get('index_url'))
        data['captured_at'] = utc(data.get('captured_at'))
        if data['captured_at'] > data['known_at']:
            raise ValueError('扫描时刻不能晚于实际入库')
        data.setdefault('date_clue', '')
        if not isinstance(data['date_clue'], str) or len(data['date_clue']) > 240:
            raise ValueError('日期线索须为短文本，尚不代表核实后的发布时间')
        evidence_required(data)
        existing = self.db.execute('SELECT lead_id FROM discovery_leads WHERE batch_id=? '
            'AND source_id=? AND normalized_url=?',
            (data['batch_id'], data['source_id'], data['url'])).fetchone()
        if existing and existing['lead_id'] != data['lead_id']:
            raise ValueError('同批同入口URL已登记；应追加处理记录，不新建同一线索')
        return self.engine._insert('discovery_leads', 'lead_id', data['lead_id'], data,
            {k: data[k] for k in ('batch_id', 'known_at', 'source_id')} | {'normalized_url': data['url']})

    def resolve(self, data):
        data, _ = self.collection._prepare(data, 'resolution_id', {
            'lead_id', 'prior_resolution_id', 'status', 'reason', 'evidence', 'information_id'})
        text_required(data, ('lead_id', 'reason'))
        evidence_required(data)
        if data.get('status') not in STATUSES:
            raise ValueError('线索处理状态无效')
        if 'prior_resolution_id' not in data:
            raise ValueError('必须明确前次处理ID；首次使用null')
        lead = self.db.execute('SELECT payload FROM discovery_leads WHERE lead_id=? '
            'AND batch_id=? AND known_at<=?', (data['lead_id'], data['batch_id'], data['known_at'])).fetchone()
        if not lead:
            raise ValueError('线索在此批次和时点不可见')
        lead = json.loads(lead['payload'])
        # Check replay before the optimistic predecessor check.
        old = self.db.execute('SELECT payload FROM discovery_resolutions WHERE resolution_id=?',
                              (data['resolution_id'],)).fetchone()
        data.setdefault('information_id', None)
        if data['status'] == 'Linked':
            text_required(data, ('information_id',))
            info = self.collection._information(data['information_id'], data['known_at'])
            if normalize_url(info.get('url')) != lead['url']:
                raise ValueError('关联原文URL必须与线索一致；相关报道不能冒充此原文')
            if info.get('read_status') not in ('Read', 'Partial'):
                raise ValueError('必须先登记已读取或部分读取的原始资料')
        elif data['information_id'] is not None:
            raise ValueError('非关联状态不指定原始资料')
        if old:
            if old['payload'] != encode(data):
                raise ValueError('处理ID已存在且内容不同')
            return False
        latest = self.db.execute('SELECT resolution_id,known_at FROM discovery_resolutions '
            'WHERE lead_id=? ORDER BY known_at DESC,rowid DESC LIMIT 1', (data['lead_id'],)).fetchone()
        if latest and latest['known_at'] > data['known_at']:
            raise ValueError('不能在较新处理之前倒插处理记录')
        if data['prior_resolution_id'] != (latest['resolution_id'] if latest else None):
            raise ValueError('前次处理已过时，请读取最新线索')
        return self.engine._insert('discovery_resolutions', 'resolution_id', data['resolution_id'], data,
            {k: data[k] for k in ('batch_id', 'lead_id', 'known_at', 'information_id')})

    def report(self, batch_id, as_of=None):
        at = utc(as_of or now())
        self.collection._batch(batch_id, at)
        leads = self.collection._records('discovery_leads', batch_id, at)
        history = self.collection._records('discovery_resolutions', batch_id, at)
        latest = {r['lead_id']: r for r in history}
        counts = dict.fromkeys(STATUSES, 0)
        counts['PartialRead'] = 0
        for lead in leads:
            resolution = latest.get(lead['lead_id'])
            lead['resolution'] = resolution
            lead['status'] = resolution['status'] if resolution else 'Pending'
            counts[lead['status']] += 1
            lead['read_status'] = None
            if lead['status'] == 'Linked':
                info = self.collection._information(resolution['information_id'], at)
                lead['read_status'] = info['read_status']
                counts['PartialRead'] += info['read_status'] == 'Partial'
        return {'as_of': at, 'leads': leads, 'history': history, 'counts': counts,
                'unresolved': counts['Pending'] + counts['Blocked'] + counts['PartialRead'],
                'note': '标题/日期线索未核实；只展示已登记发现，数量不代表全网覆盖。关联原文不等于通过初筛或形成方向。'}

    def apply_pack(self, package):
        reject_extra(package, {'pack_id', 'leads', 'resolutions'})
        text_required(package, ('pack_id',))
        for key in ('leads', 'resolutions'):
            if not isinstance(package.get(key), list):
                raise ValueError(key + '需要列表')
        old = self.db.execute('SELECT payload FROM discovery_runs WHERE pack_id=?', (package['pack_id'],)).fetchone()
        if old:
            previous = json.loads(old['payload'])
            if encode(previous['submitted_package']) != encode(package):
                raise ValueError('线索包已存在且内容不同；修订使用新编号')
            return {'inserted': False, 'known_at': previous['known_at']}
        stamp = now()
        p = deepcopy(package)
        with self.engine.atomic():
            self.engine._insert('discovery_runs', 'pack_id', p['pack_id'],
                {'submitted_package': package, 'known_at': stamp}, {'known_at': stamp})
            for key, operation in (('leads', self.add_lead), ('resolutions', self.resolve)):
                for record in p[key]:
                    if 'known_at' in record:
                        raise ValueError('线索包不得指定known_at；由实际导入时刻生成')
                    operation({**record, 'known_at': stamp})
        return {'inserted': True, 'known_at': stamp,
                'added': {key: len(p[key]) for key in ('leads', 'resolutions')}}
