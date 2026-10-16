"""Uncalibrated source-quality priors and bounded numerical confidence."""
import math

SOURCE_RELIABILITY = {'A': 1.0, 'B': 0.85, 'C': 0.6, 'D': 0.3}


def bounded(value, field, maximum=1.0):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError(f'{field}需要0–{maximum:g}的有限数值')
    return float(value)


def reliability_score(value):
    if isinstance(value, str):
        if value not in SOURCE_RELIABILITY:
            raise ValueError('SourceReliability等级须A/B/C/D或0–1')
        return SOURCE_RELIABILITY[value]
    return bounded(value, 'source_reliability')


def confidence_score(judgment, reliability):
    """Quality caps confidence; unknown quality cannot imply certainty."""
    judgment = bounded(judgment, 'confidence_score')
    quality = reliability_score(reliability)
    if judgment is None or quality is None:
        return None
    return min(judgment, quality)
