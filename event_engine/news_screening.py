"""Three short Codex screening rounds before deep current-event research."""
import json
from .engine import encode, now, reject_extra, utc
from .collection import text_required

VERSION = 'news-screening-v1'
DECISIONS = ('DeepReview', 'Watch', 'Background', 'Unscreened')


def round_input(data, allowed, enums):
    if not isinstance(data, dict):
        raise ValueError('筛选轮次需要对象')
    reject_extra(data, {*allowed, 'reason'})
    reason = data.get('reason')
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 240:
        raise ValueError('每轮仅保存1至240字短理由')
    for field, choices in enums.items():
        if data.get(field) not in choices:
            raise ValueError('筛选字段无效：' + field)


def evaluate(rounds):
    if not isinstance(rounds, dict):
        raise ValueError('需要分轮初筛')
    reject_extra(rounds, {'round1', 'round2', 'round3'})
    history = []

    def stop(level, decision, reason):
        if any('round' + str(n) in rounds for n in range(level + 1, 4)):
            raise ValueError('前轮已停止，不应填写后轮深查内容')
        history.append({'round': level, 'result': decision, 'reason': reason})
        return {'decision': decision, 'stopped_at': level, 'rounds': history,
                'deep_review_allowed': decision == 'DeepReview', 'bias': None,
                'trade_permission': False, 'entry_allowed': False}

    r = rounds.get('round1')
    round_input(r, {'duplicate', 'time_relevance', 'source_quality'}, {
        'time_relevance': {'Current', 'Background', 'Upcoming', 'Unknown'},
        'source_quality': {'A', 'B', 'C', 'D', 'Unknown'}})
    if type(r.get('duplicate')) is not bool and r.get('duplicate') is not None:
        raise ValueError('重复状态须为布尔或未知')
    if r.get('duplicate') or r['time_relevance'] == 'Background':
        return stop(1, 'Background', r['reason'])
    if r['time_relevance'] == 'Upcoming' or r['source_quality'] in ('D', 'Unknown'):
        return stop(1, 'Watch', r['reason'])
    history.append({'round': 1, 'result': 'Pass', 'reason': r['reason']})
    if 'round2' not in rounds:
        return stop(2, 'Watch', '影响力初筛尚未完成；先保留短线索，不开展深查。')
    r2 = rounds['round2']
    round_input(r2, {'scope', 'potential', 'spillover'}, {
        'scope': {'Market', 'Style', 'Industry', 'Company', 'Local', 'Unknown'},
        'potential': {'High', 'Medium', 'Low', 'Unknown'},
        'spillover': {'Clear', 'Possible', 'None', 'Unknown'}})
    if r2['potential'] == 'Low' or (r2['scope'] in ('Company', 'Local') and r2['spillover'] == 'None'):
        return stop(2, 'Background', r2['reason'])
    if (r2['potential'] == 'Unknown' or r2['scope'] == 'Unknown' or
            r2['scope'] not in ('Market', 'Style') and r2['spillover'] != 'Clear'):
        return stop(2, 'Watch', r2['reason'])
    history.append({'round': 2, 'result': 'Pass', 'reason': r2['reason']})
    if 'round3' not in rounds:
        return stop(3, 'Watch', '新增程度和传导初筛尚未完成；不进入深查。')
    r3 = rounds['round3']
    round_input(r3, {'novelty', 'transmission', 'fact_support'}, {
        'novelty': {'New', 'Update', 'Repeat', 'Unknown'},
        'transmission': {'Clear', 'Possible', 'None', 'Unknown'},
        'fact_support': {'Supported', 'Unverified'}})
    if r3['novelty'] == 'Repeat' or r3['transmission'] == 'None':
        return stop(3, 'Background', r3['reason'])
    if (r3['novelty'] == 'Unknown' or r3['transmission'] != 'Clear' or
            r3['fact_support'] != 'Supported' or rounds['round1']['time_relevance'] == 'Unknown'):
        return stop(3, 'Watch', r3['reason'])
    return stop(3, 'DeepReview', r3['reason'])


