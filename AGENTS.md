# AGENTS.md — Codex / Claude Code 协作规则

本仓库是一个**本地优先的量化研究知识库**。AI agent（Codex、Claude Code 等）在本仓库内工作时，必须遵守以下规则。

## 不可违反的核心规则

1. **结论必带引用**。任何事实性陈述、数字、结论必须以脚注形式给出来源：
   - 来自研报：`[^src-id#page-x]`，例如 `动量因子在 2020–2024 IC 均值 0.01[^src-2024-citic-momentum-002#page-7]`
   - 来自回测：`[^backtest:outputs/2026-04/momentum_v3.json]`
   - 来自概念页本身：`[[concepts/momentum-decay]]`
2. **不修改 `raw/`**。原始资料永远只读；解析失败时把错误写入 `converted/<id>/manifest.json` 的 `errors` 字段，不要重命名或删除原文。
3. **不直接编辑 `converted/`**。该目录由 `kb ingest` 重建。手动修订应改 `wiki/sources/<id>.md` 或重新 ingest。
4. **写入 `wiki/` 前先检查重复**。`kb compile` 应在更新前比对 frontmatter `source_hash`，避免重复 Source Card。
5. **不向云端发送原始 PDF/Office 文件**。云模型仅允许接收：检索返回的小片段、用户明确允许的图表 PNG（用于 VLM 描述）。

## 引用与忠实度

- 写 memo 时，每个 claim 至少挂一条引用；无法引用的判断需用 `> 推断：…` 块标记。
- 引用 chunk 的内容必须真实支持 claim；`kb eval` 会跑 citation faithfulness 检查，假引用会计入回归。
- 不允许"洗稿式"复述：引用片段时优先保留原文专有名词、数字、公式。

## 概念页演化

- 给概念页加证据时，写入 `## Evidence For` 或 `## Evidence Against` 段，格式：
  ```
  - [src-id#page-x] 一句话摘要（保留原文关键词）
  ```
- 发现新结论与已有概念矛盾 → 不要静默改写，触发 `kb compile` 的 contradiction detection，让人审。
- 修改概念页正文的"定义"或"结论"段必须追加 Changelog 行：
  ```
  ## Changelog
  - 2026-05-13: 据 [src-...] 将适用条件从 X 改为 Y
  ```

## Threads（研究项目档案）

- 每次 `kb ask` 强烈建议带 `--thread <id>`；无 thread 的 memo 进 `wiki/outputs/`，由 `kb lint` 提示归类。
- 新发现可能开辟独立课题时，建议先 `kb thread new`，再继续写 memo。

## 半自治因子实验

- 多 agent 因子发现必须先落在 `experiments/<id>/`，并使用 `kb agentic new` 生成标准 handoff 文件。
- agent 默认只能写 `experiments/<id>/` 与 `inbox/factors/`；不得自治写入 `wiki/factors/`。
- `wiki/factors/` 只能在 `kb agentic gate <id>` 返回 `decision=promote_candidate` 后，由人明确要求再写。
- Research Agent 负责证据与假设；Factor Agent 负责 `factor_spec.yaml`；Backtest Agent 负责 `backtest_result.json`；Critic Agent 负责泄漏、成本、重复因子、引用支撑检查。
- 任何实验缺少 OOS 窗口、交易成本结果、IC t-stat 或 long-short Sharpe 时，默认 `hold`，不得包装成有效因子。

## 工具调用偏好

- 优先用 MCP server（Phase 3 起）；调试或脚本场景用 CLI（`scripts/cli.py`）。
- 检索默认走 `kb search`；不要绕过索引去 `grep raw/`。
- 大批量 ingest 用 `kb ingest <dir>`；单文件用 `kb ingest <file>`。

## 失败模式与降级

- 解析失败的 PDF：尝试 `docling → marker → OCR`，仍失败则把错误记 `manifest.json.errors`，建立 stub Source Card（status=`failed`），不要伪造正文。
- 网络/模型不可用时（离线）：检索仍可用关键词通道；语义检索关闭后给出明确警告。
- 引用 chunk 找不到了（哈希不匹配）：lint 报错，不要"修复"成相似页码。

## 不做什么

- 不主动建 canonical 经典概念种子页（已显式放弃）。
- 不写 Web UI、不接外部 API（除非新 plan 允许）。
- 不引入云数据库（默认本地优先）。
- 不在 `wiki/` 里写超过 200 行无引用的"综述"，鼓励多个短 memo + 概念页聚合。
