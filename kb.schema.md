# kb.schema.md — 命名、字段、引用约定

## ID 规则

- Source: `src-<YYYY>-<institution-slug>-<topic-slug>-<3digit>`，例 `src-2024-citic-momentum-002`
- Concept: `concept-<topic-slug>`，例 `concept-momentum-decay`
- Factor: `factor-<name>-<version>`，例 `factor-momentum-v3`
- Strategy: `strategy-<name>`
- Model: `model-<arch>-<variant>`，例 `model-transformer-ts-v1`
- Thread: `thread-<topic-slug>-<YYYYqQ>`，例 `thread-momentum-turnover-2026q2`
- Memo: `memo-<YYYY-MM-DD>-<query-slug>-<4hex>`
- Experiment: `exp-<YYYY-MM-DD>-<topic-slug>-<4hex>`，例 `exp-2026-05-18-turnover-momentum-a1b2`

所有 ID 仅含 `[a-z0-9-]`，长度 ≤ 80。

## 通用 frontmatter 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✓ | 见 ID 规则 |
| `type` | enum | ✓ | source / concept / factor / strategy / model / thread / memo |
| `title` | string | ✓ | 显示名 |
| `domains` | list[str] | ✓ | 选股 / 资产配置 / 机器学习 / 深度学习 / 通用方法 |
| `asset_classes` | list[str] |  | A股 / 港股 / 美股 / 商品 / 利率 / 外汇 / 多资产 |
| `tags` | list[str] |  | 自由标签 |
| `status` | enum | ✓ | active / disputed / deprecated / superseded / failed / retracted |
| `as_of` | date | ✓ (source/factor/concept) | 结论所述时点 |
| `last_reviewed` | date |  | 上次人工 review 时间 |

## Source Card 专有

| 字段 | 必填 | 说明 |
|---|---|---|
| `institution` | ✓ | 机构名 |
| `authors` |  | 作者列表 |
| `date` | ✓ | 报告日期，默认作为 `as_of` |
| `license` | ✓ | public / subscription / internal |
| `source_hash` | ✓ | 原文 sha256（自动） |
| `parser` | ✓ | docling / marker / markitdown / mixed |
| `parser_version` | ✓ | 解析器版本（自动） |
| `ingested_at` | ✓ | 自动 |
| `raw_path` | ✓ | 相对 `raw/` 路径 |

## Concept Card 正文段（顺序固定）

1. `## 定义`（≤ 100 字，可含一条 canonical 引用）
2. `## 关键结论`（短陈述，每条带引用）
3. `## Evidence For`（由 `kb compile` 自动聚合）
4. `## Evidence Against`（同上）
5. `## 适用条件`
6. `## 相关`（双链到其他 concept/factor/strategy）
7. `## Changelog`

## Factor Card 专有 frontmatter

```yaml
implementation:
  repo_path: /Users/hedi_ai/factor_mining   # 绝对路径或相对路径
  module: factors/momentum/v3.py            # 相对 repo_path
  commit: null                              # 写入时填 git sha
  last_backtest:
    path: outputs/2026-04/momentum_v3.json
    sharpe: 1.2
    ic: 0.04
performance_over_time:
  - period: 2010-2015
    ic_mean: 0.06
    source: src-...
```

## Thread frontmatter

```yaml
status: exploring  # exploring | paused | shipped | abandoned
hypotheses: ["..."]
open_questions: ["..."]
sources_read: []
sources_queue: []
started_at: 2026-04-10
```

## Memo frontmatter

```yaml
thread: thread-... | null
query: "..."
as_of_filter: 2024-12-31
retrieval:
  top_k: 10
  reranker: bge-reranker-v2-m3
  hit_ids: [src-...#p5, ...]
model: claude-opus-4-7
created_at: 2026-05-13
```

## Agentic Experiment 文件

半自治因子实验默认写在 `experiments/<experiment-id>/`，不是正式 wiki 资产。

```yaml
id: exp-...
type: agentic_experiment
status: draft | reviewed
decision: hold | retire | promote_candidate
autonomy: semi
topic: "..."
thread: thread-... | null
hypothesis:
  statement: "..."
  rationale: "..."
  citations: ["[^src-...#page-1]"]
paths:
  factor_spec: factor_spec.yaml
  backtest_result: backtest_result.json
  critic_report: critic_report.yaml
gate:
  min_abs_ic_t: 3.0
  min_long_short_sharpe: 1.0
```

正式 `wiki/factors/` 只能在 `decision: promote_candidate` 后由人工明确确认写入；其他自治产物应留在
`experiments/` 或 `inbox/factors/`。

## 引用格式

- 研报：`[^src-id#page-x]`（脚注定义可省略，由 lint 自动补齐）
- 回测：`[^backtest:<path>]`
- 概念双链：`[[concepts/<slug>]]`
- 跨概念证据：在 Concept Card 的 `Evidence For` 段使用 `- [src-id#page-x] 摘要`

## 命名禁忌

- 不用空格、不用中文标点、不用大写字母作为 ID 一部分。
- ID 一旦写入索引不可改名；需重命名则建新 ID + 旧 ID 设 `superseded_by`。
