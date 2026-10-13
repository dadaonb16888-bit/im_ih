# CODEX_TASK_PHASE1_EVENT_ENGINE.md

# IM_IH Event Engine Phase 1 Development Task

Version: V1.0

Purpose: Provide Codex with an implementation specification for upgrading the existing Event Engine into an Event Alpha Engine.

---

# 1. Development Objective

The current project has implemented an Event Research Layer:

```
Parent Event
    ↓
Event Update
    ↓
State Update
```

Phase 1 objective:

Upgrade it into:

```
Market Information
    ↓
Event Detection
    ↓
Parent Event
    ↓
Event Update
    ↓
State Update
    ↓
Event Alpha
    ↓
IM/IH Bias Output
```

The Event Engine must eventually answer:

1. What happened?
2. Which market channel does it belong to?
3. Which style benefits: IM or IH?
4. How strong is the impact?
5. How long can the effect persist?
6. Is the event currently tradable?

---

# 2. Development Principles

Do not rewrite the existing project.

Preserve:

- event_engine
- database
- dashboard
- workbench
- existing research workflow

Implement incrementally.

No trading execution should be developed in this phase.

---

# 3. Files To Modify

## Existing files

Review and upgrade:

```
event_engine/event.py

event_engine/event_update.py

event_engine/event_state.py
```

Required changes:

Add fields required for Event Alpha calculation.

---

# 4. New Files To Add

Create:

```
event_engine/

    channel.py
    scoring.py
    decay.py
    dominance.py
    confidence.py
```

---

# 5. Data Structure Design

## Event Object

```python
Event:

{
    event_id,
    event_name,
    event_time,
    first_tradable_time,

    channel,
    horizon,
    bias,
    invalidation,

    source,
    source_reliability,

    impact_score,
    confidence_score,
    persistence_score,

    event_strength,
    affected_style,
    status
}
```

---

# 6. Event Channel Mapping

Implement channel mapping.

Required channels:

```
TECH_GROWTH
DIRECT_SMALLCAP_LIQUIDITY
DIRECT_LARGECAP
MARKET_LIQUIDITY
CREDIT_LARGECAP
REGULATION_QUALITY
RISK_APPETITE
RISK_OFF
MARKET_STABILIZATION
```

Each channel should provide default IM/IH impact mapping.

Example:

```
TECH_GROWTH

IM impact: positive
IH impact: neutral
Bias: Strong IM
```

---

# 7. Event Score Engine

Implement:

```
Event Score =
Impact
×
Confidence
×
Persistence
×
Freshness
```

Components:

## Impact Score

Range:

0-5

## Confidence Score

Range:

0-1

## Persistence Score

Based on horizon:

```
Fast
Swing
Trend
```

## Freshness

Time decay function.

Example:

```
Freshness = exp(-days / decay_period)
```

---

# 8. Event Update Enhancement

Event Update must measure information change.

Add:

```
information_gain
bias_change
channel_change
score_change
```

Example:

Initial:

AI theme

Update:

Industry order confirmation

Result:

Event score increases.

---

# 9. State Engine Enhancement

Maintain:

```
Fresh
Diffusing
Crowded
Reversing
```

Add automatic transition logic.

Example:

Fresh:

new event detected.

Diffusing:

market begins accepting event.

Crowded:

event already priced in.

Reversing:

event impact weakening.

---

# 10. Dominant Event Engine

Create:

```
dominance.py
```

Input:

```
Event Pool
```

Output:

```
Dominant Event
```

Example output:

```json
{
    "event": "DeepSeek AI Revaluation",
    "score": 4.5,
    "bias": "Strong IM",
    "confidence": 0.82
}
```

---

# 11. Database Requirements

Extend database tables.

## events

Required fields:

```
event_id
name
channel
horizon
bias
impact
confidence
score
created_time
status
```

## event_updates

```
event_id
update_time
information_gain
bias_change
channel_change
```

## event_states

```
event_id
timestamp
pricing_state
acceptance
event_score
```

---

# 12. Test Cases

## Test 1: DeepSeek AI Event

Input:

```
TECH_GROWTH
```

Expected:

```
Bias: Strong IM
```

---

## Test 2: Small Cap Liquidity Crisis

Input:

```
DIRECT_SMALLCAP_LIQUIDITY
```

Expected:

```
Bias: Strong IH
```

---

## Test 3: Event Decay

Create historical event.

Verify score decreases with time.

---

## Test 4: Multiple Events

Input:

```
AI event
Risk off event
Liquidity event
```

Expected:

Return highest scoring dominant event.

---

# 13. Acceptance Criteria

Phase 1 is complete when:

## Requirement 1

Event can produce quantitative score.

## Requirement 2

Event can produce IM/IH directional bias.

## Requirement 3

Multiple events can be ranked.

## Requirement 4

Event state can identify:

- Fresh
- Diffusing
- Crowded
- Reversing

## Requirement 5

Output interface exists for future Spread Engine.

Example:

```json
{
    "dominant_event": "AI Theme",
    "bias": "Strong IM",
    "confidence": 0.82,
    "trade_permission": true
}
```

---

# Final Goal

Build the bridge:

```
Event
 ↓
Event Alpha
 ↓
IM/IH Bias
 ↓
Spread Trading System
```

This phase creates the foundation for the complete IM_IH Event Driven Relative Value Trading System.
