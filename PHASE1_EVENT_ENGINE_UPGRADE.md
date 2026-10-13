# Phase 1 Event Engine Upgrade

完成日期：2026-10-13。规范：PROJECT_REVIEW.md、CODEX_TASK_PHASE1_EVENT_ENGINE.md。编码前先完成PHASE1_IMPLEMENTATION_PLAN.md。

## 实现结果

原Event Research Layer已增量接入Event Alpha计算与方向输出。原Parent/Update/State、AI判读、收集、研究记录、数据库及工作台均保留。没有加入Spread、Timing、Execution、Broker或回测模块。

|模块|实现|
|---|---|
|Event Schema|兼容event_name/name、channel/channels；source、source_reliability、impact_score、confidence_score、persistence_score、event_strength、affected_style、status|
|Channel|九类必需映射加原POSITIONING；TECH_GROWTH默认Strong IM、小盘流动性危机默认Strong IH；证据方向覆盖、null不强填、多渠道相反默认不定向|
|Score|Impact × Confidence × Persistence × Freshness；缺关键证据保持null；未知与零分分开|
|Confidence|0–1有限数值，来源等级或数值可靠性限制上限，不从旧文字High自动填数值|
|Decay|含时区精确时间，指数自然日衰减；Fast/Swing/Trend分开；Low重复不重启时钟|
|Update|information_gain保留；新增bias_change、channel_change、score_change、score_before/after与评分时刻；重放幂等|
|State|根据显式接受度和priced_in/impact_weakening观察自动转移；保留证据、因果epoch与双时间；Crowded不会仅因Confirmed自动解除|
|Dominance|全池和三周期按分数排名；剔除历史、未来、失效、未审核及缺数值事件；同分/反向冲突保留候选|
|Interface|EventEngine.alpha_report、CLI alpha-report、只读GET /api/alpha；原report新增event_alpha|
|Workbench|事件评分页展示组件、缺口、渠道假设、主导事件及更新历史；AI判读与收集页面继续可用|

## 修改文件

1. event_engine/engine.py：接入字段契约、更新差异、状态推导和Alpha接口；因果Update引用资料也检查可知时间。
2. event_engine/ai_research.py：数值判读沿现有正式因果升格路径写入，证据门槛保留。
3. database/schema.sql：JSON生成列与只读event_states视图。
4. database/events.sqlite3：幂等结构升级，旧记录未改变。
5. manage.py：alpha-report命令。
6. workbench.py：只读Alpha API。
7. dashboard/app.js：事件评分页。
8. dashboard/style.css：评分页布局。
9. tests/test_ai_research.py：数值判读、缺证据和事务回滚的3项测试。
10. README.md：最新规范、字段、参数、运行方式与接口。
11. docs/最新开发路线.md：最高优先级规范与新阶段划分。

## 新增文件

1. event_engine/channel.py
2. event_engine/scoring.py
3. event_engine/decay.py
4. event_engine/dominance.py
5. event_engine/confidence.py
6. event_engine/event.py（原仓库没有该文件）
7. event_engine/event_update.py（原仓库没有该文件）
8. event_engine/event_state.py（原仓库没有该文件）
9. database/migrations.py
10. tests/test_event_alpha.py（25项测试）
11. PHASE1_IMPLEMENTATION_PLAN.md
12. PHASE1_EVENT_ENGINE_UPGRADE.md
13. data/event_alpha_current_report.json
14. data/phase1_event_alpha_validation.json
15. docs/event_alpha_preview.png

PROJECT_REVIEW.md和CODEX_TASK_PHASE1_EVENT_ENGINE.md为从GitHub完整读取并保存的规范副本，不是本轮自行改写的新需求。

## 数据库与兼容

- schema版本2，events增加可查询name/channel/horizon/bias/impact/confidence/score/created_time/status及来源、持续度等JSON生成列；event_updates增加information_gain、bias_change、channel_change、score_change、update_time生成列。
- event_states是state_updates的只读兼容视图；写入仍走原State方法，审计与不可改删触发器保持。
- SQL列是其所属记录的快照，不是当前完整事件投影。当前/as_of评分从Parent和当时可见Update重建，防止旧分数冒充实时分数。
- 原report.dominant保留旧研究优先级；标准数值输出为event_alpha/alpha-report。下游应该接新接口。
- 14张表全部旧记录（包含payload、known/effective/recorded时间及关联）与升级前SQLite备份逐项一致。18个事件、53条信息、8条AI判读、19条研究记录、2条因果更新、0条市场状态保持。

## 验证结果

- 修改前72项测试通过；最终全量100项测试通过（原72项＋新25项Alpha测试＋新3项AI流程测试）。
- 四项指定验收通过：TECH_GROWTH→Strong IM；DIRECT_SMALLCAP_LIQUIDITY→Strong IH；随时间分数衰减；多事件返回最高分主导。
- 验证未知/null、方向覆盖、来源置信度上限、NaN/无穷/布尔/越界拒绝、时区与未来、评分增量、低增量去重、方向轮转、状态时序、拥挤解除、同分冲突、旧库升级及重开、不可改删、CLI/API接入与AI事务回滚。
- SQLite integrity_check=ok，foreign_key_check无违规；旧记录比较全部通过。
- 前端JavaScript语法检查通过；浏览器确认事件评分页、缺口、主导事件空池输出及原AI判读，控制台无错误。截图见docs/event_alpha_preview.png。
- 实际库当前可评分事件为0、dominant_event=null。升级能力与历史事件证据完整性是两个问题，未为填满排名而补造数值。

## 参数与风险

- 持续度默认Fast=0.4、Swing=0.7、Trend=1；衰减周期为1/5/20自然日；来源上限A=1、B=.85、C=.6、D=.3。都是未校准研究参数；分数不是已验证收益预测。
- 默认渠道映射有明确前提，例如DIRECT_SMALLCAP_LIQUIDITY指危机而非救助注资；不将新闻Category机械转为方向。
- Fresh生命周期可以表示完整研究事件进入Alpha池，不会凭时间或分数生成市场Confirmed。
- trade_permission仅是事件层资格。entry_allowed始终false，仍无进场时机或执行能力。
- 旧AI卡没有自动映射文字置信度到数值；补充数值需Codex读取来源并追加新版本。普通JSON标签仍不能证明作者身份或原文已经读取。
- 本轮没有增加无人值守模型、联网采集或定时任务。

## 下一阶段建议

先用完整原文、预期基线、受益暴露和精确时间，为一批事件补齐可审计的影响/置信度数值及来源，验证工程输出。随后按新规范单独规划Phase 2历史行情与Spread；用户当前暂停回测，因此不在本轮提前接入行情、回测或交易执行。
