# 半自治 Agent 流程图

本流程图描述 `kb agentic` 的默认编排。核心原则是：agent 可以自治地产生候选和证据，但正式知识库写入必须经过固定 gate。

## 主流程

```mermaid
flowchart TD
    A["用户问题 / Thread"] --> B["kb agentic new"]
    B --> C["experiments/<id>/experiment.yaml"]

    C --> R["Research Agent<br/>检索 wiki / source / memo<br/>提出带引用假设"]
    R --> H["hypothesis<br/>statement / rationale / citations"]

    H --> F["Factor Agent<br/>转成受限 FactorSpec"]
    F --> FS["factor_spec.yaml<br/>inputs / operators / expression / constraints"]

    FS --> BT["Backtest Agent<br/>执行固定回测协议"]
    BT --> BR["backtest_result.json<br/>IC / Sharpe / turnover / cost / OOS"]

    BR --> CR["Critic Agent<br/>检查泄漏、成本、重复、引用"]
    CR --> RP["critic_report.yaml<br/>blockers / warnings / checks"]

    RP --> G["kb agentic gate <id><br/>固定门槛判定"]
    G -->|缺少结果或证据| HOLD["hold<br/>继续补证据 / 补回测"]
    G -->|指标或审计失败| RETIRE["retire<br/>保留失败记录"]
    G -->|全部通过| PROMOTE["promote_candidate<br/>允许起草正式因子卡"]

    HOLD --> C
    RETIRE --> ELOG["experiments/<id>/decision.yaml"]
    PROMOTE --> W["Wiki Steward<br/>写 inbox/factors/ 或 thread memo"]
    W --> HUMAN["人工确认"]
    HUMAN --> WF["wiki/factors/<factor-id>.md"]
```

## 写入边界

```mermaid
flowchart LR
    subgraph AUTO["允许自治写入"]
        E["experiments/<id>/"]
        IF["inbox/factors/"]
    end

    subgraph PROTECTED["受保护区域"]
        RAW["raw/"]
        CONV["converted/"]
        WF["wiki/factors/"]
    end

    AG["Agent Roles"] --> E
    AG --> IF
    AG -.禁止.-> RAW
    AG -.禁止.-> CONV
    AG -.需要 promote_candidate + 人工确认.-> WF
```

## Gate 口径

默认 gate 在 [src/kb/agentic.py](../src/kb/agentic.py) 中定义：

- `min_abs_ic_t: 3.0`
- `min_long_short_sharpe: 1.0`
- `max_turnover: 5.0`
- 必须有 OOS 窗口
- 必须有交易成本结果
- critic 不得有 blockers

缺少必要字段时默认 `hold`；明确低于门槛或有 blocker 时 `retire`；全部通过才是 `promote_candidate`。
