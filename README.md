# IM/IH 事件处理模块 V1.0

已依据ChatGPT《股指品种对冲策略研究》的最新启动包和补充标注规则，建立本地SQLite数据库和可运行事件处理程序。本阶段只处理事件、方向和市场接受度，不执行回测或下单。

在其他电脑上运行与GitHub交付范围见[GitHub交付说明](docs/GitHub交付说明.md)。需要Python 3.10或更新版本，无第三方Python依赖。

## Phase 1 Event Engine Upgrade（2026-10-13）

当前最高优先级规范是 [PROJECT_REVIEW.md](PROJECT_REVIEW.md) 和 [CODEX_TASK_PHASE1_EVENT_ENGINE.md](CODEX_TASK_PHASE1_EVENT_ENGINE.md)。已在原事件系统内增量实现 **Event → Event Alpha → IM/IH Bias**，保留收集、AI研究、因果审核、数据库和工作台。分析计划见 [PHASE1_IMPLEMENTATION_PLAN.md](PHASE1_IMPLEMENTATION_PLAN.md)，完整变更与风险见 [PHASE1_EVENT_ENGINE_UPGRADE.md](PHASE1_EVENT_ENGINE_UPGRADE.md)。

- 新增九类渠道默认影响（兼容POSITIONING）、数值评分、时间衰减、主导事件排序和按周期输出。TECH_GROWTH默认Strong IM；DIRECT_SMALLCAP_LIQUIDITY默认Strong IH，前提是小盘流动性危机。明确证据方向可以覆盖默认，明确null保持未知。
- `Event Score = Impact × Confidence × Persistence × Freshness`。Impact为0–5，数值Confidence为0–1并受来源可靠性约束；默认Persistence为Fast 0.4/Swing 0.7/Trend 1，指数衰减周期为1/5/20自然日。来源等级上限A/B/C/D为1/0.85/0.6/0.3。这些工程参数尚未统计校准，不代表已验证的交易收益。
- 使用`event_name`/`channel`或兼容的`name`/`channels`。新增source、source_reliability、impact_score、confidence_score、persistence_score、event_strength、affected_style、status；数值及方向通过具有新增事实的Event Update追加，低增量重复不能抬分或重启衰减。
- State在提供接受度、priced_in或impact_weakening观察及证据后自动推导Fresh/Diffusing/Crowded/Reversing；没有行情不会生成市场Confirmed。`alpha_state=Fresh`仅表示完整事件评分进入生命周期，不等于市场已确认。Crowded需明确解除已定价观察才能恢复扩散。
- 工作台增加 **事件评分** 页，显示评分组件、默认渠道前提、评分缺口、全池及三个周期的主导事件。现有18个事件/8条AI判读缺完整数值依据，仍无可评分主导事件；全部旧记录保持保留。

运行数值Alpha报告：

```text
python manage.py alpha-report --output data/event_alpha_current_report.json
python manage.py alpha-report --as-of 2026-10-13T20:00:00+08:00
```

只读API：`GET /api/alpha?as_of=<时区时间>`。响应含`dominant_event`、`score`、`bias`、`confidence`、`ranking`、`excluded`、`by_horizon`及`trade_permission`。后者只表示事件层资格；实际`entry_allowed`始终false。同分保留候选，反向同分显式输出conflict，不强行选方向。

`GET /api/events`和`manage.py report`新增`event_alpha`作为数值输出，旧`dominant`保留为LegacyResearchPriority兼容结果。分数按as_of重新计算；SQL生成列中的Parent数值是创建时快照，Update的score_before/score_after及State的event_score是各自记录时刻快照，查询当前数值应使用Alpha接口。

数据库升级为版本2：只追加JSON生成列与只读event_states视图，原始payload和记录时间不回写。Python 3.10标准运行时的SQLite支持这些生成列；外部SQLite工具需3.31或更新版本。升级前本地备份不进入仓库。

全量100项测试通过，其中28项为本轮新增。未开发Spread Engine、Trading Execution或Broker API。

### 评分证据与研究预览（2026-10-13后续）

新增`score_basis`：每个评分组件分别保存数值、Codex解释和来源编号。参考时刻必须匹配已经核对的精确来源时间，不能把日期补成零点，也不能用官方原文的可靠性代替方向置信度。规则与真实案例见[评分证据与研究案例](docs/评分证据与研究案例.md)。

工作台“AI判读”和“事件评分”页现在分别展示**研究评分**与正式Alpha。两条新研究卡已追加，AI判读总数10、原始信息57；其中一条仅有参考时间研究分数，另一条因相对影响及方向未知而保持null。正式Parent方向、Dominant和市场确认均未升格。来源原件快照与指纹保存于`data/source_snapshots`，可从工作台打开。

```text
python manage.py research-alpha-report --output data/research_alpha_report_20261013.json
```

只读API：`GET /api/research-alpha`。输出永远标记research_only=true、trade_permission=false。基础强度不依赖精确时刻，有完整数值依据时可单独展示；含Freshness的分数仍要求精确参考时间。原Alpha接口和资格规则保持。后续全量118项测试通过。

