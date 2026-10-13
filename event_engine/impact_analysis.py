"""Evidence tables for policy change and beneficiary hypotheses, not extra factors."""
from datetime import date, timedelta, timezone
from .decay import timestamp

VERSION = 'policy-paths-v1'
CHANGE_TYPES = {'NewMechanism', 'Strengthened', 'ImplementationDetail', 'Reaffirmation', 'Unknown'}
STAGES = {'Intent', 'Draft', 'Effective', 'Unknown'}


def validate_impact_analysis(assessment, sources, checks, as_of):
    analysis = assessment.get('impact_analysis')
    if analysis is None:
        return
    if not isinstance(analysis, dict) or set(analysis) != {'version', 'policy_deltas', 'beneficiary_paths', 'conclusion', 'limits'}:
        raise ValueError('impact_analysis结构不完整')
    if analysis['version'] != VERSION:
        raise ValueError('未知影响分析版本')
    if not isinstance(analysis['conclusion'], str) or not analysis['conclusion'].strip():
        raise ValueError('影响分析需Codex结论')
    if not isinstance(analysis['limits'], list) or any(not isinstance(s, str) or not s.strip() for s in analysis['limits']):
        raise ValueError('影响分析limits需文字列表')

    def text(row, fields):
        if any(not isinstance(row.get(k), str) or not row[k].strip() for k in fields):
            raise ValueError('影响表格缺解释字段')

    def refs(ids, required=False):
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
            raise ValueError('影响表格引用需不重复编号列表')
        if required and not ids:
            raise ValueError('已知判断必须有对应证据')
        if any(i not in sources or checks.get(i) not in ('Read', 'Partial') for i in ids):
            raise ValueError('影响表格引用须属于本次已读取来源')

    deltas = analysis['policy_deltas']
    paths = analysis['beneficiary_paths']
    if not isinstance(deltas, list) or not deltas or not isinstance(paths, list) or not paths:
        raise ValueError('影响分析需政策对照与受益路径')
    identifiers = set()
    for row in deltas:
        allowed = {'item_id', 'topic', 'new_fact', 'baseline', 'new_source_ids', 'baseline_source_ids',
                   'baseline_kind', 'change_type', 'stage', 'magnitude', 'reason', 'limits'}
        if not isinstance(row, dict) or set(row) != allowed:
            raise ValueError('政策对照字段不完整')
        text(row, ('item_id', 'topic', 'new_fact', 'baseline', 'reason', 'limits'))
        if row['item_id'] in identifiers:
            raise ValueError('政策条目编号重复')
        identifiers.add(row['item_id'])
        if row['change_type'] not in CHANGE_TYPES or row['stage'] not in STAGES:
            raise ValueError('政策变化类型或实施状态无效')
        if row['baseline_kind'] not in ('EarlierSource', 'IssuerComparison', 'NotFound'):
            raise ValueError('政策基线类型无效')
        refs(row['new_source_ids'], True)
        refs(row['baseline_source_ids'], row['change_type'] != 'Unknown')
        if row['baseline_kind'] == 'NotFound' and (row['change_type'] != 'Unknown' or row['baseline_source_ids']):
            raise ValueError('未找到基线不能声称已知增量')
        if row['baseline_kind'] == 'EarlierSource':
            def public_date(source):
                value = source.get('published_at') or source.get('published_date')
                if not isinstance(value, str):
                    return None
                # Date-only sources cannot establish ordering within the same day.
                return date.fromisoformat(value[:10])
            new_times = [public_date(sources[i]) for i in row['new_source_ids']]
            for iid in row['baseline_source_ids']:
                value = public_date(sources[iid])
                if not value or not any(t and value < t for t in new_times):
                    raise ValueError('EarlierSource必须有早于新信息的公开日期')
        if row['magnitude'] is not None and (not isinstance(row['magnitude'], str) or not row['magnitude'].strip()):
            raise ValueError('政策力度须明确文字或null')
    identifiers = set()
    for row in paths:
        allowed = {'path_id', 'beneficiary', 'style', 'benefit', 'offsets', 'effect', 'effect_status',
                   'exposure_type', 'exposure_as_of', 'source_ids', 'limits'}
        if not isinstance(row, dict) or set(row) != allowed:
            raise ValueError('企业受益路径字段不完整')
        text(row, ('path_id', 'beneficiary', 'benefit', 'offsets', 'limits'))
        if row['path_id'] in identifiers:
            raise ValueError('受益路径编号重复')
        identifiers.add(row['path_id'])
        if row['style'] not in ('IM', 'IH', 'Both', 'Unknown') or row['effect'] not in ('Positive', 'Negative', 'Mixed', 'Unknown'):
            raise ValueError('受益风格或预期净效应无效')
        if row['effect_status'] not in ('Hypothesis', 'VerifiedMechanism'):
            raise ValueError('受益效应需区分研究推断与已核对机制')
        if row['exposure_type'] not in ('Business', 'SectorProxy', 'PortfolioDisclosure', 'Unknown'):
            raise ValueError('相对暴露依据无效')
        refs(row['source_ids'], True)
        if row['exposure_type'] == 'SectorProxy' and row['effect_status'] == 'VerifiedMechanism':
            raise ValueError('行业代理不能确认企业净受益机制')
        if row['exposure_as_of'] is not None:
            observed = date.fromisoformat(row['exposure_as_of'])
            if observed > timestamp(as_of).astimezone(timezone(timedelta(hours=8))).date():
                raise ValueError('不能使用未来暴露数据')
        if row['exposure_type'] != 'Unknown' and row['exposure_as_of'] is None:
            raise ValueError('业务/行业/披露组合需注明观察或统计日期')
