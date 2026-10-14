"""Descriptive ETF share evidence; never a style alpha or actual cash-flow model."""
from datetime import date, timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
from .engine import reject_extra, utc
from .decay import timestamp

UNITS = {'份': Decimal(1), '万份': Decimal(10000), '亿份': Decimal(100000000)}


def finite_float(value):
    out = float(value)
    if not isfinite(out):
        raise ValueError('计算结果超出有限输出范围')
    return out


def number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(name + '必须为有限数值')
    try:
        out = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(name + '必须为有限数值') from None
    if not out.is_finite() or out < 0 or positive and out == 0:
        raise ValueError(name + '必须为有效非负数或正数')
    return out


def public_source(row, as_of):
    if row.get('read_status') != 'Read':
        raise ValueError('计算需要实际读取原始数值；索引或部分读取不作数值输入')
    if not isinstance(row.get('source_id'), str) or not row['source_id'].strip():
        raise ValueError('需要证据编号')
    url = row.get('source_url')
    if not isinstance(url, str) or not url.startswith(('https://', 'http://')):
        raise ValueError('需要原始来源地址')
    if timestamp(utc(row.get('known_at'))) > timestamp(as_of):
        raise ValueError('证据在此时尚不可知')


def dated(value, as_of):
    try:
        result = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('统计日期须为YYYY-MM-DD') from None
    if result.isoformat() != value:
        raise ValueError('统计日期须为YYYY-MM-DD')
    if result > timestamp(as_of).astimezone(timezone(timedelta(hours=8))).date():
        raise ValueError('统计期不能来自未来')
    return result


def share_observation(row, as_of):
    reject_extra(row, {'fund_code', 'share_date', 'measure', 'value', 'unit',
                       'source_id', 'source_url', 'read_status', 'known_at'})
    code = row.get('fund_code')
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        raise ValueError('基金代码须为6位数字')
    if row.get('measure') != 'TotalShares' or row.get('unit') not in UNITS:
        raise ValueError('仅接受明确单位的总份额，不接受规模金额、申赎单位或上限')
    public_source(row, as_of)
    return dated(row.get('share_date'), as_of), number(row.get('value'), '总份额') * UNITS[row['unit']]


def compare_shares(previous, current, as_of, adjustment_review=None, nav=None):
    """Change in sampled products, with conditional NAV-based notional estimation.

    Adjustment evidence concerns splits/mergers/unit conversion, not price adjustments.
    Evidence labels are assertions supplied by the trusted researcher, not authenticity checks.
    """
    as_of = utc(as_of)
    before_date, before = share_observation(previous, as_of)
    after_date, after = share_observation(current, as_of)
    if previous['fund_code'] != current['fund_code'] or before_date >= after_date:
        raise ValueError('须为同一产品且期末晚于期初')
    result = {'fund_code': current['fund_code'], 'period_start': before_date.isoformat(),
              'period_end': after_date.isoformat(), 'as_of': as_of,
              'previous_total_shares': finite_float(before), 'current_total_shares': finite_float(after),
              'share_delta_unadjusted': finite_float(after - before),
              'share_change_pct_unadjusted': finite_float((after / before - 1) * 100) if before else None,
              'share_delta_adjusted': None, 'net_creation_notional_estimate': None,
              'adjustment_status': 'Unchecked', 'source_ids': [previous['source_id'], current['source_id']],
              'gaps': [], 'research_only': True, 'bias': None, 'trade_permission': False,
              'entry_allowed': False, 'note': '产品样本的份额变化；估算名义申赎价值不等于现金入金，不代表整个指数资金流。'}
    factor = None
    if adjustment_review is not None:
        reject_extra(adjustment_review, {'status', 'scale_factor', 'source_ids', 'reason', 'known_at'})
        status = adjustment_review.get('status')
        if status not in ('Clear', 'Adjusted', 'Unchecked'):
            raise ValueError('份额事项检查状态无效')
        if timestamp(utc(adjustment_review.get('known_at'))) > timestamp(as_of):
            raise ValueError('份额事项检查在此时尚不可知')
        ids = adjustment_review.get('source_ids')
        if not isinstance(ids, list) or any(not isinstance(i, str) or not i.strip() for i in ids):
            raise ValueError('份额事项检查需要证据编号列表')
        if not isinstance(adjustment_review.get('reason'), str) or not adjustment_review['reason'].strip():
            raise ValueError('份额事项检查需要范围及理由')
        if status in ('Clear', 'Adjusted'):
            if not ids:
                raise ValueError('已核份额事项必须有证据，不能默认为无拆分')
            factor = number(adjustment_review.get('scale_factor'), '期初份额折算因子', positive=True)
            if status == 'Clear' and factor != 1:
                raise ValueError('无份额事项的折算因子须为1')
            result['source_ids'].extend(ids)
        elif adjustment_review.get('scale_factor') is not None:
            raise ValueError('未核份额事项不能给折算因子')
        result['adjustment_status'] = status
    if factor is None:
        result['gaps'].append('份额拆分/合并等事项未核；不能把未调整变化认作净申赎')
    else:
        result['share_delta_adjusted'] = finite_float(after - before * factor)
    nav_value = None
    if nav is not None:
        reject_extra(nav, {'fund_code', 'nav_date', 'measure', 'value', 'currency',
                          'source_id', 'source_url', 'read_status', 'known_at'})
        public_source(nav, as_of)
        if (nav.get('fund_code') != current['fund_code'] or nav.get('measure') != 'UnitNAV'
                or nav.get('currency') != 'CNY' or dated(nav.get('nav_date'), as_of) != after_date):
            raise ValueError('净值须匹配产品及期末日期，且为人民币单位净值')
        nav_value = number(nav.get('value'), '单位净值', positive=True)
        result['source_ids'].append(nav['source_id'])
    if nav_value is None:
        result['gaps'].append('匹配期末日期的单位净值未核')
    if factor is not None and nav_value is not None:
        result['net_creation_notional_estimate'] = finite_float((after - before * factor) * nav_value)
    result['source_ids'] = list(dict.fromkeys(result['source_ids']))
    return result
