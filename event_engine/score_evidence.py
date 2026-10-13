"""Auditable research scoring; reference publication is not global first release."""
from .decay import timestamp
from .scoring import score_event

RUBRIC_VERSION = 'score-evidence-v1'
COMPONENTS = {'source', 'source_reliability', 'impact_score', 'confidence_score', 'persistence_score'}


def validate_score_basis(assessment, sources, checks, as_of):
    basis = assessment.get('score_basis')
    if basis is None:
        return
    if not isinstance(basis, dict) or set(basis) != {'rubric_version', 'components', 'reference_time'}:
        raise ValueError('score_basis需要rubric_version/components/reference_time')
    if basis['rubric_version'] != RUBRIC_VERSION:
        raise ValueError('未知评分依据版本')
    components = basis['components']
    if not isinstance(components, dict) or set(components) != COMPONENTS:
        raise ValueError('每个评分组件必须分别说明依据')

    def item(value):
        if not isinstance(value, dict) or set(value) != {'value', 'reason', 'source_ids'}:
            raise ValueError('评分依据需要value/reason/source_ids')
        if not isinstance(value['reason'], str) or not value['reason'].strip():
            raise ValueError('评分理由不能为空')
        ids = value['source_ids']
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
            raise ValueError('评分引用须为不重复编号列表')
        if value['value'] is not None and not ids:
            raise ValueError('确定的评分组件需要证据引用')
        if any(i not in sources or checks.get(i) not in ('Read', 'Partial') for i in ids):
            raise ValueError('评分引用必须属于本次已读取证据')

    for key, value in components.items():
        item(value)
        if key not in assessment or type(value['value']) is not type(assessment[key]) or value['value'] != assessment[key]:
            raise ValueError('评分依据与实际组件不一致: ' + key)
    source = assessment.get('source')
    if source is not None:
        supported_urls = {url for i in components['source']['source_ids'] for url in
                          (sources[i].get('url'), sources[i].get('original_url')) if url}
        if source not in supported_urls:
            raise ValueError('评分来源需匹配引用的原文地址')
    if assessment['decision'] == 'InsufficientEvidence' and assessment.get('confidence_score') is not None:
        raise ValueError('方向未知时，不能用事实可信度替代方向数值置信度')
    reference = basis['reference_time']
    item(reference)
    if reference['value'] is not None:
        target = timestamp(reference['value'])
        if target > timestamp(as_of):
            raise ValueError('参考公开时间不能来自未来')
        matches = []
        for iid in reference['source_ids']:
            public = sources[iid].get('published_at')
            if isinstance(public, str) and 'T' in public:
                matches.append(timestamp(public) == target)
        if not any(matches):
            raise ValueError('参考时刻须匹配已核对的精确来源时间，日期不能补零点')


def research_preview(assessment, as_of):
    """Compute only when the assessment is visible, retaining unscored old cards."""
    if timestamp(assessment['known_at']) > timestamp(as_of):
        return None
    basis = assessment.get('score_basis')
    event = {key: assessment.get(key) for key in COMPONENTS | {'horizon'}}
    event['event_time'] = basis['reference_time']['value'] if basis else None
    result = score_event(event, as_of)
    if basis is None:
        result.update({'score': None, 'event_strength': None, 'score_gaps': ['score_basis_missing']})
    return {'assessment_id': assessment['assessment_id'], 'event_id': assessment['event_id'],
            'known_at': assessment['known_at'], 'bias': assessment.get('bias'),
            'decision': assessment['decision'], 'research_mode': assessment['research_mode'],
            'reference_time': event['event_time'], 'time_basis': 'SourcePublicationReference' if event['event_time'] else None,
            'score_basis': basis, **result, 'research_only': True, 'trade_permission': False,
            'entry_allowed': False, 'formal_projection': assessment.get('causal_projection'),
            'research_gaps': assessment.get('gaps', [])}
