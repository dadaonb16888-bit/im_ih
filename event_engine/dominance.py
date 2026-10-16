"""Numerical Event Pool ranking, independent of timing and execution."""
import math
from .decay import timestamp
from .scoring import score_event


def rank_events(events, as_of, horizon=None):
    at = timestamp(as_of)
    eligible, excluded = [], []
    for event in events:
        reasons = []
        if event.get('scope', 'Current') == 'Historical':
            reasons.append('historical_scope')
        if horizon and event.get('horizon') != horizon:
            continue
        for field in ('known_at', 'effective_at', 'event_time', 'first_tradable_time'):
            if event.get(field) and timestamp(event[field]) > at:
                reasons.append('future_' + field)
        if event.get('status') == 'Closed' or event.get('causal_status') == 'Closed':
            reasons.append('invalidated')
        if event.get('reviewed') is not True:
            reasons.append('causal_review_missing')
        if event.get('independent_cause') is not True or event.get('relative_pricing') is not True:
            reasons.append('relative_causality_missing')
        if event.get('information_gain') not in ('Medium', 'High'):
            reasons.append('information_gain_missing')
        if not event.get('first_tradable_time') or not event.get('invalidation'):
            reasons.append('time_or_invalidation_missing')
        if event.get('bias') in (None, 'Neutral'):
            reasons.append('no_directional_bias')
        result = score_event(event, as_of)
        if result['score'] is None:
            reasons.extend(result['score_gaps'])
        elif result['score'] <= 0:
            reasons.append('zero_score')
        if reasons:
            excluded.append({'event_id': event['event_id'], 'reasons': reasons})
        else:
            eligible.append({**event, **result})
    eligible.sort(key=lambda e: (-e['score'], e['event_id']))
    return eligible, excluded


def dominant_event(events, as_of, horizon=None):
    ranked, excluded = rank_events(events, as_of, horizon)
    top = ranked[0]['score'] if ranked else None
    leaders = [e for e in ranked if math.isclose(e['score'], top, rel_tol=1e-9, abs_tol=1e-12)]
    directions = {1 if 'IM' in e['bias'] else -1 for e in leaders}
    conflict = len(directions) > 1
    chosen = leaders[0] if len(leaders) == 1 else None
    return {'dominant_event': chosen['event_id'] if chosen else None,
            'event_name': chosen['name'] if chosen else None,
            'score': chosen['score'] if chosen else None,
            'bias': chosen['bias'] if chosen else None,
            'confidence': chosen['confidence'] if chosen else None,
            'trade_permission': bool(chosen and chosen.get('qualification') == 'TRADEABLE'),
            'entry_allowed': False, 'permission_scope': 'Event Layer only; timing and execution required',
            'conflict': conflict, 'candidates': [e['event_id'] for e in leaders],
            'reason': 'highest_score' if chosen else 'equal_score_conflict' if conflict else 'equal_score_tie' if leaders else 'no_eligible_alpha',
            'ranking': [{'event_id': e['event_id'], 'score': e['score'], 'bias': e['bias'],
                         'confidence': e['confidence'], 'qualification': e.get('qualification')} for e in ranked],
            'excluded': excluded, 'as_of': as_of}
