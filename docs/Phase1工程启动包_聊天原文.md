来源：ChatGPT《股指品种对冲策略研究》，最新轮次 `8017a23e-71dd-4d35-8862-305b63538d49`。

链接：https://chatgpt.com/c/6ac8eb59-034c-83e8-89d8-04063cc5f820

覆盖说明：本次接口返回最近5轮，本文完整保存最新一轮的Phase 1工程启动包；未取得更早完整聊天历史。以下为来源原文，示例标签及代码尚不等于经过核实的实施规格。

下面进入 **Phase 1：工程启动文件输出**。

目标：

让 Codex 收到后可以直接开始搭建项目。

本次输出包含：

1. 项目目录结构  
2. SQLite 数据库建表 SQL  
3. 第一版 Event CSV 模板  
4. Python 项目骨架  
5. 第一阶段开发任务说明  

---

# IM_IH_Event_System

## Phase 1 工程启动包 V1.0

---

# 一、项目目录结构

创建：

```text
IM_IH_Event_System/

│
├── README.md
│
├── config/
│   └── config.yaml
│
├── data/
│   ├── raw/
│   │   ├── im_price.csv
│   │   ├── ih_price.csv
│   │
│   └── events/
│       ├── events.csv
│       ├── event_updates.csv
│       └── event_states.csv
│
├── database/
│   └── event_system.db
│
├── sql/
│   └── schema.sql
│
├── src/
│
│   ├── database/
│   │   ├── db.py
│   │   └── models.py
│   │
│   ├── event_engine/
│   │   ├── event_loader.py
│   │   ├── event_state.py
│   │   └── dominant_event.py
│   │
│   ├── spread_engine/
│   │   ├── spread.py
│   │   └── basis.py
│   │
│   ├── backtest/
│   │   ├── event_backtest.py
│   │   └── performance.py
│   │
│   └── main.py
│
├── notebooks/
│   ├── event_analysis.ipynb
│   └── spread_analysis.ipynb
│
└── dashboard/
    └── app.py
```

---

# 二、数据库设计

## schema.sql


```sql
CREATE TABLE events (

    event_id TEXT PRIMARY KEY,

    event_name TEXT NOT NULL,

    event_type TEXT,

    event_time DATETIME,

    first_tradable_time DATETIME,

    channel TEXT,

    horizon TEXT,

    initial_bias TEXT,

    current_bias TEXT,

    invalidation TEXT,

    status TEXT,

    confidence TEXT

);


CREATE TABLE event_updates (

    update_id INTEGER PRIMARY KEY AUTOINCREMENT,

    event_id TEXT,

    update_time DATETIME,

    source_type TEXT,

    information_gain TEXT,

    description TEXT,

    new_bias TEXT,

    new_channel TEXT,

    FOREIGN KEY(event_id)
    REFERENCES events(event_id)

);


CREATE TABLE event_states (

    state_id INTEGER PRIMARY KEY AUTOINCREMENT,

    event_id TEXT,

    timestamp DATETIME,

    pricing_state TEXT,

    acceptance TEXT,

    dominant BOOLEAN,

    FOREIGN KEY(event_id)
    REFERENCES events(event_id)

);


CREATE TABLE market_data (

    datetime DATETIME PRIMARY KEY,

    im_price REAL,

    ih_price REAL,

    spread REAL,

    volume_im REAL,

    volume_ih REAL

);


CREATE TABLE signals (

    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,

    datetime DATETIME,

    event_id TEXT,

    direction TEXT,

    spread REAL,

    strength TEXT,

    entry_allowed BOOLEAN

);
```

---

# 三、Event CSV模板

## events.csv


```csv
event_id,event_name,event_type,event_time,first_tradable_time,channel,horizon,initial_bias,status,confidence
```


---

## 第一批录入事件

