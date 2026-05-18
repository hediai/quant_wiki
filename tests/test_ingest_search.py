"""End-to-end Phase 1 sanity: ingest → search → compile → lint."""
from __future__ import annotations

from pathlib import Path

from kb.compile import compile_source
from kb.ingest import ingest_path
from kb.lint import lint
from kb.search import search


SAMPLE = """# 测试研报：动量因子

## 摘要

研究动量因子在高换手股票上的衰减情况。

## 主要结论

- 动量因子在高换手股票上失效
- 换手率分桶后多空收益显著
- 行业中性化改善因子表现

## 方法

按 60 日均换手率分 5 组回测。
"""


def _seed(kb_root, name: str = "测试-动量-2024.md"):
    raw = kb_root.raw / name
    raw.write_text(SAMPLE, encoding="utf-8")
    return raw


def test_ingest_writes_manifest_and_card(kb_root, meta, vstore, embedder):
    raw = _seed(kb_root)
    results = ingest_path(raw, paths=kb_root, meta=meta, vstore=vstore, embedder=embedder)
    assert len(results) == 1
    r = results[0]
    assert not r.skipped
    assert r.chunk_count >= 1
    sid = r.source_id

    manifest = kb_root.converted / sid / "manifest.json"
    assert manifest.exists()
    card = kb_root.sources / f"{sid}.md"
    assert card.exists()


def test_duplicate_hash_is_skipped(kb_root, meta, vstore, embedder):
    raw = _seed(kb_root)
    ingest_path(raw, paths=kb_root, meta=meta, vstore=vstore, embedder=embedder)
    again = ingest_path(raw, paths=kb_root, meta=meta, vstore=vstore, embedder=embedder)
    assert again[0].skipped
    assert "duplicate" in again[0].reason


def test_search_returns_relevant_hit(kb_root, meta, vstore, embedder):
    _seed(kb_root)
    ingest_path(_seed(kb_root, "another-动量-2024.md"), paths=kb_root, meta=meta, vstore=vstore, embedder=embedder)
    results = search("动量 换手率 衰减", meta=meta, vstore=vstore, embedder=embedder, top_k=3, rerank=False)
    assert results
    assert any("动量" in r.text for r in results)


def test_compile_enriches_card(kb_root, meta, vstore, embedder):
    raw = _seed(kb_root)
    [r] = ingest_path(raw, paths=kb_root, meta=meta, vstore=vstore, embedder=embedder)
    result = compile_source(r.source_id, paths=kb_root, meta=meta, aggregate_evidence=False)
    body = result.card_path.read_text(encoding="utf-8")
    assert "关键结论" in body
    assert "动量因子在高换手股票上失效" in body
    assert "Changelog" in body


def test_lint_passes_after_compile(kb_root, meta, vstore, embedder):
    raw = _seed(kb_root)
    [r] = ingest_path(raw, paths=kb_root, meta=meta, vstore=vstore, embedder=embedder)
    compile_source(r.source_id, paths=kb_root, meta=meta, aggregate_evidence=False)
    findings = lint(kb_root)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors, [str(f) for f in errors]


def test_as_of_filter_excludes_future_sources(kb_root, meta, vstore, embedder):
    raw = _seed(kb_root)
    ingest_path(raw, paths=kb_root, meta=meta, vstore=vstore, embedder=embedder)
    # All sources get ingested with today's date as as_of; filter to a past date
    # should yield no hits.
    results = search(
        "动量", meta=meta, vstore=vstore, embedder=embedder,
        top_k=5, as_of="2000-01-01", rerank=False,
    )
    assert not results
