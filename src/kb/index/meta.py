"""SQLite metadata store: sources, ingest log, citation graph."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    title TEXT,
    institution TEXT,
    date TEXT,
    as_of TEXT,
    domains TEXT,           -- JSON array
    asset_classes TEXT,     -- JSON array
    tags TEXT,              -- JSON array
    license TEXT,
    source_hash TEXT UNIQUE,
    parser TEXT,
    parser_version TEXT,
    status TEXT,
    raw_path TEXT,
    ingested_at TEXT,
    extra TEXT              -- JSON for forward-compat
);

CREATE INDEX IF NOT EXISTS idx_sources_as_of ON sources(as_of);
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);

CREATE TABLE IF NOT EXISTS ingest_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT,
    raw_path TEXT,
    source_hash TEXT,
    parser TEXT,
    parser_version TEXT,
    chunk_count INTEGER,
    figure_count INTEGER,
    table_count INTEGER,
    errors TEXT,            -- JSON array
    at TEXT
);

CREATE TABLE IF NOT EXISTS citations (
    src_card TEXT,          -- source/concept/factor/memo id of the *citer*
    cited_source TEXT,
    page INTEGER,
    snippet TEXT,
    PRIMARY KEY (src_card, cited_source, page)
);
CREATE INDEX IF NOT EXISTS idx_citations_target ON citations(cited_source);

CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    title TEXT,
    status TEXT,
    last_reviewed TEXT,
    extra TEXT
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""

CURRENT_VERSION = 1


class MetaStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(db_path))
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self._ensure_version()
        self.con.commit()

    def _ensure_version(self) -> None:
        cur = self.con.execute("SELECT version FROM schema_version")
        row = cur.fetchone()
        if row is None:
            self.con.execute("INSERT INTO schema_version(version) VALUES (?)", (CURRENT_VERSION,))

    def close(self) -> None:
        self.con.close()

    @contextmanager
    def tx(self):
        try:
            yield self.con
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise

    # ---- sources -----------------------------------------------------------
    def upsert_source(self, fields: dict) -> None:
        cols = [
            "id", "title", "institution", "date", "as_of",
            "domains", "asset_classes", "tags",
            "license", "source_hash", "parser", "parser_version",
            "status", "raw_path", "ingested_at", "extra",
        ]
        row = {k: _normalise(fields.get(k)) for k in cols}
        placeholders = ",".join(["?"] * len(cols))
        assignments = ",".join(f"{c}=excluded.{c}" for c in cols if c != "id")
        sql = (
            f"INSERT INTO sources ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {assignments}"
        )
        with self.tx() as con:
            con.execute(sql, [row[c] for c in cols])

    def get_source(self, source_id: str) -> dict | None:
        cur = self.con.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def get_source_by_hash(self, source_hash: str) -> dict | None:
        cur = self.con.execute("SELECT * FROM sources WHERE source_hash = ?", (source_hash,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def list_sources(self) -> list[dict]:
        cur = self.con.execute("SELECT * FROM sources ORDER BY date DESC, id")
        return [_row_to_dict(r) for r in cur.fetchall()]

    def sources_as_of(self, as_of_iso: str) -> set[str]:
        cur = self.con.execute(
            "SELECT id FROM sources WHERE as_of IS NULL OR as_of = '' OR as_of <= ?",
            (as_of_iso,),
        )
        return {r[0] for r in cur.fetchall()}

    # ---- ingest log --------------------------------------------------------
    def log_ingest(self, **kw) -> None:
        cols = [
            "source_id", "raw_path", "source_hash", "parser", "parser_version",
            "chunk_count", "figure_count", "table_count", "errors", "at",
        ]
        from datetime import timezone
        kw.setdefault("at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        kw["errors"] = json.dumps(kw.get("errors") or [], ensure_ascii=False)
        with self.tx() as con:
            con.execute(
                f"INSERT INTO ingest_log ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
                [kw.get(c) for c in cols],
            )

    # ---- helpers -----------------------------------------------------------
    def stats(self) -> dict:
        cur = self.con
        return {
            "sources": cur.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "ingest_events": cur.execute("SELECT COUNT(*) FROM ingest_log").fetchone()[0],
            "citations": cur.execute("SELECT COUNT(*) FROM citations").fetchone()[0],
            "concepts": cur.execute("SELECT COUNT(*) FROM concepts").fetchone()[0],
        }


def _normalise(value):
    if isinstance(value, (list, tuple, set)):
        return json.dumps(sorted(list(value)) if isinstance(value, set) else list(value), ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row_to_dict(row: sqlite3.Row | None) -> dict:
    if row is None:
        return {}
    d = dict(row)
    for k in ("domains", "asset_classes", "tags", "extra"):
        v = d.get(k)
        if isinstance(v, str) and v:
            try:
                d[k] = json.loads(v)
            except json.JSONDecodeError:
                pass
    return d
