"""Chunk + vector + FTS store. LanceDB when available, SQLite-only fallback."""
from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

log = logging.getLogger(__name__)


@dataclass
class Hit:
    chunk_id: str
    source_id: str
    page: int
    text: str
    score: float
    via: str  # "fts" | "vector" | "hybrid"


class VectorStore:
    """Hybrid (FTS + vector) store. Internally backed by SQLite for FTS5 and
    LanceDB for vectors when available; if LanceDB is missing we keep vectors
    in SQLite blobs and do brute-force cosine in Python (fine for ≤ few-k chunks).
    """

    def __init__(self, root: Path, dim: int):
        self.root = root
        self.dim = dim
        root.mkdir(parents=True, exist_ok=True)
        self._sqlite_path = root / "chunks.sqlite"
        self._con = sqlite3.connect(str(self._sqlite_path))
        self._con.row_factory = sqlite3.Row
        self._init_sqlite()
        self._lance_tbl = self._open_lance()

    # ---- schema ------------------------------------------------------------
    def _init_sqlite(self) -> None:
        with self._con:
            self._con.executescript(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    page INTEGER,
                    offset INTEGER,
                    text TEXT NOT NULL,
                    tokens TEXT,
                    domains TEXT,
                    as_of TEXT,
                    license TEXT,
                    vector BLOB
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    tokens,
                    content='chunks',
                    content_rowid='rowid'
                );
                CREATE TRIGGER IF NOT EXISTS chunks_fts_ai AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts(rowid, tokens) VALUES (new.rowid, new.tokens);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_fts_ad AFTER DELETE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, tokens) VALUES('delete', old.rowid, old.tokens);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_fts_au AFTER UPDATE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, tokens) VALUES('delete', old.rowid, old.tokens);
                    INSERT INTO chunks_fts(rowid, tokens) VALUES (new.rowid, new.tokens);
                END;
                CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_as_of ON chunks(as_of);
                """
            )

    def _open_lance(self):
        try:
            import lancedb  # type: ignore
            import pyarrow as pa  # type: ignore
        except ImportError:
            return None
        try:
            db = lancedb.connect(str(self.root / "lance"))
            if "chunks" in db.table_names():
                return db.open_table("chunks")
            schema = pa.schema([
                pa.field("chunk_id", pa.string()),
                pa.field("source_id", pa.string()),
                pa.field("page", pa.int32()),
                pa.field("offset", pa.int32()),
                pa.field("text", pa.string()),
                pa.field("as_of", pa.string()),
                pa.field("license", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), self.dim)),
            ])
            return db.create_table("chunks", schema=schema, mode="create")
        except Exception as exc:
            log.warning("LanceDB unavailable, using SQLite-only vectors: %s", exc)
            return None

    # ---- writes ------------------------------------------------------------
    def delete_source(self, source_id: str) -> None:
        with self._con:
            self._con.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
        if self._lance_tbl is not None:
            try:
                self._lance_tbl.delete(f"source_id = '{source_id}'")
            except Exception as exc:
                log.warning("Lance delete failed: %s", exc)

    def add_chunks(self, rows: list[dict]) -> None:
        if not rows:
            return
        sql_rows = []
        for r in rows:
            vec_blob = _pack_vector(r["vector"]) if r.get("vector") is not None else None
            sql_rows.append((
                r["chunk_id"], r["source_id"], r.get("page", 1),
                r.get("offset", 0), r["text"], r.get("tokens", ""),
                json.dumps(r.get("domains") or [], ensure_ascii=False),
                r.get("as_of") or "",
                r.get("license") or "",
                vec_blob,
            ))
        with self._con:
            self._con.executemany(
                "INSERT OR REPLACE INTO chunks "
                "(chunk_id, source_id, page, offset, text, tokens, domains, as_of, license, vector) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                sql_rows,
            )
        if self._lance_tbl is not None:
            try:
                lance_rows = [{
                    "chunk_id": r["chunk_id"],
                    "source_id": r["source_id"],
                    "page": int(r.get("page", 1)),
                    "offset": int(r.get("offset", 0)),
                    "text": r["text"],
                    "as_of": r.get("as_of") or "",
                    "license": r.get("license") or "",
                    "vector": [float(x) for x in r["vector"]],
                } for r in rows if r.get("vector") is not None]
                if lance_rows:
                    self._lance_tbl.add(lance_rows)
            except Exception as exc:
                log.warning("Lance add failed (continuing with SQLite vectors): %s", exc)

    # ---- queries -----------------------------------------------------------
    def fts(self, query_tokens: str, *, top_k: int = 20, as_of: str | None = None) -> list[Hit]:
        q = _fts_escape(query_tokens)
        if not q:
            return []
        where = ""
        params: list = []
        if as_of:
            where = "AND (c.as_of = '' OR c.as_of <= ?)"
            params.append(as_of)
        sql = (
            "SELECT c.chunk_id, c.source_id, c.page, c.text, bm25(chunks_fts) AS score "
            "FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid "
            f"WHERE chunks_fts MATCH ? {where} "
            "ORDER BY score LIMIT ?"
        )
        try:
            cur = self._con.execute(sql, [q, *params, top_k])
        except sqlite3.OperationalError as exc:
            log.warning("FTS query failed: %s", exc)
            return []
        hits = []
        for row in cur.fetchall():
            hits.append(Hit(
                chunk_id=row["chunk_id"], source_id=row["source_id"],
                page=row["page"] or 1, text=row["text"],
                score=-float(row["score"]),  # bm25 lower is better; negate so higher=better
                via="fts",
            ))
        return hits

    def vector(self, query_vec: Sequence[float], *, top_k: int = 20, as_of: str | None = None) -> list[Hit]:
        if self._lance_tbl is not None:
            return self._vector_lance(query_vec, top_k=top_k, as_of=as_of)
        return self._vector_brute(query_vec, top_k=top_k, as_of=as_of)

    def _vector_lance(self, qv, *, top_k: int, as_of: str | None) -> list[Hit]:
        try:
            q = self._lance_tbl.search(list(qv)).limit(top_k * 3)
            if as_of:
                q = q.where(f"as_of = '' OR as_of <= '{as_of}'", prefilter=True)
            df = q.to_pandas()
        except Exception as exc:
            log.warning("Lance search failed (%s); falling back to brute force.", exc)
            return self._vector_brute(qv, top_k=top_k, as_of=as_of)

        hits: list[Hit] = []
        for _, r in df.iterrows():
            dist = float(r.get("_distance", 0.0))
            hits.append(Hit(
                chunk_id=r["chunk_id"], source_id=r["source_id"],
                page=int(r.get("page") or 1), text=r["text"],
                score=1.0 - dist, via="vector",
            ))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def _vector_brute(self, qv, *, top_k: int, as_of: str | None) -> list[Hit]:
        sql = "SELECT chunk_id, source_id, page, text, vector, as_of FROM chunks WHERE vector IS NOT NULL"
        params: list = []
        if as_of:
            sql += " AND (as_of = '' OR as_of <= ?)"
            params.append(as_of)
        cur = self._con.execute(sql, params)
        scored: list[tuple[float, sqlite3.Row]] = []
        qv = list(qv)
        for row in cur.fetchall():
            v = _unpack_vector(row["vector"])
            if not v:
                continue
            scored.append((_cosine(qv, v), row))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [
            Hit(
                chunk_id=r["chunk_id"], source_id=r["source_id"],
                page=r["page"] or 1, text=r["text"], score=s, via="vector",
            )
            for s, r in scored[:top_k]
        ]

    def hybrid(
        self,
        *,
        query_text: str,
        query_tokens: str,
        query_vec: Sequence[float] | None,
        top_k: int = 10,
        fetch_k: int = 30,
        as_of: str | None = None,
    ) -> list[Hit]:
        fts_hits = self.fts(query_tokens, top_k=fetch_k, as_of=as_of)
        vec_hits = self.vector(query_vec, top_k=fetch_k, as_of=as_of) if query_vec else []
        return rrf_fuse(fts_hits, vec_hits, top_k=top_k)

    def count(self) -> int:
        return self._con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]


def rrf_fuse(*lists: Iterable[Hit], top_k: int = 10, k: int = 60) -> list[Hit]:
    """Reciprocal rank fusion of hit lists."""
    scores: dict[str, tuple[float, Hit]] = {}
    for lst in lists:
        for rank, hit in enumerate(lst):
            cur = scores.get(hit.chunk_id)
            inc = 1.0 / (k + rank + 1)
            if cur is None:
                merged = Hit(hit.chunk_id, hit.source_id, hit.page, hit.text, inc, "hybrid")
                scores[hit.chunk_id] = (inc, merged)
            else:
                s, h = cur
                scores[hit.chunk_id] = (s + inc, Hit(h.chunk_id, h.source_id, h.page, h.text, s + inc, "hybrid"))
    fused = [h for _, h in scores.values()]
    fused.sort(key=lambda h: h.score, reverse=True)
    return fused[:top_k]


# ---- utilities ----------------------------------------------------------------
def _pack_vector(vec: Sequence[float]) -> bytes:
    import struct
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack_vector(blob: bytes) -> list[float]:
    if not blob:
        return []
    import struct
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


_FTS_BAD = re.compile(r"[\"\\(\\)\\:\\*]")


def _fts_escape(q: str) -> str:
    """Quote each whitespace-separated term for FTS5 phrase match."""
    if not q:
        return ""
    terms = [t for t in q.split() if t and not _FTS_BAD.search(t)]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in terms)
