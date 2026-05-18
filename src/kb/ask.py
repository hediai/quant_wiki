"""Memo generation: retrieve → synthesise → write into a thread (or outputs/)."""
from __future__ import annotations

import datetime as dt
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path

from .config import Paths
from .index import MetaStore, VectorStore
from .llm import LLMClient, Passage, get_llm
from .search import search
from .utils.frontmatter_io import read_md, write_md
from .utils.ids import memo_id

log = logging.getLogger(__name__)


@dataclass
class AskResult:
    memo_id: str
    memo_path: Path
    thread_id: str | None
    hits: int


def ask(
    query: str,
    *,
    paths: Paths,
    meta: MetaStore,
    vstore: VectorStore,
    embedder,
    llm: LLMClient | None = None,
    thread: str | None = None,
    as_of: str | None = None,
    top_k: int = 8,
    domains: list[str] | None = None,
) -> AskResult:
    llm = llm or get_llm()
    hits = search(
        query, meta=meta, vstore=vstore, embedder=embedder,
        top_k=top_k, as_of=as_of, domains=domains, rerank=True,
    )

    passages = [Passage(source_id=h.source_id, page=h.page, text=h.text) for h in hits]
    body = llm.summarise(query, passages)

    # Resolve thread (if given) and choose a target directory.
    thread_resolved = _resolve_thread(paths, thread) if thread else None
    out_dir = (
        thread_resolved.parent / "memos" if thread_resolved else paths.outputs
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    mid = memo_id(query, when=dt.datetime.now(), rand_hex=secrets.token_hex(2))
    fm = {
        "id": mid, "type": "memo", "title": query[:80],
        "thread": _thread_id_from_path(thread_resolved) if thread_resolved else None,
        "query": query,
        "as_of_filter": as_of,
        "retrieval": {
            "top_k": top_k,
            "domains": domains,
            "hit_ids": [f"{h.source_id}#page-{h.page}" for h in hits],
            "via": [h.via for h in hits],
        },
        "model": llm.name,
        "status": "draft",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    path = out_dir / f"{mid}.md"
    write_md(path, fm, body + "\n")

    # If we landed in a thread, append a "what changed" line.
    if thread_resolved:
        _touch_thread(thread_resolved, mid, query)

    return AskResult(memo_id=mid, memo_path=path, thread_id=fm["thread"], hits=len(hits))


def _resolve_thread(paths: Paths, ident: str) -> Path | None:
    """Accept either a full thread id (`thread-xxx-yyyqQ`), a slug, or a path."""
    if not paths.threads.exists():
        return None
    # Direct id match
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
    log.warning("thread '%s' not found; memo will land in outputs/", ident)
    return None


def _thread_id_from_path(main: Path) -> str | None:
    try:
        fm, _ = read_md(main)
        return fm.get("id")
    except Exception:
        return None


def _touch_thread(main: Path, mid: str, query: str) -> None:
    fm, body = read_md(main)
    today = dt.date.today().isoformat()
    line = f"- {today}: 新 memo `{mid}` — {query[:80]}"
    from .concepts import _upsert_section  # type: ignore
    body = _upsert_section(body, "## Changelog", line)
    write_md(main, fm, body)