class NewsScreening:
    def __init__(self, engine):
        self.engine, self.db = engine, engine.db

    def active(self, as_of):
        return self.db.execute('SELECT 1 FROM news_screening_runs WHERE known_at<=? LIMIT 1', (utc(as_of),)).fetchone() is not None

    def latest(self, as_of=None):
        at = utc(as_of or now())
        rows = self.db.execute('SELECT payload FROM information_screenings WHERE known_at<=? ORDER BY known_at,rowid', (at,))
        return {r['information_id']: r for r in (json.loads(row['payload']) for row in rows)}

    def history(self, information_id, as_of=None):
        return [json.loads(r['payload']) for r in self.db.execute(
            'SELECT payload FROM information_screenings WHERE information_id=? AND known_at<=? ORDER BY known_at,rowid',
            (information_id, utc(as_of or now())))]

    def report(self, as_of=None):
        at = utc(as_of or now())
        latest = self.latest(at)
        information = []
        for row in self.db.execute('SELECT payload FROM information_inbox ORDER BY information_id'):
            info = json.loads(row['payload'])
            if any(info.get(k) and utc(info[k]) > at for k in ('recorded_at', 'observed_at', 'known_at')):
                continue
            linked = [r[0] for r in self.db.execute('SELECT event_id FROM event_information WHERE information_id=?', (info['information_id'],))
                      if self.engine.snapshot(r[0], at) is not None]
            information.append({**info, 'screening': latest.get(info['information_id']), 'event_ids': linked})
        from .research_queue import research_queue
        return {'as_of': at, 'version': VERSION, 'gate_active': self.active(at), 'information': information,
                'research_queue': research_queue(self.engine, information, at),
                'counts': {d: sum((i['screening']['decision'] if i['screening'] else 'Unscreened') == d for i in information) for d in DECISIONS},
                'note': '初筛决定是否值得深查，不代表IM/IH方向；未筛选与待核不自动判无价值。'}

    def apply_pack(self, pack):
        reject_extra(pack, {'pack_id', 'actor', 'version', 'generated_at', 'screenings'})
        text_required(pack, ('pack_id', 'actor', 'version', 'generated_at'))
        if pack['actor'] != 'Codex' or pack['version'] != VERSION:
            raise ValueError('仅使用受信本地Codex初筛流程；JSON作者标签不是身份认证')
        at = now()
        if utc(pack['generated_at']) > at:
            raise ValueError('初筛包不能在未来生成')
        old = self.db.execute('SELECT payload FROM news_screening_runs WHERE pack_id=?', (pack['pack_id'],)).fetchone()
        if old:
            previous = json.loads(old['payload'])
            if encode(previous['submitted_pack']) != encode(pack):
                raise ValueError('初筛包内容变化；修订需要新编号')
            return {'inserted': False, 'known_at': previous['known_at'], 'pack_id': pack['pack_id']}
        if not isinstance(pack.get('screenings'), list) or not pack['screenings']:
            raise ValueError('需要至少一条初筛')
        with self.engine.atomic():
            self.engine._insert('news_screening_runs', 'pack_id', pack['pack_id'], {'submitted_pack': pack, 'known_at': at}, {'known_at': at})
            ids = []
            for raw in pack['screenings']:
                reject_extra(raw, {'screening_id', 'information_id', 'summary', 'input_rounds'})
                text_required(raw, ('screening_id', 'information_id', 'summary'))
                if len(raw['summary']) > 240:
                    raise ValueError('初筛只保存短摘要')
                source = self.db.execute('SELECT payload FROM information_inbox WHERE information_id=?', (raw['information_id'],)).fetchone()
                if not source:
                    raise ValueError('初筛引用的原始信息不存在')
                info = json.loads(source['payload'])
                if any(info.get(k) and utc(info[k]) > at for k in ('recorded_at', 'observed_at', 'known_at')):
                    raise ValueError('原始信息在此时尚不可知')
                result = evaluate(raw['input_rounds'])
                if result['deep_review_allowed'] and info.get('read_status') == 'Unavailable':
                    raise ValueError('未取得原文不能声称有事实支持并进入深查；先短核验')
                record = {**raw, **result, 'known_at': at, 'actor': 'Codex', 'version': VERSION}
                self.engine._insert('information_screenings', 'screening_id', raw['screening_id'], record,
                                    {'information_id': raw['information_id'], 'pack_id': pack['pack_id'], 'known_at': at})
                ids.append(raw['screening_id'])
        return {'inserted': True, 'known_at': at, 'pack_id': pack['pack_id'], 'screenings': ids}
