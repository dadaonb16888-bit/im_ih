"""Read-only research work grouped by Parent, never a trading state."""
from .engine import utc


def research_queue(engine, information, as_of):
    # Local import avoids the AIResearch -> NewsScreening validation dependency.
    from .ai_research import AIResearch
    at = utc(as_of)
    research = AIResearch(engine)
    groups, association = {}, []
    for info in information:
        screening = info.get('screening')
        if not screening or not screening.get('deep_review_allowed'):
            continue
        ids = [eid for eid in info.get('event_ids', []) if engine.snapshot(eid, at) is not None]
        if len(ids) != 1:
            association.append({'information_id': info['information_id'], 'title': info['title'],
                                'event_ids': ids, 'reason': '尚未归并' if not ids else '多个Parent，需Codex核定归属'})
            continue
        group = groups.setdefault(ids[0], [])
        group.append(info)
    tasks = []
    for eid, items in sorted(groups.items()):
        parent = engine.snapshot(eid, at)
        cards = research.list_assessments(eid, at)
        card = cards[-1] if cards else None
        reason = '三轮通过后尚未完成本轮判读'
        complete = False
        if card:
            mode = 'HistoricalReview' if parent.get('scope') == 'Historical' else 'CurrentReview'
            if not {i['information_id'] for i in items}.issubset(card['source_ids']):
                reason = '有新的通过项尚未纳入最近判读'
            elif utc(card['known_at']) < max(utc(i['screening']['known_at']) for i in items):
                reason = '最近判读早于本轮初筛；需核对本轮输入'
            elif card.get('research_mode') != mode:
                reason = '事件研究范围已变化'
            else:
                try:
                    context = research.context(eid, card['source_ids'], as_of=at)
                    complete = context['input_digest'] == card['input_digest']
                except ValueError:
                    complete = False
                reason = '本轮通过项已合并判读' if complete else '事件或证据输入已变化；需重新判读'
        status = ('ReviewedWithGaps' if card.get('gaps') or card.get('decision') == 'InsufficientEvidence'
                  else 'Reviewed') if complete else 'NeedsReview'
        tasks.append({'event_id': eid, 'event_name': parent['name'], 'scope': parent.get('scope'),
            'information_ids': [i['information_id'] for i in items], 'source_count': len(items),
            'status': status, 'reason': reason,
            'assessment_id': card['assessment_id'] if complete else None,
            'reviewed_at': card['known_at'] if complete else None,
            'research_bias': card.get('bias') if complete else None,
            'decision': card.get('decision') if complete else None,
            'gaps': card.get('gaps', []) if complete else [],
            'next_action': card.get('next_action') if complete else None,
            'trade_permission': False, 'entry_allowed': False})
    tasks.sort(key=lambda t: (t['status'] != 'NeedsReview', t['event_id']))
    return {'as_of': at, 'tasks': tasks, 'needs_association': association,
        'counts': {s: sum(t['status'] == s for t in tasks) for s in ('NeedsReview', 'ReviewedWithGaps', 'Reviewed')},
        'research_only': True, 'trade_permission': False, 'entry_allowed': False,
        'note': '按Parent合并研究工作；已判读不等于方向或市场确认。旧关联表无建立时间，历史归属不能完整重建。'}
