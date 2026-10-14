# Phase 1 Event Engine Upgrade

## 最新复核（2026-10-14 07:35）

可选暴露类型增加PortfolioDisclosure及日期/引用测试；追加6条来源、2张V4卡。新质生产力由IM改为不定方向，公募继续不定方向；旧评分及方向按as_of保留，正式状态不变。全量132项测试通过。详见[基线复核与方向修订](docs/基线复核与方向修订_20261014.md)，下文各轮记录为当次快照。

## 最新交付：政策增量与受益路径（2026-10-14）

新增可选impact_analysis契约及引用/基线/暴露日期校验，在原AI事务中追加。工作台显示政策变化、执行状态、力度及IM/IH机会和抵消因素。新增4条来源和2张V3研究卡，数据为18个事件、61条信息、12条AI判读、19条研究记录、2条因果更新、0条正式市场State；旧库14张表旧行全部保留。没有改写评分公式或自动升格方向。130项测试通过（前轮118＋本轮12）。实施计划、全部修改/新增文件与风险见[政策增量与企业路径案例](docs/政策增量与企业路径案例.md)。下文保留前轮记录。

完成日期：2026-10-13。规范：PROJECT_REVIEW.md、CODEX_TASK_PHASE1_EVENT_ENGINE.md。编码前先完成PHASE1_IMPLEMENTATION_PLAN.md。

## 2026-10-13后续：评分证据

新增event_engine/score_evidence.py和tests/test_score_evidence.py；修改AI判读、评分基础强度、CLI/API及工作台，提供有逐项证据的独立研究评分和受限归档原件读取。补4条来源、2条研究卡及两份官方PDF快照；旧记录均保留，正式方向及市场状态未升格。全量测试从100增至118项。原轮次记录如下保留；最新真实数据为18个事件、57条信息、10条AI判读、2条因果更新、0条正式市场State。详见[评分证据与研究案例](docs/评分证据与研究案例.md)。

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

## 2026-10-14 每日收集与整批导入

按[每日收集落库计划](docs/每日收集落库计划_20261014.md)增量新增受信本地整批导入`apply_daily_collection.py`及4项测试，原数据表、工作台和AI研究流程保持。整批失败回滚、同包重放不重复、变化拒绝覆盖、入库时刻不接受外部倒填。

实际检查26个冻结入口及补充来源，保存14类57项检查、29条信息、3个新候选、5份AI判读与7个旧Parent复核。29条分为3条新候选、4条事件关联信息、15条背景、7条待核实。19条精确时间落窗口、1条早于窗口、9条精确时间未核；全部实际发现晚于固定截止，未倒填知识。

新地区风险候选仅有低置信度IH研究推断，影响幅度未知，不评分；两项产业/制度候选未知方向。旧新质生产力卡追加低增量传播V5并保留V4政策表与10月9日参考时间，未恢复原IM方向。中欧会见归并旧磋商，意愿不当已签订单。未增加正式因果更新或市场State。

新增数据：`daily_collection_20261014.json`、`daily_source_audit_20261014.json`、`ai_daily_collection_20261014.json`、`daily_collection_report_20261014.json`、`daily_collection_validation_20261014.json`。新增研究报告与浏览器验证截图`docs/daily_collection_20261014_preview.png`；更新README与交付说明，数据库追加当前快照。

验证：全量136项测试通过；旧库14张表旧行逐条保留，完整性正常、外键无违规；两类包同包重放均不新增，历史截止不可提前看到新候选或新意见。浏览器核验固定窗口、14类覆盖缺口、时间精度与分流、旧事件复核和低置信度IH卡，无控制台错误。

当前库21个事件、96条信息、19份AI判读、19条研究记录、2条未完成审核因果更新、0条State。14类覆盖仍Partial/Blocked，7条Pending、9条精确时刻未核、5个旧候选后续待核；原始ETF份额/机构持仓与完整动态公告未接入。研究可评分数量与正式数值Dominant仍为空。没有无人值守联网收集、模型调用、行情回测或执行。
