"""MCP server exposing kb tools to Codex / Claude Code.

Run:
    python -m mcp_server.server                  # uses KB_ROOT env or cwd
    KB_ROOT=/Users/hedi_ai/wiki kb-mcp           # via console-script

The server is stdio-based per MCP convention; register it in Claude Code with
`claude mcp add quant-wiki -- python -m mcp_server.server` (or via the JSON
config — see USAGE.md).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from kb.agentic import gate_experiment, init_agentic, list_experiments, new_experiment
from kb.ask import ask as run_ask
from kb.compile import compile_source
from kb.concepts import create_concept_stub
from kb.config import paths as get_paths
from kb.doctor import doctor as run_doctor
from kb.index import MetaStore, VectorStore, get_embedder
from kb.lint import lint as run_lint
from kb.llm import get_llm
from kb.search import search as run_search
from kb.threads import list_threads, new_thread
from kb.thread_review import review_thread
from kb.utils.frontmatter_io import read_md

log = logging.getLogger("kb-mcp")


def _paths():
    return get_paths(Path(os.environ.get("KB_ROOT", "")) or None)


# ---------------------------------------------------------------------------
# Tool implementations — pure functions returning JSON-serialisable dicts.
# ---------------------------------------------------------------------------

def t_search(query: str, top_k: int = 8, as_of: str | None = None, domain: list[str] | None = None) -> dict:
    paths = _paths()
    meta = MetaStore(paths.meta_db)
    embedder = get_embedder()
    vstore = VectorStore(paths.lance, dim=embedder.dim)
    try:
        hits = run_search(
            query, meta=meta, vstore=vstore, embedder=embedder,
            top_k=top_k, as_of=as_of, domains=domain, rerank=True,
        )
    finally:
        meta.close()
    return {
        "query": query,
        "hits": [
            {
                "source_id": h.source_id, "page": h.page,
                "snippet": h.text[:400], "score": round(h.score, 4),
                "via": h.via, "as_of": h.as_of,
                "citation": f"[^{h.source_id}#page-{h.page}]",
            }
            for h in hits
        ],
    }


def t_fetch_source(source_id: str) -> dict:
    paths = _paths()
    card = paths.sources / f"{source_id}.md"
    if not card.exists():
        return {"error": f"source not found: {source_id}"}
    fm, body = read_md(card)
    manifest_path = paths.converted / source_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    return {"frontmatter": fm, "body": body, "manifest": manifest, "path": str(card.relative_to(paths.root))}


def t_fetch_chunk(source_id: str, page: int = 1, offset: int | None = None) -> dict:
    import sqlite3
    paths = _paths()
    db = paths.lance / "chunks.sqlite"
    if not db.exists():
        return {"error": "vector index not built"}
    con = sqlite3.connect(str(db))
    try:
        if offset is not None:
            cur = con.execute(
                "SELECT chunk_id, text, page, offset FROM chunks "
                "WHERE source_id=? AND page=? AND offset=?",
                (source_id, page, offset),
            )
        else:
            cur = con.execute(
                "SELECT chunk_id, text, page, offset FROM chunks "
                "WHERE source_id=? AND page=? ORDER BY offset LIMIT 1",
                (source_id, page),
            )
        row = cur.fetchone()
        if not row:
            return {"error": f"chunk not found: {source_id} p{page}"}
        return {"chunk_id": row[0], "text": row[1], "page": row[2], "offset": row[3]}
    finally:
        con.close()


def t_list_threads() -> dict:
    paths = _paths()
    return {"threads": list_threads(paths)}


def t_get_thread(thread_id: str) -> dict:
    paths = _paths()
    for d in paths.threads.iterdir():
        if not d.is_dir():
            continue
        main = d / "thread.md"
        if not main.exists():
            continue
        fm, body = read_md(main)
        if fm.get("id") == thread_id or d.name == thread_id:
            memos = []
            memos_dir = main.parent / "memos"
            if memos_dir.exists():
                for m in sorted(memos_dir.glob("*.md")):
                    mfm, _mbody = read_md(m)
                    memos.append({
                        "id": mfm.get("id"), "title": mfm.get("title"),
                        "query": mfm.get("query"), "path": str(m.relative_to(paths.root)),
                    })
            return {"thread": fm, "body": body, "memos": memos}
    return {"error": f"thread not found: {thread_id}"}


def t_propose_concept_stub(title: str, definition: str = "", domains: list[str] | None = None) -> dict:
    paths = _paths()
    out = create_concept_stub(title, paths=paths, definition=definition, domains=domains)
    return {"path": str(out.relative_to(paths.root)), "id": out.stem}


def t_save_memo(query: str, thread: str | None = None, top_k: int = 8, as_of: str | None = None) -> dict:
    paths = _paths()
    meta = MetaStore(paths.meta_db)
    embedder = get_embedder()
    vstore = VectorStore(paths.lance, dim=embedder.dim)
    llm = get_llm()
    try:
        r = run_ask(
            query, paths=paths, meta=meta, vstore=vstore, embedder=embedder,
            llm=llm, thread=thread, as_of=as_of, top_k=top_k,
        )
    finally:
        meta.close()
    return {
        "memo_id": r.memo_id, "thread_id": r.thread_id,
        "path": str(r.memo_path.relative_to(paths.root)),
        "hits": r.hits, "model": llm.name,
    }


def t_compile(source_id: str, aggregate_evidence: bool = True) -> dict:
    paths = _paths()
    meta = MetaStore(paths.meta_db)
    embedder = get_embedder()
    llm = get_llm()
    try:
        r = compile_source(
            source_id, paths=paths, meta=meta,
            embedder=embedder, llm=llm,
            aggregate_evidence=aggregate_evidence,
        )
    finally:
        meta.close()
    return {
        "source_id": r.source_id,
        "card_path": str(r.card_path.relative_to(paths.root)),
        "evidence_applied": r.evidence_applied,
        "proposals_written": r.proposals_written,
    }


def t_run_lint(strict: bool = False) -> dict:
    paths = _paths()
    findings = run_lint(paths)
    return {
        "n_findings": len(findings),
        "findings": [
            {
                "severity": f.severity, "rule": f.rule,
                "file": str(f.file.relative_to(paths.root)),
                "message": f.message,
            }
            for f in findings
        ],
    }


def t_doctor() -> dict:
    return run_doctor(_paths())


def t_new_thread(topic: str, hypotheses: list[str] | None = None) -> dict:
    paths = _paths()
    main = new_thread(topic, paths=paths, hypotheses=hypotheses)
    return {"path": str(main.relative_to(paths.root)), "slug": main.parent.name}


def t_review_thread(thread_id: str) -> dict:
    paths = _paths()
    r = review_thread(thread_id, paths=paths)
    return {
        "thread_id": r.thread_id, "memos_seen": r.memos_seen,
        "path": str(r.thread_path.relative_to(paths.root)),
    }


def t_agentic_init(overwrite: bool = False) -> dict:
    paths = _paths()
    r = init_agentic(paths, overwrite=overwrite)
    return {
        "directories": [str(p.relative_to(paths.root)) for p in r.directories],
        "agents": [str(p.relative_to(paths.root)) for p in r.agent_paths],
    }


def t_agentic_new(
    topic: str,
    domain: str = "选股",
    thread: str | None = None,
    hypothesis: str = "",
    citations: list[str] | None = None,
) -> dict:
    paths = _paths()
    r = new_experiment(
        topic, paths=paths, domain=domain, thread=thread,
        hypothesis=hypothesis, citations=citations,
    )
    return {
        "experiment_id": r.experiment_id,
        "path": str(r.experiment_dir.relative_to(paths.root)),
        "record": str(r.record_path.relative_to(paths.root)),
    }


def t_agentic_list() -> dict:
    paths = _paths()
    return {"experiments": list_experiments(paths)}


def t_agentic_gate(experiment: str) -> dict:
    paths = _paths()
    r = gate_experiment(experiment, paths=paths)
    return {
        "experiment_id": r.experiment_id,
        "decision": r.decision,
        "reasons": r.reasons,
        "decision_path": str(r.decision_path.relative_to(paths.root)),
    }


# ---------------------------------------------------------------------------
# MCP wiring
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {"name": "search", "desc": "Hybrid search over the knowledge base. Returns hits with citations.",
     "fn": t_search, "schema": {
         "type": "object",
         "properties": {
             "query": {"type": "string"},
             "top_k": {"type": "integer", "default": 8},
             "as_of": {"type": "string", "description": "ISO date filter, e.g. 2024-12-31"},
             "domain": {"type": "array", "items": {"type": "string"}},
         },
         "required": ["query"],
     }},
    {"name": "fetch_source", "desc": "Fetch a Source Card frontmatter + body + parser manifest.",
     "fn": t_fetch_source, "schema": {
         "type": "object", "properties": {"source_id": {"type": "string"}}, "required": ["source_id"],
     }},
    {"name": "fetch_chunk", "desc": "Fetch one indexed chunk by (source_id, page[, offset]).",
     "fn": t_fetch_chunk, "schema": {
         "type": "object", "properties": {
             "source_id": {"type": "string"}, "page": {"type": "integer"},
             "offset": {"type": "integer"},
         }, "required": ["source_id"],
     }},
    {"name": "list_threads", "desc": "List research threads.", "fn": t_list_threads,
     "schema": {"type": "object", "properties": {}}},
    {"name": "get_thread", "desc": "Read one research thread with its memos.",
     "fn": t_get_thread, "schema": {
         "type": "object", "properties": {"thread_id": {"type": "string"}}, "required": ["thread_id"],
     }},
    {"name": "new_thread", "desc": "Create a new research thread (project archive).",
     "fn": t_new_thread, "schema": {
         "type": "object",
         "properties": {"topic": {"type": "string"}, "hypotheses": {"type": "array", "items": {"type": "string"}}},
         "required": ["topic"],
     }},
    {"name": "review_thread", "desc": "Roll up all memos in a thread into a stage summary.",
     "fn": t_review_thread, "schema": {
         "type": "object", "properties": {"thread_id": {"type": "string"}}, "required": ["thread_id"],
     }},
    {"name": "propose_concept_stub", "desc": "Create a Concept Card stub (does not auto-promote — human reviews).",
     "fn": t_propose_concept_stub, "schema": {
         "type": "object",
         "properties": {
             "title": {"type": "string"}, "definition": {"type": "string"},
             "domains": {"type": "array", "items": {"type": "string"}},
         },
         "required": ["title"],
     }},
    {"name": "save_memo", "desc": "Ask a question, synthesise a memo with citations, write to a thread (or outputs/).",
     "fn": t_save_memo, "schema": {
         "type": "object",
         "properties": {
             "query": {"type": "string"}, "thread": {"type": "string"},
             "top_k": {"type": "integer"}, "as_of": {"type": "string"},
         },
         "required": ["query"],
     }},
    {"name": "compile", "desc": "Generate/refresh a Source Card and route claims to concepts.",
     "fn": t_compile, "schema": {
         "type": "object",
         "properties": {"source_id": {"type": "string"}, "aggregate_evidence": {"type": "boolean"}},
         "required": ["source_id"],
     }},
    {"name": "run_lint", "desc": "Structural lint over the wiki — returns findings.",
     "fn": t_run_lint, "schema": {"type": "object", "properties": {"strict": {"type": "boolean"}}}},
    {"name": "doctor", "desc": "Health snapshot of the KB.",
     "fn": t_doctor, "schema": {"type": "object", "properties": {}}},
    {"name": "agentic_init", "desc": "Create semi-autonomous agent role cards and sandbox folders.",
     "fn": t_agentic_init, "schema": {
         "type": "object", "properties": {"overwrite": {"type": "boolean"}},
     }},
    {"name": "agentic_new", "desc": "Create one guarded semi-autonomous factor experiment.",
     "fn": t_agentic_new, "schema": {
         "type": "object",
         "properties": {
             "topic": {"type": "string"},
             "domain": {"type": "string"},
             "thread": {"type": "string"},
             "hypothesis": {"type": "string"},
             "citations": {"type": "array", "items": {"type": "string"}},
         },
         "required": ["topic"],
     }},
    {"name": "agentic_list", "desc": "List semi-autonomous factor experiments.",
     "fn": t_agentic_list, "schema": {"type": "object", "properties": {}}},
    {"name": "agentic_gate", "desc": "Apply the fixed promotion gate to an experiment.",
     "fn": t_agentic_gate, "schema": {
         "type": "object",
         "properties": {"experiment": {"type": "string"}},
         "required": ["experiment"],
     }},
]


def call_tool(name: str, arguments: dict) -> Any:
    """Synchronous dispatch — used by tests + the async MCP handler."""
    for t in TOOLS:
        if t["name"] == name:
            try:
                return t["fn"](**(arguments or {}))
            except Exception as exc:  # surface a structured error, never crash the server
                log.exception("tool %s failed", name)
                return {"error": f"{type(exc).__name__}: {exc}"}
    return {"error": f"unknown tool: {name}"}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        from mcp.server import Server  # type: ignore
        from mcp.server.stdio import stdio_server  # type: ignore
        from mcp.types import TextContent, Tool  # type: ignore
    except ImportError:
        print(
            "MCP SDK not installed. Run: pip install 'quant-wiki[mcp]'",
            flush=True,
        )
        return 1

    import asyncio

    server = Server("quant-wiki")

    @server.list_tools()
    async def _list_tools() -> list:
        return [
            Tool(name=t["name"], description=t["desc"], inputSchema=t["schema"])
            for t in TOOLS
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list:
        result = call_tool(name, arguments or {})
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    async def _run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
