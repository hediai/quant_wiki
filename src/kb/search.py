"""Search: hybrid FTS + vector + optional reranker, with as_of filter."""
from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass
from typing import Sequence

from .config import HALF_LIFE_DAYS, Paths
from .index import Hit, MetaStore, VectorStore
from .utils.text import jieba_tokens

log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    chunk_id: str
    source_id: str
    page: int
    text: str
    score: float
    via: str
    as_of: str | None = None


def search(
    query: str,
    *,
    meta: MetaStore,
    vstore: VectorStore,
    embedder,
    top_k: int = 10,
    fetch_k: int = 30,
    as_of: str | None = None,
    domains: Sequence[str] | None = None,
    rerank: bool = True,
    half_life_days: int = HALF_LIFE_DAYS,
) -> list[SearchResult]:
    as_of_iso = _normalise_date(as_of)
    tokens = jieba_tokens(query)
    qvec = embedder.encode([query])[0] if embedder else None

    hits = vstore.hybrid(
        query_text=query, query_tokens=tokens, query_vec=qvec,
        top_k=fetch_k, fetch_k=fetch_k, as_of=as_of_iso,
    )

    # Domain filter via SQLite metadata.
    if domains:
        ok = set(meta.con.execute(
            "SELECT id FROM sources WHERE " + " OR ".join(["domains LIKE ?"] * len(domains)),
            [f"%{d}%" for d in domains],
        ).fetchall())
        ok_ids = {r[0] for r in ok}
        hits = [h for h in hits if h.source_id in ok_ids]

    if rerank:
        hits = _rerank(query, hits)

    # Time-decay weighting.
    if half_life_days > 0:
        now = dt.date.today()
        for h in hits:
            src = meta.get_source(h.source_id)
            if not src:
                continue
            as_of_str = src.get("as_of") or src.get("date")
            if not as_of_str:
                continue
            try:
                d = dt.date.fromisoformat(as_of_str)
            except ValueError:
                continue
            age = max((now - d).days, 0)
            h.score = h.score * math.exp(-age / half_life_days)

    hits.sort(key=lambda h: h.score, reverse=True)
    out: list[SearchResult] = []
    for h in hits[:top_k]:
        src = meta.get_source(h.source_id) or {}
        out.append(SearchResult(
            chunk_id=h.chunk_id, source_id=h.source_id, page=h.page,
            text=h.text, score=h.score, via=h.via, as_of=src.get("as_of"),
        ))
    return out


def _rerank(query: str, hits: list[Hit]) -> list[Hit]:
    """Cross-encoder rerank when FlagEmbedding is available; otherwise no-op."""
    if not hits:
        return hits
    try:
        from FlagEmbedding import FlagReranker  # type: ignore
    except ImportError:
        return hits
    try:
        reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=True)
        pairs = [(query, h.text) for h in hits]
        scores = reranker.compute_score(pairs, normalize=True)
        for h, s in zip(hits, scores):
            h.score = float(s)
            h.via = "rerank"
    except Exception as exc:
        log.warning("rerank failed (%s); using hybrid scores.", exc)
    return hits


def _normalise_date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s).isoformat()
    except ValueError:
        return s
