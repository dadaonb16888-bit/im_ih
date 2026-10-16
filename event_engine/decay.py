"""Continuous natural-day decay; no trading calendar or future interpolation."""
import math
from datetime import datetime, timezone

DECAY_PERIODS = {'Fast': 1.0, 'Swing': 5.0, 'Trend': 20.0}


def timestamp(value):
    if not isinstance(value, str) or 'T' not in value:
        raise ValueError('衰减需要含时区的完整时间')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('衰减时间必须含时区')
    return stamp.astimezone(timezone.utc)


def freshness(event_time, as_of, horizon, decay_period=None):
    if horizon not in DECAY_PERIODS:
        raise ValueError('衰减Horizon无效')
    period = DECAY_PERIODS[horizon] if decay_period is None else decay_period
    if type(period) not in (int, float) or not math.isfinite(period) or period <= 0:
        raise ValueError('decay_period必须为正有限天数')
    age = (timestamp(as_of) - timestamp(event_time)).total_seconds() / 86400
    return 0.0 if age < 0 else math.exp(-age / period)
