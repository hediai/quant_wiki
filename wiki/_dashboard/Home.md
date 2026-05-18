---
id: home
type: dashboard
title: quant-wiki 主页
---

# 量化研究知识库

> 本页是 Obsidian 阅读入口。需启用 Dataview 插件以渲染下方列表。

## 最近 Source Cards

```dataview
TABLE WITHOUT ID
  link(file.link, title) as 报告,
  institution as 机构,
  date as 日期,
  domains as 领域,
  status as 状态
FROM "sources"
WHERE type = "source"
SORT date DESC
LIMIT 20
```

## Concepts（活跃 / 争议）

```dataview
TABLE WITHOUT ID
  link(file.link, title) as 概念,
  status as 状态,
  last_reviewed as 上次审阅
FROM "concepts"
WHERE type = "concept"
SORT status DESC, last_reviewed DESC
```

## Factors

```dataview
TABLE WITHOUT ID
  link(file.link, title) as 因子,
  implementation.module as 实现,
  implementation.last_backtest.sharpe as Sharpe,
  implementation.last_backtest.ic as IC,
  status as 状态
FROM "factors"
WHERE type = "factor"
SORT status, file.name
```

## 研究项目（Threads）

```dataview
TABLE WITHOUT ID
  link(file.link, title) as 项目,
  status as 状态,
  started_at as 开始,
  length(sources_read) as 已读数
FROM "threads"
WHERE type = "thread"
SORT status, started_at DESC
```

## 待办

- inbox/concepts/ 里的候选概念：用 `kb concept new` 或人工编辑提升为正式 concept 页
- index/conflicts.jsonl：用 `kb lint` 看到的 contradiction 列表
- wiki/outputs/：未归入 thread 的 memo
