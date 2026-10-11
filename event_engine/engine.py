"""Append-only IM/IH causal event ledger. No price-to-direction inference."""
import json
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = {'TECH_GROWTH', 'DIRECT_SMALLCAP_LIQUIDITY', 'DIRECT_LARGECAP',
            'MARKET_LIQUIDITY', 'CREDIT_LARGECAP', 'REGULATION_QUALITY',
            'RISK_APPETITE', 'RISK_OFF', 'MARKET_STABILIZATION', 'POSITIONING'}
HORIZONS = {'Fast', 'Swing', 'Trend'}
STYLE = {'Strong IM': 2, 'IM': 1, 'Neutral': 0, 'IH': -1, 'Strong IH': -2}
GAIN = {'Low': 1, 'Medium': 2, 'High': 3}
PRICING = {'Fresh', 'Diffusing', 'Crowded', 'Reversing'}
ACCEPTANCE = {'Unconfirmed', 'Confirmed', 'Delayed', 'Fading', 'Rejected'}
# Research ordering, configurable later after validation; not an alpha score.
ACCEPTANCE_RANK = {'Confirmed': 4, 'Delayed': 3, 'Unconfirmed': 2, 'Fading': 1}
CATEGORIES = {'TECH', 'POLICY_GROWTH', 'MONETARY', 'REGULATION', 'FUND_FLOW',
              'SMALLCAP_LIQUIDITY', 'RISK_OFF', 'RISK_ON', 'VALUE_DIVIDEND',
              'BROAD_STIMULUS', 'SEASONAL', 'POSITIONING', 'EARNINGS', 'EXTERNAL_MACRO'}
CAUSAL_FIELDS = {'bias', 'channels', 'horizon', 'directness', 'independent_cause',
                 'relative_pricing', 'invalidation', 'first_tradable_time',
                 'event_time', 'reviewed'}


def utc(value):
    """Require a full, timezone-aware timestamp. Date-only annotations stay drafts."""
    if not isinstance(value, str) or 'T' not in value:
        raise ValueError('需要含时区的完整时间；日期不能推定为零点')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('时间必须含时区')
    return dt.astimezone(timezone.utc).isoformat(timespec='microseconds')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def reject_extra(data, allowed):
    extra = set(data) - allowed
    if extra:
        raise ValueError('不允许的字段: ' + ', '.join(sorted(extra)))


def validate_causal(data):
    if data.get('bias') is not None and data['bias'] not in STYLE:
        raise ValueError('未知Bias；未确定请用null，不能用Neutral代替')
    if data.get('horizon') is not None and data['horizon'] not in HORIZONS:
        raise ValueError('Horizon必须为Fast/Swing/Trend')
    if 'channels' in data and data['channels'] is not None:
        ch = data['channels']
        if not isinstance(ch, list) or len(ch) != len(set(ch)) or set(ch) - CHANNELS:
            raise ValueError('Channel列表无效；第一个为主渠道')
    if data.get('directness') is not None:
        if type(data['directness']) is not int or data['directness'] not in (1, 2, 3):
            raise ValueError('Directness人工标注1/2/3，越高越直接')
    for field in ('independent_cause', 'relative_pricing', 'reviewed'):
        if field in data and data[field] is not None and type(data[field]) is not bool:
            raise ValueError(field + '必须为布尔值或null')
    for field in ('event_time', 'first_tradable_time'):
        if data.get(field) is not None:
            data[field] = utc(data[field])


