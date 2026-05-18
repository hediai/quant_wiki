# quant-wiki

本地优先的量化研究知识库。把研报持续编译成可维护的 Markdown 知识库，由 Codex/Claude Code 整理、检索、生成带引用的研究备忘录，Obsidian 浏览。

## 30 秒上手

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[minimal]'

kb ingest samples/                                     # 试导入两份样例
kb compile src-2024-...                                # 生成 Source Card
kb thread new "动量调研"
kb ask "动量因子在高换手股票上是否失效？" --thread <thread-id>
kb agentic init                                      # 生成半自治 agent 角色卡
kb agentic new "高换手动量衰减" --thread <thread-id> # 新建因子实验沙盒
kb doctor                                              # 看缺哪些可选模块
```

完整安装与 MCP/Obsidian 接入见 **[USAGE.md](USAGE.md)**。

## 三件套

- **CLI**：`kb` 命令（[src/kb/cli.py](src/kb/cli.py)），完成 ingest/search/compile/ask/lint/eval
- **MCP server**：`kb-mcp`（[mcp_server/server.py](mcp_server/server.py)），让 Claude Code/Codex 原生调用 12 个工具
- **Obsidian vault**：直接打开 `wiki/`，主页 [wiki/_dashboard/Home.md](wiki/_dashboard/Home.md)

## 设计文档

- [AGENTS.md](AGENTS.md)：AI 协作规则（必读）
- [kb.schema.md](kb.schema.md)：命名、字段、引用约定
- [USAGE.md](USAGE.md)：完整操作手册
- [docs/agentic-flow.md](docs/agentic-flow.md)：半自治 agent 编排流程图
- 实施方案 v2：`~/.claude/plans/summary-adaptive-patterson.md`

## 目录

- `raw/` 原始资料（只读）
- `converted/` 解析产物（可重建）
- `wiki/` 长期资产，Obsidian vault
- `experiments/` 半自治因子实验沙盒（agent 输出先落这里）
- `agents/` 半自治 agent 角色卡与写入边界
- `index/` SQLite + LanceDB 索引 + 评估数据
- `src/kb/` Python 包
- `mcp_server/` MCP server
- `tests/` pytest
