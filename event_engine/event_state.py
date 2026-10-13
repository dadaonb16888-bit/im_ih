"""Pricing transitions from explicit observations, never inferred from news score."""


def transition_state(acceptance=None, observations=None, previous=None):
    observations = observations or {}
    if not isinstance(observations, dict) or set(observations) - {'priced_in', 'impact_weakening'}:
        raise ValueError('状态观察仅支持priced_in/impact_weakening')
    if any(type(value) is not bool for value in observations.values()):
        raise ValueError('状态观察必须为布尔值')
    if observations.get('impact_weakening') or acceptance in ('Fading', 'Rejected'):
        return 'Reversing'
    if observations.get('priced_in'):
        return 'Crowded'
    if acceptance == 'Confirmed':
        if previous == 'Crowded' and observations.get('priced_in') is not False:
            return 'Crowded'
        return 'Diffusing'
    if acceptance == 'Unconfirmed':
        return previous or 'Fresh'
    return previous
