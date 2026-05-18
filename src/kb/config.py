"""Paths, defaults, and project-root discovery."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def find_root(start: Path | None = None) -> Path:
    """Walk up from start until we find a folder containing kb.schema.md."""
    cur = (start or Path.cwd()).resolve()
    for parent in [cur, *cur.parents]:
        if (parent / "kb.schema.md").exists():
            return parent
    env = os.environ.get("KB_ROOT")
    if env:
        return Path(env).resolve()
    raise RuntimeError(
        "Could not locate kb root (no kb.schema.md found). "
        "Run from inside the repo or set KB_ROOT."
    )


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def raw(self) -> Path: return self.root / "raw"
    @property
    def inbox(self) -> Path: return self.root / "inbox"
    @property
    def converted(self) -> Path: return self.root / "converted"
    @property
    def wiki(self) -> Path: return self.root / "wiki"
    @property
    def sources(self) -> Path: return self.wiki / "sources"
    @property
    def concepts(self) -> Path: return self.wiki / "concepts"
    @property
    def factors(self) -> Path: return self.wiki / "factors"
    @property
    def threads(self) -> Path: return self.wiki / "threads"
    @property
    def outputs(self) -> Path: return self.wiki / "outputs"
    @property
    def experiments(self) -> Path: return self.root / "experiments"
    @property
    def agents(self) -> Path: return self.root / "agents"
    @property
    def index(self) -> Path: return self.root / "index"
    @property
    def meta_db(self) -> Path: return self.index / "meta.sqlite"
    @property
    def lance(self) -> Path: return self.index / "lance"
    @property
    def eval_dir(self) -> Path: return self.index / "eval"
    @property
    def golden(self) -> Path: return self.eval_dir / "golden.jsonl"
    @property
    def regressions(self) -> Path: return self.eval_dir / "regressions.jsonl"
    @property
    def conflicts(self) -> Path: return self.index / "conflicts.jsonl"


def paths(start: Path | None = None) -> Paths:
    return Paths(find_root(start))


# Defaults
EMBED_MODEL = os.environ.get("KB_EMBED_MODEL", "BAAI/bge-m3")
RERANK_MODEL = os.environ.get("KB_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
CHUNK_SIZE = int(os.environ.get("KB_CHUNK_SIZE", "800"))  # chars
CHUNK_OVERLAP = int(os.environ.get("KB_CHUNK_OVERLAP", "120"))
HALF_LIFE_DAYS = int(os.environ.get("KB_HALF_LIFE_DAYS", "730"))
