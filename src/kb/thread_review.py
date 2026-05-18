"""Thread review: roll up all memos in a thread into a stage summary."""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

from .concepts import _upsert_section  # type: ignore
from .config import Paths
from .llm import LLMClient, Passage, get_llm
from .utils.frontmatter_io import read_md, write_md

log = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    thread_id: str
    thread_path: Path
    memos_seen: int


def review_thread(thread_id: str, *, paths: Paths, llm: LLMClient | None = None) -> ReviewResult:
    llm = llm or get_llm()
    main = _find_thread(paths, thread_id)
    if main is None:
        raise KeyError(f"thread not found: {thread_id}")

    memos_dir = main.parent / "memos"
    memos: list[tuple[dict, str]] = []
    if memos_dir.exists():
        for md in sorted(memos_dir.glob("*.md")):
            try:
                fm, body = read_md(md)
            except Exception as exc:
                log.warning("memo %s unreadable: %s", md, exc)
                continue
            memos.append((fm, body))

    if not memos:
        summary = "_本 thread 暂无 memo，先用 `kb ask --thread` 写一份。_"
    else:
        # Compose a synthetic 'passage list' from memo queries + bodies.
        passages = []
        for fm, body in memos:
            mid = fm.get("id") or "memo-?"
            q = fm.get("query") or fm.get("title") or ""
            snippet = body.strip()[:600]
            passages.append(Passage(source_id=mid, page=0, text=f"{q}\n\n{snippet}"))
        # Offline heuristic prints a tidy index; LLM produces real synthesis.
        summary = llm.summarise(
            query=f"汇总 thread `{thread_id}` 下的所有 memo，识别一致结论、冲突、open questions。",
            passages=passages,
        )

    fm, body = read_md(main)
    today = dt.date.today().isoformat()
    block = (
        f"\n### {today} 阶段性总结\n\n"
        + summary
        + f"\n\n_由 `kb thread review {thread_id}` 自动生成。_\n"
    )
    body = _upsert_section(body, "## 阶段性结论", block)
    fm["last_reviewed"] = today
    write_md(main, fm, body)

    return ReviewResult(thread_id=thread_id, thread_path=main, memos_seen=len(memos))


def _find_thread(paths: Paths, ident: str) -> Path | None:
    if not paths.threads.exists():
        return None
    for d in paths.threads.iterdir():
        if not d.is_dir():
            continue
        main = d / "thread.md"
        if not main.exists():
            continue
        try:
            fm, _ = read_md(main)
        except Exception:
            continue
        if fm.get("id") == ident or d.name == ident:
            return main
    return None
