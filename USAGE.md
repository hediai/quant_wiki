# USAGE — quant-wiki 操作手册

本仓库 = 量化研究知识库。所有 KB 操作通过 `kb` 命令或 MCP 工具完成。

---

## 1. 一次性安装

```bash
cd /Users/hedi_ai/wiki

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 最小可用（FTS + jieba + 哈希 embedder，纯 Python）
pip install -e .

# 推荐：Office/PDF 解析 + LanceDB 向量
pip install -e '.[parsers,index]'

# 大模型综合 + 重排（首次会下载 bge-m3 与 reranker 模型，约 4GB）
pip install -e '.[embed]'

# 真 LLM 综合（Claude）
pip install -e '.[anthropic]'
export ANTHROPIC_API_KEY=sk-ant-...

# MCP server（让 Claude Code / Codex 原生调用）
pip install -e '.[mcp]'

# 一把梭
pip install -e '.[full]'
```

`kb doctor` 会告诉你少装了哪些可选项。

---

## 2. 日常工作流

### 2.1 导入研报

```bash
# 单文件
kb ingest path/to/中信证券-动量因子-2024.pdf --domain 选股 --institution 中信证券

# 批量目录
kb ingest raw/选股/2024/ --domain 选股
```

每个文件会：sha256 去重 → 选解析器（MarkItDown / Docling / Marker / pypdf）→ 写
`converted/<source_id>/{doc.md, manifest.json, tables/, figures/}` → 切块入索引 →
建 stub Source Card 在 `wiki/sources/`。

### 2.2 编译 Source Card + 概念演化

```bash
kb compile src-2024-citic-momentum-001
```

- 抽取摘要、关键结论、方法段，写入 Source Card。
- 把每条结论当作 claim：相似 Concept 在阈值之上 → 自动追加到 Evidence For/Against；冲突
  → 标记 concept `status: disputed` 并写入 `index/conflicts.jsonl`；无匹配 → 在
  `inbox/concepts/` 留 stub 候选。

### 2.3 检索

```bash
kb search "动量因子换手率衰减"
kb search "Risk Parity" --as-of 2022-12-31 --top-k 10
kb search "因子拥挤度" --domain 选股 --json
```

混合检索（FTS + 向量 → reranker）+ `as_of` 时间切片 + 半衰期软衰减权重。

### 2.4 研究项目（threads）

```bash
kb thread new "动量因子换手率影响"
# 输出 thread id，例 thread-dong-liang-yin-zi-huan-shou-lu-ying-xiang-2026q2

# 在 thread 下问问题、写带引用的 memo
kb ask "动量在高换手股票上是否失效？" --thread thread-dong-liang-...-2026q2

# 阶段性总结：聚合 thread 下所有 memo
kb thread review thread-dong-liang-...-2026q2
```

### 2.5 因子卡 + factor_mining 联动

```bash
# 建因子卡
kb factor new momentum --version 3 --domain 选股

# 关联代码 + 回测
kb factor link factor-momentum-v3 \
  --repo /Users/hedi_ai/factor_mining \
  --module factors/momentum/v3.py \
  --backtest outputs/2026-04/momentum_v3.json

# 校验所有因子卡
kb factor validate
```

`link` 会读取仓库 HEAD commit，写入 frontmatter；后续 git 改动会被 `kb lint`
检测出"已 drift"。

### 2.6 半自治因子实验（agentic sandbox）

```bash
# 生成 agent 角色卡与沙盒目录
kb agentic init

# 新建一个受保护的因子实验
kb agentic new "高换手动量衰减" \
  --thread thread-dong-liang-...-2026q2 \
  --hypothesis "高换手股票上的动量信号可能反转" \
  --citation "[^src-2024-...#page-1]"

# 查看实验
kb agentic list

# 回测和 critic 写完后，由固定 gate 决定 promote_candidate / hold / retire
kb agentic gate exp-2026-...
```

半自治流程的默认写入边界：

| 区域 | 策略 |
|---|---|
| `experiments/<id>/` | 允许 agent 写入实验记录、FactorSpec、回测结果、critic 报告 |
| `inbox/factors/` | 允许写候选因子草稿 |
| `wiki/factors/` | 只有 gate 返回 `promote_candidate` 且人工明确要求后才写 |
| `raw/` / `converted/` | 禁止自治写入 |

角色卡生成在 `agents/`：

- `orchestrator.md`：调度、检查写入边界、运行 gate
- `research.md`：从 wiki 检索证据，提出带引用假设
- `factor.md`：把假设转成受限 `factor_spec.yaml`
- `backtest.md`：按统一协议写 `backtest_result.json`
- `critic.md`：检查泄漏、成本、重复因子、引用支撑
- `wiki-steward.md`：只在 gate 后写研究记忆或候选草稿

流程图见 [docs/agentic-flow.md](docs/agentic-flow.md)。

### 2.7 体检 / Lint / 评估

