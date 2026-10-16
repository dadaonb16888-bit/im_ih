# Phase 1 Implementation Plan

分析完成：2026-10-13。最高优先级依据：[PROJECT_REVIEW.md](PROJECT_REVIEW.md) 与 [CODEX_TASK_PHASE1_EVENT_ENGINE.md](CODEX_TASK_PHASE1_EVENT_ENGINE.md)。本计划在编码前形成。

## 当前项目分析

- 目录保留 event_engine、database、dashboard、workbench.py、manage.py、data、docs、tests。没有 Spread、Execution 或 Broker 模块。
- engine.py 集中实现 Parent、因果 Update、State、双时间可见性、不可改删账本、资格检查及按直接度/增量排序的旧主导候选。规范提到的 event.py、event_update.py、event_state.py 尚不存在，因此新增模块并接入既有引擎，不替换整个项目。
- 数据库已有14张表：18个事件、53条原始信息、19条研究记录、2条因果更新、8条AI判读、1个收集批次。市场 State 为0。数据库完整性正常。
- 改动前全量72项测试通过。已使用SQLite一致性备份保存升级前快照。
- 与 PROJECT_REVIEW 的主要差距：渠道只有枚举；没有数值影响、置信度、持续度和时间衰减；没有按数值Alpha排序的独立输出；Update无方向/渠道/分数差异；State依赖显式输入。市场、Spread、Timing、回测和Execution留在后续阶段。

## 修改文件

- event_engine/engine.py：接入字段校验、自动状态、更新差异和Alpha输出，保留旧研究接口及资格规则。
- database/schema.sql：为新库增加Alpha字段的JSON生成列及event_states兼容视图；旧库采用幂等追加列迁移。
- event_engine/ai_research.py：允许有来源的数值判读随正式因果升格进入评分；旧研究包保持兼容，证据缺口不能因分数绕过。
- manage.py、workbench.py：增加只读Alpha报告接口和CLI，不开发下单接口。
- dashboard/app.js、dashboard/style.css：展示数值组件、默认映射、主导Alpha及缺口；保留研究、收集和原有页面。
- README.md、docs/最新开发路线.md：说明当前最高优先级规范、参数、输出边界和运行方式。

## 新增文件

- event_engine/channel.py：九个必需渠道的默认IM/IH影响映射，兼容既有POSITIONING，支持证据方向覆盖；不是按新闻Category直接定方向。
- event_engine/confidence.py：可靠性等级与数值置信度校验、限制；映射参数作为未校准工程配置。
- event_engine/decay.py：时区感知的指数时间衰减，Fast/Swing/Trend分开配置。
- event_engine/scoring.py：Impact × Confidence × Persistence × Freshness；缺关键值返回不可评分，不用零或中性替代未知。
- event_engine/dominance.py：排除未来/失效/历史/不可评分事件，数值排序、同分冲突和按周期输出；独立区分事件层许可与实际开仓。
- event_engine/event.py、event_update.py、event_state.py：事件Alpha投影、更新变化、基于明确观察的状态转换。
- tests/test_event_alpha.py：规范四项验收加迁移、时序、重放、冲突、状态、研究包与API兼容回归。
- PHASE1_EVENT_ENGINE_UPGRADE.md：最终变更日志、验证、风险与下一阶段建议。

## 数据结构与口径

- Parent/Update JSON增量支持source、source_reliability、impact_score(0–5)、confidence_score(0–1)、persistence_score(0–1)、event_strength、affected_style、status；兼容event_name/name、channel/channels。
- events/event_updates保留原payload与审计列。新增JSON生成列满足SQL查询字段；不回写旧记录，不把已保存研究倾向自动升级。event_states为state_updates只读兼容视图，保留现有写入入口。
- 更新保存计算得到的bias_change、channel_change、score_change与评分时刻；低增量重复不提高数值、不重新开始衰减。衰减从真实公开时间计时，重大增量仅在明确修改事件时间/评分依据时调整。
- 分数在as_of动态计算；存储分数只是当次记录时的快照，不能充当以后任意时点分数。默认持续度Fast=0.4/Swing=0.7/Trend=1，衰减周期1/5/20自然日；均为待验证参数。
- alpha_state可在完整事件进入研究池时为Fresh（事件生命周期）；市场pricing_state只有具有证据的State才改变。自动转移依据已提供的acceptance、priced_in、impact_weakening观察，无数据不制造Confirmed。
- 旧report.dominant保留兼容并明确为旧研究优先级；新event_alpha/alpha-report接口是数值Alpha标准输出。trade_permission仅表示事件层资格，entry_allowed始终false。

## 风险点与控制

1. 默认渠道方向只是基准假设；证据支持的明确bias优先，null保持未知，混合渠道冲突不强行定向。
2. 分数参数尚未统计校准；不声称产生有效收益Alpha，不接行情或回测。
3. 旧库/包缺数值仍可读可导入，显示评分缺口，不补造指标或市场接受度。
4. known_at与effective_at同时限制历史可见性；不能拿未来更新、未来资料或后来判读做历史排名。
5. SQLite生成列和兼容视图需要幂等升级；迁移前备份，升级后比对全部旧payload/记录并验证完整性。
6. 同分反向事件不随ID强行决定方向；返回冲突和候选，事件排名不等于实际交易许可。

## 执行顺序

纯函数模块与字段契约 → 数据库兼容迁移 → 既有引擎/AI流程接入 → CLI/API与工作台 → 全量测试与旧库保留检查 → README及变更日志。范围仅Event Layer。
