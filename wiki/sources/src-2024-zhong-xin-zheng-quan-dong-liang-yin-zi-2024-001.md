---
id: src-2024-zhong-xin-zheng-quan-dong-liang-yin-zi-2024-001
type: source
title: 中信证券-动量因子-2024
institution: 中信证券
authors: []
date: '2026-05-13'
as_of: '2026-05-13'
domains:
- 选股
asset_classes: []
tags: []
license: internal
source_hash: de53d3d9023a9df2f6428d80686e91e814f692b1a08c9f120294a58f9b8b5069
parser: stub
parser_version: plain-1
status: active
raw_path: /Users/hedi_ai/wiki/samples/中信证券-动量因子-2024.md
ingested_at: '2026-05-13T15:02:20'
---

# 中信证券-动量因子-2024

## 摘要

本文为 quant-wiki Phase 1 smoke test 用样例，非真实研报。

## 关键结论

- 全样本动量因子 RankIC 均值 0.03，2020 年后衰减至 0.01  [^src-2024-zhong-xin-zheng-quan-dong-liang-yin-zi-2024-001#page-1]
- 在高换手率分位（top 20%）的股票上，动量因子甚至出现反转，10 日反转收益显著  [^src-2024-zhong-xin-zheng-quan-dong-liang-yin-zi-2024-001#page-1]
- 行业中性化后动量效应回归弱化但仍存在  [^src-2024-zhong-xin-zheng-quan-dong-liang-yin-zi-2024-001#page-1]
- Barra 风险模型分解显示残差动量贡献了大部分超额收益  [^src-2024-zhong-xin-zheng-quan-dong-liang-yin-zi-2024-001#page-1]

## 方法

- 样本：沪深 A 股全市场，剔除 ST 与上市未满 1 年股票
- 因子定义：过去 20 日累计收益
- 换手率分桶：按 60 日平均换手率分 5 组
- 评估指标：分组超额收益、IC、RankIC、Long-Short Sharpe

## 引用

converted: [doc.md](../../converted/src-2024-zhong-xin-zheng-quan-dong-liang-yin-zi-2024-001/doc.md)、manifest: [manifest.json](../../converted/src-2024-zhong-xin-zheng-quan-dong-liang-yin-zi-2024-001/manifest.json)

## Changelog

- 2026-05-13T15:02:20: `kb compile` 自动生成草稿
