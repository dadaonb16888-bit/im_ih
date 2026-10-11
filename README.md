# IM/IH 事件处理模块 V1.0

已依据ChatGPT《股指品种对冲策略研究》的最新启动包和补充标注规则，建立本地SQLite数据库和可运行事件处理程序。本阶段只处理事件、方向和市场接受度，不执行回测或下单。

在其他电脑上运行与GitHub交付范围见[GitHub交付说明](docs/GitHub交付说明.md)。需要Python 3.10或更新版本，无第三方Python依赖。

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

本程序没有联网收集器、定时任务或实时行情连接。迁移的数据来自10月10日已有资料，不代表已经收集到10月11日当前。市场确认仍需人工提供可核查的IM/IH相对行情证据。
