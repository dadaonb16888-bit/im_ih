"""Small follow-up notes on a prior Watch screening, not a news reader/model."""
import json
from .engine import utc
from .collection import normalize_url


def validate_follow_up(note, raw, result, latest, engine, at):
    if note is None:
        return
    fields = {'prior_screening_id', 'group_id', 'priority', 'question', 'evidence_source_ids',
              'finding', 'next_trigger', 'outcome'}
    if not isinstance(note, dict) or set(note) != fields:
        raise ValueError('短核验字段不完整')
    for key in ('prior_screening_id', 'group_id', 'question', 'finding', 'next_trigger'):
        value = note[key]
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 240:
            raise ValueError('短核验仅保存1至240字短字段')
    if note['priority'] not in ('High', 'Normal', 'Low'):
        raise ValueError('核验优先级无效；不是交易评分')
    prior = latest.get(raw['information_id'])
    if not prior or prior['decision'] != 'Watch' or prior['screening_id'] != note['prior_screening_id']:
        raise ValueError('待核输入已变化或不再Watch，请读取最新筛选')
    ids = note['evidence_source_ids']
    if (not isinstance(ids, list) or any(not isinstance(i, str) or not i.strip() for i in ids)
            or len(ids) != len(set(ids)) or len(ids) > 3):
        raise ValueError('每主题短核验最多3个来源，引用不可重复')
    readable = False
    for iid in ids:
        row = engine.db.execute('SELECT payload FROM information_inbox WHERE information_id=?', (iid,)).fetchone()
        if not row:
            raise ValueError('短核验引用不存在')
        source = json.loads(row['payload'])
        if any(source.get(k) and utc(source[k]) > at for k in ('observed_at', 'recorded_at', 'known_at')):
            raise ValueError('短核验不能引用未来资料')
        if source.get('read_status') not in ('Read', 'Partial', 'Unavailable'):
            raise ValueError('短核验引用必须有读取状态')
        if not normalize_url(source.get('url')):
            raise ValueError('短核验来源需可追溯地址')
        readable |= source['read_status'] in ('Read', 'Partial')
    outcome = note['outcome']
    if outcome not in ('WaitEvidence', 'Archive', 'Rescreen'):
        raise ValueError('短核验结果无效')
    if outcome == 'WaitEvidence' and result['decision'] != 'Watch':
        raise ValueError('等待新证据仍须Watch')
    if outcome == 'Archive' and result['decision'] != 'Background':
        raise ValueError('归档须由初筛得出Background')
    if outcome in ('Archive', 'Rescreen') and not readable:
        raise ValueError('归档或重筛须有可读取证据，未知不能直接判低价值')


def validate_group_budgets(screenings):
    groups = {}
    all_sources = set()
    for row in screenings:
        note = row.get('follow_up')
        if note:
            group = groups.setdefault(note['group_id'], set())
            group.update(note['evidence_source_ids'])
            all_sources.update(note['evidence_source_ids'])
            if len(group) > 3:
                raise ValueError('同主题多条消息共享最多3个核验来源')
    if len(all_sources) > 12:
        raise ValueError('一批短核验最多12个来源；不要扩大成全量深查')