```bash
kb doctor                  # 能力、计数、待办建议
kb lint --strict           # 缺引用 / 断链 / factor 校验 / conflicts / regressions
kb eval                    # 跑 golden set + memo citation faithfulness
kb eval --skip-faithfulness
```

---

## 3. 在 Claude Code / Codex 里使用（MCP）

### 3.1 启动 MCP server

```bash
# 一次性测试
KB_ROOT=/Users/hedi_ai/wiki python -m mcp_server.server
# 或
kb-mcp
```

### 3.2 在 Claude Code 注册

```bash
claude mcp add quant-wiki -- /Users/hedi_ai/wiki/.venv/bin/kb-mcp
# 然后在 Claude Code 内会看到下列工具
```

或编辑 `~/.claude/mcp.json`：

```json
{
  "mcpServers": {
    "quant-wiki": {
      "command": "/Users/hedi_ai/wiki/.venv/bin/kb-mcp",
      "env": {
        "KB_ROOT": "/Users/hedi_ai/wiki",
        "KB_LLM": "anthropic",
        "ANTHROPIC_API_KEY": "..."
      }
    }
  }
}
```

### 3.3 暴露的工具

| Tool | 用途 |
|---|---|
| `search` | 混合检索，返回带引用的 hit |
| `fetch_source` | 取 Source Card + manifest |
| `fetch_chunk` | 取单 chunk 原文 |
| `list_threads` / `get_thread` / `new_thread` / `review_thread` | 研究项目档案管理 |
| `propose_concept_stub` | 写一个概念候选 stub（不自动晋升） |
| `save_memo` | 检索 + 综合 + 写 memo 到 thread |
| `compile` | 生成/刷新 Source Card 并跑概念证据聚合 |
| `run_lint` / `doctor` | 健康检查 |
| `agentic_init` / `agentic_new` / `agentic_list` / `agentic_gate` | 半自治因子实验沙盒 |

CLI 与 MCP 共享同一份后端逻辑（`src/kb/`）。

---

## 4. Obsidian 阅读

把 `wiki/` 直接作为 Obsidian vault 打开。

- `wiki/_dashboard/Home.md` 是主页，渲染最近的 sources / 活跃 concepts / factors / threads。
- 推荐启用插件（已在 `wiki/.obsidian/community-plugins.json` 列出）：
  - **Dataview**：渲染 dashboard 表格
  - **Templater**：用 `wiki/_templates/` 下的 Source/Concept/Thread 模板
  - **Graph Analysis**：看引用图谱
- `wiki/.obsidian/graph.json` 已经按目录给节点上色（sources/concepts/factors/threads/outputs）。

---

## 5. 配置环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `KB_ROOT` | KB 根目录（仓库外用） | 自动从 `kb.schema.md` 探测 |
| `KB_LLM` | `anthropic` / `heuristic` / `auto` | `auto` |
| `KB_VLM` | `claude` / `heuristic` | `heuristic` |
| `ANTHROPIC_API_KEY` | 启用 Anthropic 后端 | — |
| `ANTHROPIC_MODEL` | 模型 id | `claude-sonnet-4-6` |
| `KB_EMBED_MODEL` | embedder 名 | `BAAI/bge-m3` |
| `KB_RERANK_MODEL` | reranker 名 | `BAAI/bge-reranker-v2-m3` |
| `KB_CHUNK_SIZE` / `KB_CHUNK_OVERLAP` | 切块参数 | 800 / 120 |
| `KB_HALF_LIFE_DAYS` | 时间衰减半衰期 | 730 |
| `FACTOR_MINING_REPO` | 显式指向 factor_mining 仓 | 自动探测 sibling 目录 |

---

## 6. 治理规则

- 任何写入 `wiki/` 的事实性结论必须带 `[^src-id#page-x]` 引用脚注（`kb lint` 强制）。
- `raw/` 永远只读；解析失败也不要重命名原文，错误写入 `manifest.json.errors`。
- `converted/` 是可重建产物，不要手工编辑——重新 `kb ingest` 即可。
- 概念页演化不要静默改写：触发 contradiction 时进 `disputed`，人工审。
- Memo 默认进 thread，未归类的进 `wiki/outputs/`，超过 5 条 lint 会提醒。
- 详细 AI 协作规则见 [AGENTS.md](AGENTS.md)。

---

## 7. 常见排错

- **`kb` 找不到 root**：当前目录或父级缺 `kb.schema.md`，或设 `export KB_ROOT=/Users/hedi_ai/wiki`。
- **search 全是 `hash-fallback`**：缺 sentence-transformers，跑 `pip install -e '.[embed]'`。
- **rerank 没启用**：缺 FlagEmbedding，同上。
- **kb-mcp 提示缺包**：`pip install -e '.[mcp]'`。
- **PDF 解析失败**：`kb doctor` 看 capabilities；装 `parsers-heavy` 后再 ingest 一次（旧 source_hash 不会重导，可手动删除 `converted/<id>/` 与 `wiki/sources/<id>.md` 后重试）。