class EventEngine:
    def __init__(self, database=ROOT / 'database' / 'events.sqlite3'):
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self._atomic_depth = 0
        self.db.executescript((ROOT / 'database' / 'schema.sql').read_text(encoding='utf-8'))
        for table in ('information_inbox', 'events', 'event_updates', 'state_updates',
                      'event_information', 'legacy_audit', 'research_notes'):
            for action in ('UPDATE', 'DELETE'):
                self.db.execute(f'''CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action}
                  BEFORE {action} ON {table} BEGIN
                  SELECT RAISE(ABORT, 'append-only ledger'); END''')
        self.db.commit()

    def close(self):
        self.db.close()

    @contextmanager
    def atomic(self):
        """Use a savepoint so bulk imports succeed or roll back as one unit."""
        name = 'event_batch_' + str(self._atomic_depth)
        self.db.execute('SAVEPOINT ' + name)
        self._atomic_depth += 1
        try:
            yield
            self.db.execute('RELEASE SAVEPOINT ' + name)
        except Exception:
            self.db.execute('ROLLBACK TO SAVEPOINT ' + name)
            self.db.execute('RELEASE SAVEPOINT ' + name)
            raise
        finally:
            self._atomic_depth -= 1

    def _insert(self, table, key, identifier, payload, extra=None, links=None):
        """Same ID + same content is idempotent; changed content is never overwritten."""
        old = self.db.execute(f'SELECT payload FROM {table} WHERE {key}=?', (identifier,)).fetchone()
        text = encode(payload)
        if old:
            if old['payload'] != text:
                raise ValueError(f'{identifier}已存在且内容不同；请追加新记录')
            return False
        fields = {key: identifier, **(extra or {}), 'payload': text}
        names = ','.join(fields)
        with nullcontext() if self._atomic_depth else self.db:
            self.db.execute(f'INSERT INTO {table} ({names}) VALUES ({",".join("?" for _ in fields)})',
                            tuple(fields.values()))
            for event_id, information_id in links or []:
                self.db.execute('INSERT OR IGNORE INTO event_information VALUES (?,?)',
                                (event_id, information_id))
        return True

    def add_information(self, data):
        if not data.get('information_id') or not data.get('title'):
            raise ValueError('原始信息需要information_id/title')
        return self._insert('information_inbox', 'information_id', data['information_id'], data)

    def create_event(self, data):
        data = dict(data)
        reject_extra(data, {'event_id', 'name', 'detection_mode', 'category', 'known_at',
                            'initial_bias', 'notes', 'legacy', 'scope', *CAUSAL_FIELDS})
        if not data.get('event_id') or not data.get('name'):
            raise ValueError('事件需要event_id/name')
        if data.get('detection_mode') not in ('News', 'MarketState'):
            raise ValueError('DetectionMode必须为News或MarketState')
        if data.get('category') is not None and data['category'] not in CATEGORIES:
            raise ValueError('Category无效')
        if data.get('scope', 'Current') not in ('Current', 'Historical'):
            raise ValueError('scope必须为Current/Historical')
        # Parent creation is a draft; initial causal assessment belongs in an update.
        if data.get('reviewed'):
            raise ValueError('创建后用Event Update提交初始因果审核')
        data['known_at'] = utc(data['known_at'])
        if 'initial_bias' in data:
            if data['initial_bias'] is not None and data['initial_bias'] not in STYLE:
                raise ValueError('Initial Bias无效')
        if data.get('bias') is not None and data.get('initial_bias') is not None and data['bias'] != data['initial_bias']:
            raise ValueError('创建时当前与初始Bias不能冲突；方向演化须提交Update')
        data.setdefault('initial_bias', data.get('bias'))
        validate_causal(data)
        self._validate_time_order(data)
        return self._insert('events', 'event_id', data['event_id'], data, {'known_at': data['known_at']})

    @staticmethod
    def _validate_time_order(data):
        if data.get('event_time') and data.get('first_tradable_time'):
            if data['first_tradable_time'] < data['event_time']:
                raise ValueError('FirstTradableTime不能早于公开/识别时间')

    def link_information(self, event_id, information_id):
        with nullcontext() if self._atomic_depth else self.db:
            self.db.execute('INSERT OR IGNORE INTO event_information VALUES (?,?)',
                            (event_id, information_id))

    def update_event(self, data):
        data = dict(data)
        reject_extra(data, {'update_id', 'event_id', 'effective_at', 'known_at', 'source_type',
                            'information_gain', 'facts', 'reason', 'evidence', 'information_ids',
                            'changes', 'invalidate'})
        for field in ('update_id', 'event_id', 'facts', 'reason', 'evidence'):
            if not data.get(field):
                raise ValueError('因果更新缺少' + field)
        if data.get('source_type') not in ('News', 'Policy', 'Announcement', 'MarketStructure'):
            raise ValueError('价格变化只能提交State Update，不能提交因果更新')
        if data.get('information_gain') not in GAIN:
            raise ValueError('InformationGain必须为High/Medium/Low')
        changes = dict(data.get('changes', {}))
        reject_extra(changes, CAUSAL_FIELDS)
        validate_causal(changes)
        if data['information_gain'] == 'Low' and (changes or data.get('invalidate')):
            raise ValueError('Low仅记录重复/低增量信息；因果修订需至少Medium及证据')
        if 'invalidate' in data and type(data['invalidate']) is not bool:
            raise ValueError('invalidate必须为布尔值')
        data['changes'] = changes
        data['known_at'] = utc(data['known_at'])
        data['effective_at'] = utc(data['effective_at'])
        snapshot = self.snapshot(data['event_id'], max(data['known_at'], data['effective_at']))
        if snapshot is None:
            raise ValueError('更新时父事件尚不可见或不存在')
        combined = {**snapshot, **changes}
        self._validate_time_order(combined)
        if combined.get('event_time') and data['effective_at'] < combined['event_time']:
            raise ValueError('因果更新不能早于事件公开/识别时间')
        if combined.get('reviewed'):
            required = ('event_time', 'channels', 'horizon', 'bias', 'directness', 'invalidation')
            if any(combined.get(k) is None or combined.get(k) == [] or combined.get(k) == '' for k in required):
                raise ValueError('审核通过需要完整时间、渠道、周期、方向、直接度及失效条件')
        for iid in data.get('information_ids', []):
            if not self.db.execute('SELECT 1 FROM information_inbox WHERE information_id=?', (iid,)).fetchone():
                raise ValueError('引用的原始信息不存在: ' + iid)
        return self._insert('event_updates', 'update_id', data['update_id'], data,
                            {k: data[k] for k in ('event_id', 'effective_at', 'known_at')},
                            [(data['event_id'], iid) for iid in data.get('information_ids', [])])

    def update_state(self, data):
        data = dict(data)
        reject_extra(data, {'state_id', 'event_id', 'effective_at', 'known_at',
                            'pricing_state', 'acceptance', 'evidence', 'method', 'notes', 'basis_epoch_id'})
        for field in ('state_id', 'event_id', 'evidence', 'method'):
            if not data.get(field):
                raise ValueError('市场状态缺少' + field)
        if data.get('pricing_state') is not None and data['pricing_state'] not in PRICING:
            raise ValueError('PricingState无效')
        if data.get('acceptance') is not None and data['acceptance'] not in ACCEPTANCE:
            raise ValueError('MarketAcceptance无效')
        if data.get('pricing_state') is None and data.get('acceptance') is None:
            raise ValueError('至少提供一种市场状态')
        data['known_at'] = utc(data['known_at'])
        data['effective_at'] = utc(data['effective_at'])
        snapshot = self.snapshot(data['event_id'], max(data['known_at'], data['effective_at']))
        if snapshot is None:
            raise ValueError('市场状态对应父事件不存在或尚不可见')
        if data.get('basis_epoch_id') and data['basis_epoch_id'] != snapshot['causal_epoch_id']:
            raise ValueError('市场状态关联的因果阶段已变化，请重新审核')
        data['basis_epoch_id'] = snapshot['causal_epoch_id']
        return self._insert('state_updates', 'state_id', data['state_id'], data,
                            {k: data[k] for k in ('event_id', 'effective_at', 'known_at')})

    def _visible(self, table, event_id, as_of):
        rows = self.db.execute(f'''SELECT payload FROM {table}
             WHERE event_id=? AND known_at<=? AND effective_at<=?
             ORDER BY MAX(known_at,effective_at), effective_at, known_at, rowid''',
                              (event_id, as_of, as_of)).fetchall()
        return [json.loads(r['payload']) for r in rows]

    def add_research_note(self, data):
        data = dict(data)
        reject_extra(data, {'note_id', 'event_id', 'kind', 'known_at', 'source', 'claim', 'review_status'})
        for field in ('note_id', 'event_id', 'source', 'claim'):
            if not data.get(field):
                raise ValueError('研究记录缺少' + field)
        if data.get('kind') not in ('Parent', 'EventUpdate', 'MarketState'):
            raise ValueError('研究记录类型无效')
        if data.get('review_status', 'Pending') != 'Pending':
            raise ValueError('来源标签不能直接成为已验证事件；请提交正式Update或State')
        data['review_status'] = 'Pending'
        data['known_at'] = utc(data['known_at'])
        return self._insert('research_notes', 'note_id', data['note_id'], data,
                            {k: data[k] for k in ('event_id', 'kind', 'known_at')})

    def history(self, event_id, as_of):
        as_of = utc(as_of)
        snapshot = self.snapshot(event_id, as_of)
        if snapshot is None:
            raise ValueError('事件不存在或尚不可见')
        notes = [json.loads(r['payload']) for r in self.db.execute(
            'SELECT payload FROM research_notes WHERE event_id=? AND known_at<=? ORDER BY known_at,rowid',
            (event_id, as_of))]
        return {'snapshot': snapshot, 'causal_updates': self._visible('event_updates', event_id, as_of),
                'market_states': self._visible('state_updates', event_id, as_of), 'research_notes': notes}

    def snapshot(self, event_id, as_of):
        as_of = utc(as_of)
        row = self.db.execute('SELECT payload FROM events WHERE event_id=? AND known_at<=?',
                              (event_id, as_of)).fetchone()
        if not row:
            return None
        event = json.loads(row['payload'])
        event.setdefault('bias', event.get('initial_bias'))
        event.setdefault('reviewed', False)
        event['initial_bias'] = event.get('initial_bias')
        event['information_gain'] = None
        event['causal_status'] = 'Active'
        epoch = event['known_at']
        event['causal_epoch_id'] = 'parent:' + event_id
        event['last_update_id'] = None
        event['last_meaningful_update_at'] = None
        for update in self._visible('event_updates', event_id, as_of):
            changes = update.get('changes', {})
            if any(k in changes and changes[k] != event.get(k) for k in ('bias', 'channels', 'horizon')):
                epoch = max(update['known_at'], update['effective_at'])
                event['causal_epoch_id'] = update['update_id']
            if event['initial_bias'] is None and changes.get('bias') is not None:
                event['initial_bias'] = changes['bias']
            event.update(changes)
            if update['information_gain'] != 'Low' or event['information_gain'] is None:
                event['information_gain'] = update['information_gain']
            if update['information_gain'] != 'Low':
                event['last_meaningful_update_at'] = max(update['known_at'], update['effective_at'])
            if update.get('invalidate'):
                event['causal_status'] = 'Closed'
            event['last_update_id'] = update['update_id']
        event['pricing_state'] = None
        event['acceptance'] = None
        event['last_state_id'] = None
        event['last_state_effective_at'] = None
        event['last_state_known_at'] = None
        for state in self._visible('state_updates', event_id, as_of):
            # Confirmation from before a rotation cannot confirm the new direction.
            if state['effective_at'] < epoch or (state.get('basis_epoch_id') and
                                                 state['basis_epoch_id'] != event['causal_epoch_id']):
                continue
            for key in ('pricing_state', 'acceptance'):
                if key in state:
                    event[key] = state[key]
            event['last_state_id'] = state['state_id']
            event['last_state_effective_at'] = state['effective_at']
            event['last_state_known_at'] = state['known_at']
        signal = STYLE.get(event.get('bias'))
        event['style_signal'] = signal
        event['D'] = None if signal is None else (1 if signal > 0 else -1 if signal < 0 else 0)
        event['as_of'] = as_of
        event['entry_allowed'] = False  # Technical timing and execution are outside this module.
        event['qualification'], event['blockers'] = self.qualify(event)
        return event

    @staticmethod
    def qualify(event):
        if event['causal_status'] == 'Closed':
            return 'INVALID', ['新的因果证据已明确失效；不是价格反向推定']
        if event.get('independent_cause') is False or event.get('relative_pricing') is False:
            return 'IGNORE', ['缺少独立因果或不影响IM/IH相对定价']
        if event.get('information_gain') == 'Low':
            return 'IGNORE', ['只有低增量信息']
        blockers = []
        for key, label in [('reviewed', '因果审核未完成'), ('channels', '传导渠道未确定'),
                           ('horizon', '作用周期未确定'), ('bias', '方向未确定'),
                           ('event_time', '公开/识别时间未核实'),
                           ('first_tradable_time', '最早可交易时间未核实'),
                           ('invalidation', '缺少失效条件'), ('directness', '直接度未标注')]:
            if event.get(key) is None or event.get(key) == [] or event.get(key) == '' or event.get(key) is False:
                blockers.append(label)
        if GAIN.get(event.get('information_gain'), 0) < 2:
            blockers.append('缺少至少Medium的信息增量审核')
        if event.get('independent_cause') is not True or event.get('relative_pricing') is not True:
            blockers.append('独立因果及相对定价影响尚未确认')
        if event.get('first_tradable_time') and event['first_tradable_time'] > event['as_of']:
            blockers.append('尚未到最早可交易时间')
        if blockers:
            return 'WATCH', blockers
        if event.get('bias') == 'Neutral':
            return 'IGNORE', ['审核后无明确相对方向']
        if event.get('pricing_state') in ('Crowded', 'Reversing'):
            return 'LATE', ['拥挤或反转阶段，暂停新开；原始方向保留']
        if event.get('acceptance') != 'Confirmed' or event.get('pricing_state') not in ('Fresh', 'Diffusing'):
            return 'WATCH', ['缺少当前方向的市场确认或可参与阶段']
        return 'TRADEABLE', []

    def report(self, as_of, include_historical=False):
        as_of = utc(as_of)
        events = [self.snapshot(r['event_id'], as_of) for r in
                  self.db.execute('SELECT event_id FROM events ORDER BY event_id')]
        events = [e for e in events if e is not None and
                  (include_historical or e.get('scope', 'Current') != 'Historical')]
        dominant = {}
        for label, horizon in [('Intraday', 'Fast'), ('Swing', 'Swing'), ('Trend', 'Trend')]:
            candidates = [e for e in events if e.get('scope', 'Current') != 'Historical' and
                          e.get('horizon') == horizon and e['qualification'] == 'TRADEABLE']
            rank = lambda e: (e['directness'], GAIN[e['information_gain']], ACCEPTANCE_RANK[e['acceptance']])
            best = max((rank(e) for e in candidates), default=None)
            leaders = [e for e in candidates if rank(e) == best]
            opposite = len({e['D'] for e in leaders}) > 1
            chosen = leaders[0] if len(leaders) == 1 else None
            dominant[label] = {'event_id': chosen['event_id'] if chosen else None,
                               'bias': chosen['bias'] if chosen else None,
                               'candidates': [e['event_id'] for e in leaders],
                               'conflict': opposite,
                               'reason': '唯一最高优先级事件' if chosen else
                               '同级方向冲突，待人工裁决' if opposite else
                               '同级多个事件，未强行选一' if leaders else '没有通过事件资格审核的候选',
                               'entry_allowed': False}
        return {'as_of': as_of, 'dominant': dominant, 'events': events,
                'scope': '事件资格与方向；不含进出场、回测及实盘指令'}
