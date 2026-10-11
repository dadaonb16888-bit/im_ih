"""Export reviewable outputs from the migrated ledger without guessing labels."""
import json
from collections import Counter
from pathlib import Path
from event_engine.engine import EventEngine, ROOT, now


def main():
    engine = EventEngine()
    try:
        report = engine.report(now())
        inbox = [json.loads(r['payload']) for r in engine.db.execute(
            'SELECT payload FROM information_inbox ORDER BY information_id')]
        references = {r['audit_id']: json.loads(r['payload']) for r in engine.db.execute(
            "SELECT audit_id,payload FROM legacy_audit WHERE audit_id LIKE 'reference:%'")}
        reviews = {r['information_id']: r for r in
                   references['reference:information_review_20261010.json']['content']}
        sources = references['reference:sources.json']['content']
        linked = {}
        for row in engine.db.execute('SELECT * FROM event_information ORDER BY information_id'):
            linked.setdefault(row['information_id'], []).append(row['event_id'])
        event_queue = []
        for e in report['events']:
            old = e.get('legacy', {})
            event_queue.append({'event_id': e['event_id'], 'name': e['name'],
                'category': e.get('category'), 'qualification': e['qualification'],
                'bias': e.get('bias'), 'channels': e.get('channels'), 'horizon': e.get('horizon'),
                'information_ids': old.get('information_ids', []),
                'source_facts_confidence': old.get('fact_confidence'),
                'legacy_research_hypothesis': old.get('research_hypothesis'),
                'im_case': old.get('im_case'), 'ih_countercase': old.get('ih_case'),
                'transmission_to_review': old.get('transmission_hypothesis'),
                'earliest_found_publication': old.get('earliest_verified_publication_at'),
                'global_first_publication_verified': False,
                'existing_gaps': old.get('gaps', []), 'engine_blockers': e['blockers'],
                'next_review_trigger': old.get('next_review_trigger'),
                'action': '先审独立因果及新增事实；成立后以Event Update补全渠道、Horizon和Bias。证据不足保留WATCH。'})
        queue = {'generated_at': report['as_of'],
            'note': '保留原信息和审核去向；不将研究倾向改写成正式Bias。不是本日新收集。',
            'event_review_queue': event_queue,
            'information_review_queue': [{**i, 'linked_events': linked.get(i['information_id'], []),
                'prior_review': reviews.get(i['information_id']),
                'next_action': '核实同一Parent的信息增量，决定Update或背景' if i['information_id'] in linked
                else '审核新Parent、旧Parent Update、市场State、背景或待核实；尚不自动创建Parent'}
                for i in inbox],
            'source_registry': sources,
            'collection_window': references['reference:collection_window_20261010.json']['content']}
        for filename, content in [('current_report.json', report), ('review_queue.json', queue)]:
            (ROOT / 'data' / filename).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
        priorities = Counter(r.get('research_priority') for r in reviews.values())
        summary = {'information': len(inbox), 'draft_events': len(report['events']),
                   'linked_information': len(linked), 'unassigned_information': len(inbox) - len(linked),
                   'source_registry': len(sources), 'research_priorities': dict(priorities),
                   'qualifications': dict(Counter(e['qualification'] for e in report['events'])),
                   'causal_updates': engine.db.execute('SELECT COUNT(*) FROM event_updates').fetchone()[0],
                   'state_updates': engine.db.execute('SELECT COUNT(*) FROM state_updates').fetchone()[0],
                   'all_events': engine.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],
                   'historical_events': engine.db.execute("SELECT COUNT(*) FROM events WHERE json_extract(payload,'$.scope')='Historical'").fetchone()[0],
                   'research_notes': engine.db.execute('SELECT COUNT(*) FROM research_notes').fetchone()[0]}
        (ROOT / 'data' / 'migration_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        doc = ['# 迁移结果与待审核事项', '',
               '## 已落实', '',
               f'- {len(inbox)}条原始信息完整入库，{len(sources)}个来源登记保留。',
               f'- {len(report["events"])}张原事件卡迁移为待审核Parent候选，正式Bias/Channel/Horizon仍待审核。',
               f'- {len(linked)}条信息已关联候选，{len(inbox)-len(linked)}条保留在待分流队列；不为凑数量自动建事件。',
               '- 原10条研究版本记录保留为legacy_audit；另外4份来源、窗口、审核和指数暴露资料保留为参考审计。',
               '- 11个历史Parent已按CSV导入历史知识库；16条来源标签含11条Parent、3条Update、2条State，均待核实，未激活为正式信号。',
               f'- 当前全部研究与审核记录{summary["research_notes"]}条；因果更新{summary["causal_updates"]}条，市场状态{summary["state_updates"]}条。原文核查和未完成审核的更新不代表方向通过。',
               '- 924、DeepSeek、小微盘首轮审核见《首轮历史事件审核》；补入来源、时间纠正、双向解释与待补证据。',
               '- 事件创建、因果更新、状态更新、时间查询、资格筛选及分周期主导候选选择均已实现。', '',
               '## 当前实际输出', '',
               '全部7个当前候选为WATCH。历史原文审核已有未完成审核的因果更新；当前候选没有通过完整审核的方向或市场State，三个周期的主导事件均为空。',
               '这是缺口的真实呈现，不是“市场没有事件”的结论。来源事实可靠与否、事件增量和方向正确与否分别审核。', '',
               '原P1/P2/P3仅决定研究先后，不转换成InformationGain；旧event_type=Trend也不直接转换成新ExpectedHorizon。', '',
               '## 逐事件下一步', '']
        for e in event_queue:
            doc += [f'### {e["event_id"]} · {e["name"]}', '',
                    '**先核实：** ' + '; '.join(e['existing_gaps']), '',
                    '**下一触发：** ' + str(e.get('next_review_trigger') or '完成上述证据核查'), '',
                    '**处理口径：** 不凭新闻类别或旧研究倾向直接给IM/IH；补证后提交因果Update。', '']
        doc += ['## 阅读与时间边界', '',
                '已读取ChatGPT接口提供的最近5轮，未获得更早完整历史；源文件保存读取覆盖说明。',
                '本次落实已有资料与事件处理，不是新的每日全量收集；旧信息主要来自2026-10-09至10-10，不能称为已收集到10-11当前。',
                '未实现自动新闻抓取、定时运行、实时行情、自动MarketAcceptance阈值、自动TTL衰减或交易指令。',
                '状态是否过时需要每日重审；没有擅自指定过期天数。实际网络收集和方向研判仍按每日流程逐条核实。', '',
                '下一项具体工作：先从现有P1队列完成官方原文、旧政策/预期基线和当期指数暴露比较，再给有充分证据的Parent提交首次因果审核。']
        (ROOT / 'docs' / '迁移结果与待审核事项.md').write_text('\n'.join(doc) + '\n', encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        engine.close()


if __name__ == '__main__':
    main()
