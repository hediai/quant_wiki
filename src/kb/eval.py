"""Evaluation: retrieval recall@k / MRR + citation faithfulness on memos."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import Paths
from .index import MetaStore, VectorStore
from .llm import LLMClient, get_llm
from .search import search
from .utils.frontmatter_io import read_md

log = logging.getLogger(__name__)


@dataclass
class GoldenCase:
    id: str
    query: str
    expected_source_ids: list[str]
    expected_keywords: list[str]
    domains: list[str] | None
    as_of: str | None


@dataclass
class CaseResult:
    case_id: str
    query: str
    recall_at_5: float
    recall_at_10: float
    rr: float
    keyword_coverage: float
    hits_top5: list[str]
    notes: str = ""


@dataclass
class EvalReport:
    cases: list[CaseResult]
    mean_recall_5: float
    mean_recall_10: float
    mrr: float
    mean_keyword_coverage: float
    citation_faithfulness: float | None
    citation_checked: int


def run_retrieval_eval(
    paths: Paths,
    *,
    meta: MetaStore,
    vstore: VectorStore,
    embedder,
    cases: list[GoldenCase] | None = None,
) -> EvalReport:
    cases = cases or load_golden(paths.golden)

    results: list[CaseResult] = []
    for c in cases:
        hits = search(
            c.query, meta=meta, vstore=vstore, embedder=embedder,
            top_k=10, as_of=c.as_of, domains=c.domains, rerank=False,
        )
        hit_sources = [h.source_id for h in hits]
        top5 = hit_sources[:5]
        top10 = hit_sources[:10]

        rec5 = _recall(c.expected_source_ids, top5) if c.expected_source_ids else None
        rec10 = _recall(c.expected_source_ids, top10) if c.expected_source_ids else None
        rr = _reciprocal_rank(c.expected_source_ids, hit_sources) if c.expected_source_ids else None
        kw_cov = _keyword_coverage(c.expected_keywords, hits[:5])

        results.append(CaseResult(
            case_id=c.id, query=c.query,
            recall_at_5=rec5 if rec5 is not None else 0.0,
            recall_at_10=rec10 if rec10 is not None else 0.0,
            rr=rr if rr is not None else 0.0,
            keyword_coverage=kw_cov,
            hits_top5=top5,
            notes="" if c.expected_source_ids else "no expected_source_ids → keyword-only check",
        ))

    real_cases = [c for c, gc in zip(results, cases) if gc.expected_source_ids]

    report = EvalReport(
        cases=results,
        mean_recall_5=_mean(c.recall_at_5 for c in real_cases),
        mean_recall_10=_mean(c.recall_at_10 for c in real_cases),
        mrr=_mean(c.rr for c in real_cases),
        mean_keyword_coverage=_mean(c.keyword_coverage for c in results),
        citation_faithfulness=None,
        citation_checked=0,
    )

    _append_regressions(paths, report, cases)
    return report


def run_faithfulness_eval(
    paths: Paths,
    *,
    meta: MetaStore,
    llm: LLMClient | None = None,
    sample: int = 20,
) -> tuple[float, int]:
    """Sample recent memos, parse `[^src-id#page-x]` citations, and call
    `llm.judge_support` against the cited chunk.
    Returns (faithfulness_ratio, n_claims_checked).
    """
    llm = llm or get_llm()
    memos: list[Path] = []
    for d in [paths.outputs, paths.threads]:
        if d.exists():
            memos.extend(d.rglob("*.md"))
    memos = [m for m in memos if m.name != "thread.md"]
    memos = memos[-sample:] if len(memos) > sample else memos

    cite_re = re.compile(r"\[\^([a-z0-9\-]+)(?:#page-(\d+))?\]")
    sup = 0
    total = 0
    for m in memos:
        try:
            _, body = read_md(m)
        except Exception:
            continue
        for sent in re.split(r"(?<=[。.！!？?])", body):
            sent = sent.strip()
            if not sent:
                continue
            for m_cite in cite_re.finditer(sent):
                sid, page_s = m_cite.group(1), m_cite.group(2)
                page = int(page_s) if page_s else 1
                chunk = _fetch_chunk_text(paths, sid, page)
                if not chunk:
                    continue
                claim = cite_re.sub("", sent).strip()
                if not claim:
                    continue
                total += 1
                if llm.judge_support(claim, chunk):
                    sup += 1
    return (sup / total if total else 0.0, total)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_golden(path: Path) -> list[GoldenCase]:
    if not path.exists():
        return []
    out: list[GoldenCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            log.warning("bad golden row: %s (%s)", line[:80], exc)
            continue
        out.append(GoldenCase(
            id=row["id"], query=row["query"],
            expected_source_ids=list(row.get("expected_source_ids") or []),
            expected_keywords=list(row.get("expected_keywords") or []),
            domains=row.get("domains") or None,
            as_of=row.get("as_of") or None,
        ))
    return out


def _recall(expected: list[str], hits: list[str]) -> float:
    if not expected:
        return 0.0
    expected_s = set(expected)
    found = sum(1 for s in expected_s if s in hits)
    return found / len(expected_s)


def _reciprocal_rank(expected: list[str], hits: list[str]) -> float:
    expected_s = set(expected)
    for i, h in enumerate(hits, start=1):
        if h in expected_s:
            return 1.0 / i
    return 0.0


def _keyword_coverage(keywords: list[str], hits) -> float:
    if not keywords:
        return 0.0
    text = " ".join(h.text for h in hits)
    found = sum(1 for k in keywords if k in text)
    return found / len(keywords)


def _mean(xs) -> float:
    vals = list(xs)
    return sum(vals) / len(vals) if vals else 0.0


def _fetch_chunk_text(paths: Paths, source_id: str, page: int) -> str:
    # Use the VectorStore SQLite directly to avoid spinning a full search.
    import sqlite3
    db = paths.lance / "chunks.sqlite"
    if not db.exists():
        return ""
    con = sqlite3.connect(str(db))
    try:
        cur = con.execute(
            "SELECT text FROM chunks WHERE source_id = ? AND page = ? LIMIT 1",
            (source_id, page),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur = con.execute(
            "SELECT text FROM chunks WHERE source_id = ? LIMIT 1",
            (source_id,),
        )
        row = cur.fetchone()
        return row[0] if row else ""
    finally:
        con.close()


def _append_regressions(paths: Paths, report: EvalReport, cases: list[GoldenCase]) -> None:
    failures = []
    for case, c in zip(cases, report.cases):
        if case.expected_source_ids and c.recall_at_5 < 0.5:
            failures.append({
                "case_id": case.id, "query": case.query,
                "recall_at_5": c.recall_at_5,
                "expected": case.expected_source_ids,
                "got_top5": c.hits_top5,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
    if not failures:
        return
    paths.regressions.parent.mkdir(parents=True, exist_ok=True)
    with open(paths.regressions, "a", encoding="utf-8") as f:
        for row in failures:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
