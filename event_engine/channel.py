"""Channel priors, not keyword classification or verified event conclusions."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ChannelImpact:
    im_impact: str
    ih_impact: str
    bias: str
    assumption: str


CHANNEL_MAPPING = {
    'TECH_GROWTH': ChannelImpact('positive', 'neutral', 'Strong IM', '科技增长冲击，IM相对暴露更高'),
    'DIRECT_SMALLCAP_LIQUIDITY': ChannelImpact('negative', 'neutral', 'Strong IH', '小盘流动性危机/去杠杆；不是小盘定向注资'),
    'DIRECT_LARGECAP': ChannelImpact('neutral', 'positive', 'Strong IH', '大盘直接受益'),
    'MARKET_LIQUIDITY': ChannelImpact('positive', 'positive', 'IM', '广谱宽松、风险弹性扩散'),
    'CREDIT_LARGECAP': ChannelImpact('neutral', 'positive', 'IH', '大型金融信用修复'),
    'REGULATION_QUALITY': ChannelImpact('negative', 'positive', 'IH', '质量约束对小盘负担更大'),
    'RISK_APPETITE': ChannelImpact('positive', 'positive', 'IM', '风险偏好改善'),
    'RISK_OFF': ChannelImpact('negative', 'negative', 'Strong IH', '高风险风格相对承压'),
    'MARKET_STABILIZATION': ChannelImpact('neutral', 'positive', 'IH', '稳定资金主要支持权重'),
    'POSITIONING': ChannelImpact('unknown', 'unknown', 'Neutral', '仓位变化没有固定方向'),
}
CHANNELS = set(CHANNEL_MAPPING)
_UNSET = object()


def channel_impact(channel):
    if channel not in CHANNEL_MAPPING:
        raise ValueError('未知Channel: ' + str(channel))
    return asdict(CHANNEL_MAPPING[channel])


def resolve_bias(channels, explicit_bias=_UNSET):
    """Explicit null stays unknown. Opposite priors require evidence to resolve."""
    if explicit_bias is not _UNSET:
        if explicit_bias not in (None, 'Strong IM', 'IM', 'Neutral', 'IH', 'Strong IH'):
            raise ValueError('Bias无效')
        return explicit_bias
    priors = [channel_impact(c)['bias'] for c in channels or []]
    nonneutral = [b for b in priors if b != 'Neutral']
    if not nonneutral:
        return 'Neutral' if priors else None
    signs = {1 if 'IM' in b else -1 for b in nonneutral}
    return nonneutral[0] if len(signs) == 1 else None


def affected_style(bias):
    return None if bias is None else 'IM' if 'IM' in bias else 'IH' if 'IH' in bias else 'Neutral'