```csv
event_id,event_name,event_type,event_time,first_tradable_time,channel,horizon,initial_bias,status,confidence

202210_SEMICONDUCTOR_RESTRICTION,
US Semiconductor Restriction,
News,
2022-10-07,
2022-10-10,
TECH_GROWTH_RISK_OFF,
Swing,
IH,
Closed,
High


202211_REOPENING_TRANSITION,
China Reopening Transition,
News,
2022-11-11,
2022-11-14,
RISK_APPETITE,
Swing,
IM,
Closed,
High


202307_POLICY_SUPPORT,
Policy Support,
News,
2023-07-24,
2023-07-25,
CREDIT_LARGECAP,
Swing,
IH,
Closed,
High


202310_STATE_SUPPORT,
Huijin State Support,
News,
2023-10-11,
2023-10-12,
DIRECT_LARGECAP,
Fast,
IH,
Closed,
High


202401_SMALLCAP_LIQUIDITY_STRESS,
Small Cap Liquidity Stress,
MarketState,
2024-01-31,
2024-02-01,
DIRECT_SMALLCAP_LIQUIDITY,
Fast,
Strong_IH,
Closed,
High


202402_MARKET_STABILIZATION,
State Stabilization,
News,
2024-02-06,
2024-02-06,
MARKET_STABILIZATION,
Fast,
IH,
Closed,
High


202404_NEW_NINE_RULES,
New Nine Rules,
News,
2024-04-12,
2024-04-15,
REGULATION_QUALITY,
Swing,
IH,
Closed,
High


202405_PROPERTY_SUPPORT,
Property Support,
News,
2024-05-17,
2024-05-20,
CREDIT_LARGECAP,
Swing,
IH,
Closed,
High


202409_POLICY_PIVOT,
Policy Pivot,
News,
2024-09-24,
2024-09-24,
LIQUIDITY_RISK_APPETITE,
Swing,
IM,
Active,
High


202501_DEEPSEEK_AI_REPRICING,
DeepSeek AI Repricing,
News,
2025-01-20,
2025-02-05,
TECH_GROWTH,
Trend,
Strong_IM,
Active,
High


202504_TARIFF_CONFLICT,
US China Tariff Conflict,
News,
2025-04-07,
2025-04-07,
RISK_OFF,
Fast,
IH,
Closed,
High
```

---

# 四、event_updates.csv模板


```csv
event_id,update_time,source_type,information_gain,description,new_bias
```


示例：

```csv
202409_POLICY_PIVOT,
2024-09-26,
Policy,
High,
Political Bureau confirmation,
IM


202501_DEEPSEEK_AI_REPRICING,
2025-01-27,
GlobalMarket,
High,
Global AI repricing,
Strong_IM


202504_TARIFF_CONFLICT,
2025-05-12,
Diplomatic,
Medium,
Geneva tariff de-escalation,
IM
```

---

# 五、event_states.csv


```csv
event_id,timestamp,pricing_state,acceptance,dominant
```


示例：

```csv
202501_DEEPSEEK_AI_REPRICING,
2025-02-10,
Diffusing,
Confirmed,
True


202401_SMALLCAP_LIQUIDITY_STRESS,
2024-02-05,
Crowded,
Confirmed,
True
```

---

# 六、Python核心模块


## spread.py


功能：

计算IM/IH价差。


```python
import numpy as np


def calculate_spread(im, ih):

    return np.log(im)-np.log(ih)



def spread_return(start,end):

    return end-start
```

---

# event_loader.py


读取事件库。


```python
import pandas as pd


def load_events(path):

    return pd.read_csv(path)
```

---

# dominant_event.py


第一版规则。


```python

def select_event(events):

    active = events[
        events["status"]=="Active"
    ]


    if len(active)==0:
        return None


    return active.sort_values(
        by="confidence",
        ascending=False
    ).iloc[0]
```

---

# signal_engine.py


```python

def generate_signal(event):


    if event["initial_bias"]=="Strong_IM":

        return 1


    if event["initial_bias"]=="IH":

        return -1


    return 0
```

---

# 七、第一阶段回测目标


不是直接交易。


先验证：

## Event Direction


问题：

事件方向是否正确？


输出：

```text
Event

Bias

T+1 Spread

T+3 Spread

T+5 Spread

T+10 Spread

Correct?
```

---

# 八、第一阶段开发任务


## Task 1

创建数据库。


完成：

- schema.sql
- SQLite初始化


---

## Task 2

导入：

11个核心事件。


---

## Task 3

接入行情。


数据：

IM：

日线/分钟。


IH：

日线/分钟。


---

## Task 4

计算：

Spread：

\[
ln(IM)-ln(IH)
\]


---

## Task 5

生成：

Event Alpha Report。


---

# 九、第一阶段完成标准


完成后应该可以回答：


## 问题1

DeepSeek：

T+5/T+10是否真的IM Alpha？


## 问题2

小微盘：

2/1进入和2/5进入差多少？


## 问题3

924：

什么时候从IH切换IM？


## 问题4

哪些Channel最有效？


---

# 十、下一阶段 Phase 2

Phase 1完成后进入：

## Event Alpha Research


新增：

- 30-50个事件；
- 自动统计；
- Channel因子分析；
- PricingState验证。


然后进入：

## Phase 3

实时Event Engine。


---

这份可以直接交给 Codex 作为第一个开发任务。

下一步建议继续补：

**Phase 2：自动化历史事件数据库 + 行情接口 + 回测引擎详细设计**。
