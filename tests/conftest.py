"""Shared fixtures: spin up an isolated KB root in a tmp dir per test."""
from __future__ import annotations

from pathlib import Path

import pytest

from kb.config import Paths
from kb.index import MetaStore, VectorStore, ZeroEmbedder


@pytest.fixture
def kb_root(tmp_path: Path) -> Paths:
    for sub in [
        "raw", "inbox", "converted",
        "wiki/sources", "wiki/concepts", "wiki/factors",
        "wiki/strategies", "wiki/models", "wiki/threads", "wiki/outputs",
        "index/lance", "index/eval",
    ]:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / "kb.schema.md").write_text("# stub\n", encoding="utf-8")
    return Paths(tmp_path)


@pytest.fixture
def meta(kb_root: Paths) -> MetaStore:
    store = MetaStore(kb_root.meta_db)
    yield store
    store.close()


@pytest.fixture
def embedder() -> ZeroEmbedder:
    return ZeroEmbedder(dim=64)


@pytest.fixture
def vstore(kb_root: Paths, embedder: ZeroEmbedder) -> VectorStore:
    return VectorStore(kb_root.lance, dim=embedder.dim)