## 事件判读由Codex执行

用户无需填IM/IH方向或审批研究结论。Codex读取原文、核对增量与预期、比较两指数受益并给出方向或证据不足结论；工作台默认展示“AI判读”，事实与推理、研究方向与正式资格分别保存。见[AI事件判读流程](docs/AI事件判读流程.md)。

当前由研究对话实际执行判读并写入，本地服务展示已保存结果。无人值守模型调用和定时执行尚未接入，不能仅启动工作台就认为后台在自动分析。

2026-10-13首轮已写入8条AI判读：7个近期候选及DeepSeek历史复核；补充10条基线/附件/版本来源，信息总数53。具体偏向、置信度及证据缺口在事件“AI判读”页查看。原43条信息和既有因果/市场记录保持保留，此次研究卡没有升格为交易方向或行情确认。

## 每日收集与分流工作台（2026-10-13）

在工作台顶部点击 **每日收集**。可以建立固定Cutoff的批次，逐项登记14类来源检查，把信息归并到新Parent、已有Parent Update、市场State、背景或待核实，并复核既有Parent的后续进展。

默认窗口为北京时间前一自然日00:00至当前；周一补到上周五00:00，节后需人工扩大起点。来源登记和之前的检查状态不会自动成为今天的覆盖结果，尚未检索、网页受阻及全文未读都显示为缺口。批次报告可下载，修订以新记录追加，历史查询保留当时可见判断。

新界面保存收集、AI判读与审计记录；没有自动抓取新闻，也不会凭资料分流生成Bias或市场确认。详细操作见[每日收集工作台](docs/每日收集工作台.md)。

## 使用本地工作台

访问 **http://127.0.0.1:8766/** 。界面支持新增原始信息、创建事件候选、信息关联、因果更新、市场状态与完整记录查看。已导入11个历史Parent及16条待核实来源记录，保留7个近期候选。首轮原文核查后共43条信息、19条研究与审核记录、2条未完成审核的因果更新；市场状态仍为空。

最新成果：[首轮历史事件审核](docs/首轮历史事件审核.md)。924、DeepSeek和小微盘卡中已分开列出事实、研究倾向、反方解释、时间修正和证据缺口。补入来源可重复执行`apply_historical_audit.py`，同一版本不会重复入库；修订应使用新版本ID。

来源中的初始方向、日期、High/Confirmed/Active标签只作为研究资料保留，不自动成为正式信号。历史事件始终与近期候选分开，不参与当前主导事件选择。924的两版初始方向在界面中明确提示差异。

关闭程序后需要重新启动：

```powershell
& 'C:\Users\yingh\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' workbench.py
```

程序仅监听本机地址，不接外部账户、实时行情或交易接口。

阅读顺序：

最新开发计划以根目录两份规范为准：Phase 1事件Alpha工程→Phase 2历史行情及Spread→Phase 3历史Alpha验证→Phase 4监控→Phase 5执行。原路线和历史版本保留在[最新开发路线](docs/最新开发路线.md)及[Phase 1工程启动包与实现对照](docs/Phase1计划与当前实现对照.md)。当前范围仍只含Event Layer，行情和统计任务尚未执行。

1. [事件处理规则](docs/事件处理规则.md)：什么算事件，何时更新，方向怎样判断。
2. [每日收集与审核流程](docs/每日收集与审核流程.md)：覆盖前一天至当前的完整收集窗口。
3. [迁移结果与待审核事项](docs/迁移结果与待审核事项.md)：已有信息的实际落库情况。
4. `data/review_queue.json`：逐条信息及事件的审核队列。
5. `data/current_report.json`：当前事件资格和三个周期的主导事件输出。

数据：`database/events.sqlite3`。原研究资料仍保留在 `../analysis/ih_im_event_research`，没有覆盖。

程序使用Python标准库，无需安装额外依赖。在本目录运行：

```powershell
$eventPython = 'C:\Users\yingh\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $eventPython manage.py report --output data/current_report.json
& $eventPython prepare_review.py
& $eventPython manage.py add-information data/information_template.json
& $eventPython manage.py create data/parent_template.json
& $eventPython manage.py update data/update_template.json
& $eventPython manage.py state data/state_template.json
& $eventPython manage.py import-research data/events
& $eventPython manage.py export-research data/exported_research
& $eventPython manage.py report --include-historical --output data/knowledge_report.json
& $eventPython manage.py history 202409_POLICY_PIVOT
& $eventPython -m unittest discover -s tests -v
```

模板是待填写格式，含null的模板不会通过审核；先复制并填入真实来源、完整时间与判断，再提交。已有记录禁止覆盖或删除，修订采用新ID追加。相同ID且内容相同可安全重复提交；相同ID且内容变化会报错。

重复迁移命令：

```powershell
& $eventPython manage.py migrate '..\analysis\ih_im_event_research'
```

本程序没有联网收集器、定时任务或实时行情连接。早期迁移的数据来自10月10日已有资料；10月13日新增研究卡也不代表已经完成当日全窗口收集。市场确认需后续接入可核查的IM/IH相对行情证据并由Codex判断，当前没有行情确认结果。
