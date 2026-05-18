"""Doctor: report KB health. Read-only."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .config import Paths
from .index import MetaStore


def doctor(paths: Paths) -> dict:
    meta = MetaStore(paths.meta_db)
    try:
        stats = meta.stats()
    finally:
        meta.close()

    raw_count = sum(1 for _ in paths.raw.rglob("*") if _.is_file()) if paths.raw.exists() else 0
    inbox_count = sum(1 for _ in paths.inbox.rglob("*") if _.is_file()) if paths.inbox.exists() else 0
    converted_count = len([p for p in paths.converted.iterdir() if p.is_dir()]) if paths.converted.exists() else 0
    sources_md = len(list((paths.wiki / "sources").glob("*.md"))) if (paths.wiki / "sources").exists() else 0
    threads_count = len([p for p in (paths.wiki / "threads").iterdir() if p.is_dir()]) if (paths.wiki / "threads").exists() else 0
    outputs_count = len(list(paths.outputs.glob("*.md"))) if paths.outputs.exists() else 0
    experiments_count = len(list(paths.experiments.glob("exp-*"))) if paths.experiments.exists() else 0

    # Capabilities.
    caps: dict[str, bool] = {}
    for mod in ("markitdown", "docling", "marker", "pypdf",
                "lancedb", "sentence_transformers", "FlagEmbedding", "jieba",
                "mcp", "anthropic"):
        try:
            __import__(mod)
            caps[mod] = True
        except ImportError:
            caps[mod] = False

    # factor_mining repo detection
    factor_repo = _find_factor_mining_repo(paths)
    factor_info = {
        "repo_path": str(factor_repo) if factor_repo else None,
        "is_git": (factor_repo / ".git").exists() if factor_repo else False,
        "factor_cards": len(list((paths.wiki / "factors").glob("*.md"))) if (paths.wiki / "factors").exists() else 0,
    }

    # Conflicts + regressions counts
    review_queue = {
        "conflicts": _count_lines(paths.conflicts),
        "regressions": _count_lines(paths.regressions),
        "concept_proposals": len(list((paths.root / "inbox" / "concepts").glob("*.md"))) if (paths.root / "inbox" / "concepts").exists() else 0,
    }

    suggestions: list[str] = []
    if not caps.get("markitdown"):
        suggestions.append("pip install 'quant-wiki[parsers]' — enables Office/HTML/CSV parsing")
    if not caps.get("docling") and not caps.get("marker"):
        suggestions.append("pip install 'quant-wiki[parsers-heavy]' — needed for non-trivial PDFs")
    if not caps.get("lancedb"):
        suggestions.append("pip install 'quant-wiki[index]' — enables LanceDB vector index")
    if not caps.get("sentence_transformers"):
        suggestions.append("pip install 'quant-wiki[embed]' — enables bge-m3 embedding (otherwise hash fallback)")
    if not caps.get("mcp"):
        suggestions.append("pip install 'quant-wiki[mcp]' — enables `kb-mcp` server for Codex/Claude Code")
    if not caps.get("anthropic"):
        suggestions.append("pip install 'quant-wiki[anthropic]' + export ANTHROPIC_API_KEY — enables real LLM synthesis")
    if inbox_count:
        suggestions.append(f"{inbox_count} file(s) sit in inbox/ — run `kb ingest inbox/` to absorb.")
    if outputs_count > 5:
        suggestions.append(f"{outputs_count} unassigned memo(s) in wiki/outputs/ — consider `kb thread new`.")
    if review_queue["conflicts"]:
        suggestions.append(f"{review_queue['conflicts']} contradiction(s) in index/conflicts.jsonl — review with `kb lint`.")
    if review_queue["concept_proposals"]:
        suggestions.append(f"{review_queue['concept_proposals']} concept proposal(s) in inbox/concepts/ — promote or discard.")
    if factor_info["repo_path"] is None:
        suggestions.append("factor_mining repo not detected — kb will operate without code/backtest linkage.")

    return {
        "stats": stats,
        "counts": {
            "raw_files": raw_count, "inbox_files": inbox_count,
            "converted_dirs": converted_count, "source_cards": sources_md,
            "threads": threads_count, "outputs_memos": outputs_count,
            "agentic_experiments": experiments_count,
        },
        "capabilities": caps,
        "factor_mining": factor_info,
        "review_queue": review_queue,
        "suggestions": suggestions,
    }


def _find_factor_mining_repo(paths: Paths) -> Path | None:
    import os
    env = os.environ.get("FACTOR_MINING_REPO")
    if env:
        p = Path(env)
        return p if p.exists() else None
    candidates = [paths.root.parent / "factor_mining", paths.root.parent / "factor-mining"]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c.resolve()
    return None


def _count_lines(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for line in p.open(encoding="utf-8") if line.strip())
