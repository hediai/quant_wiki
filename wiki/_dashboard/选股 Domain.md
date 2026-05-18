---
id: domain-stock-selection
type: dashboard
title: 选股 Domain 地图
domain: 选股
---

# 选股 Domain 地图

## Sources

```dataview
TABLE WITHOUT ID
  link(file.link, title) as 报告,
  institution as 机构,
  date as 日期,
  tags as 标签
FROM "sources"
WHERE contains(domains, "选股")
SORT date DESC
```

## Concepts

```dataview
LIST
FROM "concepts"
WHERE contains(domains, "选股") OR contains(tags, "选股")
SORT file.name
```

## Factors

```dataview
TABLE WITHOUT ID
  link(file.link, title) as 因子,
  implementation.module as 实现,
  implementation.last_backtest.sharpe as Sharpe
FROM "factors"
WHERE contains(domains, "选股")
```

## 相关 Threads

```dataview
LIST
FROM "threads"
WHERE contains(domains, "选股") OR contains(file.path, "dong-liang") OR contains(file.path, "xuan-gu")
```
