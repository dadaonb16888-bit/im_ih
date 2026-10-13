# IM/IH 事件处理模块 V1.0

已依据ChatGPT《股指品种对冲策略研究》的最新启动包和补充标注规则，建立本地SQLite数据库和可运行事件处理程序。本阶段只处理事件、方向和市场接受度，不执行回测或下单。

在其他电脑上运行与GitHub交付范围见[GitHub交付说明](docs/GitHub交付说明.md)。需要Python 3.10或更新版本，无第三方Python依赖。

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

最新开发计划：[最新开发路线](docs/最新开发路线.md)：Phase 1事件基础→Phase 1.5历史行情→Phase 2事件Alpha研究→Phase 3实时监控→Phase 4自动交易。历史版本见[Phase 1工程启动包与实现对照](docs/Phase1计划与当前实现对照.md)。具体行情和统计任务尚未执行。

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
