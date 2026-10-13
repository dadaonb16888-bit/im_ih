"""Incremental Event field contract and as-of Alpha projection."""
from .channel import affected_style, channel_impact, resolve_bias
from .confidence import bounded, reliability_score
from .scoring import score_event

ALPHA_FIELDS = {'source', 'source_reliability', 'impact_score', 'confidence_score',
                'persistence_score', 'event_strength', 'affected_style', 'status'}
ALIASES = {'event_name', 'channel'}


def normalize_event(data):
    result = dict(data)
    if 'event_name' in result:
        if 'name' in result and result['name'] != result['event_name']:
            raise ValueError('event_name与name不能冲突')
        result['name'] = result.pop('event_name')
    if 'channel' in result:
        ch = result.pop('channel')
        if ch is not None:
            channel_impact(ch)
        channels = [] if ch is None else [ch]
        if 'channels' in result and result['channels'] != channels:
            raise ValueError('channel与channels不能冲突')
        result['channels'] = channels
        if 'bias' not in result:
            result['bias'] = resolve_bias(channels)
    return result


def validate_alpha(data):
    for key, maximum in [('impact_score', 5), ('confidence_score', 1), ('persistence_score', 1), ('event_strength', 5)]:
        if key in data:
            bounded(data[key], key, maximum)
    if 'source_reliability' in data:
        reliability_score(data['source_reliability'])
    if data.get('source') is not None and (not isinstance(data['source'], str) or not data['source'].strip()):
        raise ValueError('source需要非空来源描述或URL')
    if data.get('affected_style') not in (None, 'IM', 'IH', 'Neutral'):
        raise ValueError('affected_style无效')
    if data.get('status') not in (None, 'Draft', 'Active', 'Closed'):
        raise ValueError('status须Draft/Active/Closed')


def project_event(event, as_of):
    computed = score_event(event, as_of)
    expected_style = affected_style(event.get('bias'))
    for field in ALPHA_FIELDS:
        event.setdefault(field, None)
    event['event_name'] = event['name']
    event['channel'] = (event.get('channels') or [None])[0]
    event['channel_default'] = channel_impact(event['channel']) if event['channel'] else None
    event['affected_style'] = expected_style
    event['status'] = 'Closed' if event['causal_status'] == 'Closed' else 'Active' if event.get('reviewed') else 'Draft'
    event['event_strength'] = computed['event_strength']
    event['alpha_state'] = event.get('pricing_state') or ('Fresh' if computed['score'] is not None and event['status'] == 'Active' else None)
    event['alpha'] = computed
    event['score'] = computed['score']
    return event
