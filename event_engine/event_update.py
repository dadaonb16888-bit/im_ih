"""Auditable changes at one timestamp; low-gain repeats never reset decay."""
from .scoring import score_event


def update_delta(before, after, as_of):
    old = score_event(before, as_of)['score']
    new = score_event(after, as_of)['score']
    return {'bias_change': {'from': before.get('bias'), 'to': after.get('bias'),
                           'changed': before.get('bias') != after.get('bias')},
            'channel_change': {'from': before.get('channels', []), 'to': after.get('channels', []),
                              'changed': before.get('channels', []) != after.get('channels', [])},
            'score_change': None if old is None or new is None else new - old,
            'score_before': old, 'score_after': new, 'score_as_of': as_of}
