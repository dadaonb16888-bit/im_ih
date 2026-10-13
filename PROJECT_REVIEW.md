# IM_IH Project Review V1.0

## 1. Review Purpose

This document is the engineering audit baseline for the IM/IH Event Driven Relative Value Trading System.

Target architecture:

Market Data
↓
Event Engine
↓
Parent Event
↓
Event Update
↓
State Update
↓
Dominant Event Engine
↓
IM/IH Bias
↓
Spread Engine
↓
Timing Engine
↓
Execution

## 2. Current Project Assessment

Current classification:

C. Between ordinary IM/IH spread strategy and full Event Driven Relative Value System.

Current positioning:

Event Driven Research Infrastructure.

The project has implemented the event research layer, but the trading alpha layer is incomplete.

Estimated completion:

- Event Research: 70%
- Event Database: 80%
- Event State Management: 80%
- Alpha Model: 10%
- Spread Model: 10%
- Backtest: 0%
- Execution: 0%

## 3. Current Strengths

Implemented:

- Parent Event
- Event Update
- State Update
- Event Database
- Research workflow
- Dashboard/workbench

The current Event Engine is the foundation and should be retained.

## 4. Main Architecture Gaps

Missing:

1. Market Data Layer
2. Dominant Event Engine
3. IM/IH Bias Engine
4. Spread Engine
5. Timing Engine
6. Backtest Engine
7. Execution Layer

## 5. Required Refactor

### Must Modify

Add modules:

```
market_data/
    futures.py
    contract.py
    continuous.py
    basis.py

event_alpha/
    dominant_event.py
    event_score.py
    confidence.py

bias_engine/
    bias.py
    channel_mapping.py

spread_engine/
    spread.py
    beta.py
    volatility.py
    roll.py

timing_engine/
    trend.py
    breakout.py
    signal.py

backtest/
    engine.py
    cost.py
    performance.py
```

## 6. Trading Logic Requirements

Event must drive trading:

Event
↓
Dominant Event
↓
IM/IH Bias
↓
Spread Direction
↓
Timing Signal
↓
Execution

The system must avoid:

- future data leakage
- look ahead bias
- unrealistic fills
- missing transaction costs

## 7. Spread Model Requirements

Base definition:

Spread = ln(IM) - ln(IH)

Must include:

- Beta adjustment
- Volatility adjustment
- Basis handling
- Contract rollover handling

## 8. Development Roadmap

### Phase 1

Build Event Alpha layer:

Event → Dominant Event → IM/IH Bias

### Phase 2

Build historical market data and Spread Engine.

### Phase 3

Validate Event Alpha using historical events.

Required outputs:

- T+1 Spread Return
- T+3 Spread Return
- T+5 Spread Return
- T+10 Spread Return
- Maximum Profit
- Maximum Drawdown

### Phase 4

Real-time monitoring system.

### Phase 5

Execution system.

## 9. Instructions For Codex

Do not rewrite the project from scratch.

Preserve:

- event_engine
- database
- dashboard
- research workflow

Implement incrementally according to the roadmap.

First priority:

Build Event Alpha layer and connect Event Engine to IM/IH trading logic.

The final objective:

Event Alpha + Relative Value + Execution Timing.
