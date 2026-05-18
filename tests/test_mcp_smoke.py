"""Phase 3: MCP server in-process smoke test.

Calls the tool dispatch directly (no stdio transport) to confirm wiring.
"""
from __future__ import annotations

import importlib
import os
import sys

import pytest

from kb.ingest import ingest_path


SAMPLE = """# 测试研报：动量因子

## 摘要
研究动量因子在高换手股票上的衰减。

## 主要结论
- 动量在高换手上失效
- 行业中性化改善
"""


def _seed_one(kb_root, meta, vstore, embedder):
    f = kb_root.raw / "test-动量.md"
    f.write_text(SAMPLE, encoding="utf-8")
    [r] = ingest_path(f, paths=kb_root, meta=meta, vstore=vstore, embedder=embedder)
    return r.source_id


@pytest.fixture
def mcp_module(kb_root):
    os.environ["KB_ROOT"] = str(kb_root.root)
    # Force-reload so _paths() picks up the new KB_ROOT for each test.
    sys.modules.pop("mcp_server.server", None)
    sys.modules.pop("mcp_server", None)
    return importlib.import_module("mcp_server.server")


def test_mcp_tools_registered(mcp_module):
    names = {t["name"] for t in mcp_module.TOOLS}
    expected = {
        "search", "fetch_source", "fetch_chunk",
        "list_threads", "new_thread", "get_thread", "review_thread",
        "propose_concept_stub", "save_memo", "compile", "run_lint", "doctor",
        "agentic_init", "agentic_new", "agentic_list", "agentic_gate",
    }
    missing = expected - names
    assert not missing, f"missing MCP tools: {missing}"


def test_mcp_search_and_fetch_source(mcp_module, kb_root, meta, vstore, embedder):
    sid = _seed_one(kb_root, meta, vstore, embedder)

    out = mcp_module.call_tool("search", {"query": "动量 换手", "top_k": 3})
    assert isinstance(out, dict) and "error" not in out, out
    hits = out.get("hits") or out.get("results") or []
    assert hits, out
    assert any(h["source_id"] == sid for h in hits)

    out = mcp_module.call_tool("fetch_source", {"source_id": sid})
    assert "error" not in out, out
    fm = out.get("frontmatter") or {}
    assert fm.get("id") == sid, out


def test_mcp_thread_lifecycle(mcp_module, kb_root):
    out = mcp_module.call_tool("new_thread", {"topic": "MCP 测试"})
    assert "error" not in out, out
    slug = out.get("slug") or out.get("thread_id")
    assert slug

    out = mcp_module.call_tool("list_threads", {})
    threads = out["threads"]
    assert threads, "no threads listed"
    # tolerate either {"id":..., "slug":...} or path-shaped entries
    matched = any(
        (isinstance(t, dict) and (t.get("slug") == slug or slug in (t.get("id") or "") or slug in (t.get("path") or "")))
        or (isinstance(t, str) and slug in t)
        for t in threads
    )
    assert matched, threads


def test_mcp_doctor_runs(mcp_module, kb_root):
    out = mcp_module.call_tool("doctor", {})
    assert "error" not in out, out
    assert "capabilities" in out
    assert "counts" in out


def test_mcp_unknown_tool_returns_error(mcp_module):
    out = mcp_module.call_tool("not_a_real_tool", {})
    assert "error" in out
