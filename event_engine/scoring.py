"""Event Alpha score: Impact × Confidence × Persistence × Freshness."""
from .confidence import bounded, confidence_score
from .decay import DECAY_PERIODS, freshness, timestamp

PERSISTENCE_SCORES = {'Fast': 0.4, 'Swing': 0.7, 'Trend': 1.0}
MODEL_VERSION = 'event-alpha-v1'


def score_event(event, as_of):
    timestamp(as_of)
    impact = bounded(event.get('impact_score'), 'impact_score', 5)
    confidence = confidence_score(event.get('confidence_score'), event.get('source_reliability'))
    horizon = event.get('horizon')
    persistence = bounded(event.get('persistence_score'), 'persistence_score')
    if persistence is None:
        persistence = PERSISTENCE_SCORES.get(horizon)
    gaps = []
    for key, value in [('impact_score', impact), ('confidence_score/source_reliability', confidence),
                       ('horizon', horizon if horizon in DECAY_PERIODS else None),
                       ('event_time', event.get('event_time')),
                       ('source', event.get('source') if isinstance(event.get('source'), str) and event['source'].strip() else None)]:
        if value is None or value == '' or value == []:
            gaps.append(key)
    fresh = None
    if horizon in DECAY_PERIODS and event.get('event_time'):
        fresh = freshness(event['event_time'], as_of, horizon)
    strength_gaps = [g for g in gaps if g != 'event_time']
    strength = None if strength_gaps else impact * confidence * persistence
    score = None if strength is None or fresh is None else strength * fresh
    return {'score': score, 'event_strength': strength, 'impact': impact, 'confidence': confidence,
            'persistence': persistence, 'freshness': fresh, 'score_gaps': gaps,
            'decay_period_days': DECAY_PERIODS.get(horizon), 'model_version': MODEL_VERSION, 'score_as_of': as_of}
