"""Ingest pipeline: hash → parse → manifest → index → source stub."""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from . import config
from .config import Paths
from .index import MetaStore, VectorStore, get_embedder
from .parsers import ParserError, parse
from .utils.frontmatter_io import write_md
from .utils.hashing import file_sha256
from .utils.ids import chunk_id, source_id
from .utils.text import chunk_text, jieba_tokens

log = logging.getLogger(__name__)


SUPPORTED = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
    ".html", ".htm", ".csv", ".tsv", ".md", ".markdown", ".txt",
}


@dataclass
class IngestResult:
    source_id: str
    raw_path: Path
    source_hash: str
    parser: str
    parser_version: str
    chunk_count: int
    figure_count: int
    table_count: int
    errors: list[str]
    skipped: bool = False
    reason: str = ""


def ingest_path(
    target: Path,
    *,
    paths: Paths,
    meta: MetaStore,
    vstore: VectorStore | None = None,
    embedder=None,
    domain_hint: str | None = None,
    institution_hint: str | None = None,
    license_hint: str = "internal",
) -> list[IngestResult]:
    target = target.resolve()
    if target.is_dir():
        files = sorted(_walk(target))
    elif target.is_file():
        files = [target]
    else:
        raise FileNotFoundError(target)

    results: list[IngestResult] = []
    for f in files:
        if f.suffix.lower() not in SUPPORTED:
            log.debug("skip unsupported: %s", f)
            continue
        results.append(_ingest_one(
            f, paths=paths, meta=meta, vstore=vstore, embedder=embedder,
            domain_hint=domain_hint, institution_hint=institution_hint,
            license_hint=license_hint,
        ))
    return results


def _walk(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and not p.name.startswith("."):
            yield p


def _ingest_one(
    f: Path, *, paths: Paths, meta: MetaStore, vstore, embedder,
    domain_hint, institution_hint, license_hint,
) -> IngestResult:
    sha = file_sha256(f)
    existing = meta.get_source_by_hash(sha)
    if existing:
        log.info("skip duplicate (hash match): %s -> %s", f.name, existing["id"])
        return IngestResult(
            source_id=existing["id"], raw_path=f, source_hash=sha,
            parser=existing.get("parser") or "", parser_version=existing.get("parser_version") or "",
            chunk_count=0, figure_count=0, table_count=0, errors=[],
            skipped=True, reason="duplicate hash",
        )

    # Mint a source_id from file metadata. Phase 1 uses filename heuristics; Phase 2
    # can pull institution/topic from the parsed text.
    domain = domain_hint or _infer_domain(f)
    institution = institution_hint or _infer_institution(f)
    topic = _infer_topic(f)
    year = _infer_year(f)
    seq = _next_seq(meta, year=year, institution=institution, topic=topic)
    sid = source_id(year=year, institution=institution, topic=topic, seq=seq)

    out_dir = paths.converted / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    try:
        result = parse(f, out_dir)
    except ParserError as exc:
        errors.append(str(exc))
        # Write a stub so we can see failures in lint.
        manifest = {
            "source_id": sid, "source_hash": sha, "raw_path": str(f),
            "parser": "stub", "parser_version": "n/a",
            "page_map": [(0, 1)], "tables": [], "figures": [], "formulas": [],
            "errors": errors,
        }
        (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_source_stub(paths, sid=sid, raw=f, sha=sha, status="failed",
                           domain=domain, institution=institution, license=license_hint,
                           parser="stub", parser_version="n/a", date_str=_today())
        meta.upsert_source({
            "id": sid, "title": f.stem, "institution": institution,
            "date": _today(), "as_of": _today(),
            "domains": [domain], "asset_classes": [],
            "tags": [], "license": license_hint,
            "source_hash": sha, "parser": "stub", "parser_version": "n/a",
            "status": "failed", "raw_path": str(f),
            "ingested_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "extra": {},
        })
        meta.log_ingest(
            source_id=sid, raw_path=str(f), source_hash=sha,
            parser="stub", parser_version="n/a",
            chunk_count=0, figure_count=0, table_count=0, errors=errors,
        )
        return IngestResult(
            source_id=sid, raw_path=f, source_hash=sha,
            parser="stub", parser_version="n/a",
            chunk_count=0, figure_count=0, table_count=0, errors=errors,
        )

    # Persist main text + manifest.
    (out_dir / "doc.md").write_text(result.text, encoding="utf-8")
    manifest = {
        "source_id": sid, "source_hash": sha, "raw_path": str(f),
        "parser": result.parser, "parser_version": result.parser_version,
        "page_map": result.page_map, "tables": result.tables,
        "figures": result.figures, "formulas": result.formulas,
        "errors": result.errors,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # Chunk + embed + index.
    chunk_count = 0
    if vstore is not None:
        chunks = chunk_text(result.text, size=config.CHUNK_SIZE, overlap=config.CHUNK_OVERLAP)
        # Also include table .md blobs as standalone chunks so tables become searchable.
        for t in result.tables:
            if t.get("md"):
                chunks.append((-1, t["md"]))  # offset -1 → "synthetic"
        # And figure captions, if any.
        for fg in result.figures:
            if fg.get("caption"):
                chunks.append((-1, f"[图] {fg['caption']}"))
        rows = []
        texts_for_embed = [c[1] for c in chunks]
        vectors = embedder.encode(texts_for_embed) if embedder and texts_for_embed else [None] * len(chunks)
        as_of_iso = _today()
        for (offset, txt), vec in zip(chunks, vectors):
            page = result.page_for_offset(offset) if offset >= 0 else 1
            cid = chunk_id(sid, page, max(offset, 0))
            rows.append({
                "chunk_id": cid, "source_id": sid,
                "page": page, "offset": max(offset, 0),
                "text": txt, "tokens": jieba_tokens(txt),
                "domains": [domain], "as_of": as_of_iso,
                "license": license_hint, "vector": vec,
            })
        vstore.delete_source(sid)
        vstore.add_chunks(rows)
        chunk_count = len(rows)

    # Write a minimal Source Card stub (kb compile will enrich it).
    _write_source_stub(
        paths, sid=sid, raw=f, sha=sha, status="active",
        domain=domain, institution=institution, license=license_hint,
        parser=result.parser, parser_version=result.parser_version,
        date_str=_today(),
    )

    meta.upsert_source({
        "id": sid, "title": f.stem, "institution": institution,
        "date": _today(), "as_of": _today(),
        "domains": [domain], "asset_classes": [],
        "tags": [], "license": license_hint,
        "source_hash": sha, "parser": result.parser,
        "parser_version": result.parser_version,
        "status": "active", "raw_path": str(f),
        "ingested_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "extra": {},
    })
    meta.log_ingest(
        source_id=sid, raw_path=str(f), source_hash=sha,
        parser=result.parser, parser_version=result.parser_version,
        chunk_count=chunk_count,
        figure_count=len(result.figures), table_count=len(result.tables),
        errors=result.errors,
    )

    return IngestResult(
        source_id=sid, raw_path=f, source_hash=sha,
        parser=result.parser, parser_version=result.parser_version,
        chunk_count=chunk_count, figure_count=len(result.figures),
        table_count=len(result.tables), errors=result.errors,
    )


# ---- inference helpers -------------------------------------------------------
_YEAR_RE = re.compile(r"(20\d{2})")


def _infer_year(f: Path) -> int:
    # Look in filename, then parent dirs.
    for token in [f.stem, *[p.name for p in f.parents]]:
        m = _YEAR_RE.search(token)
        if m:
            return int(m.group(1))
    return dt.datetime.now().year


def _infer_domain(f: Path) -> str:
    # Use first ancestor whose name matches a known domain.
    known = {"选股", "资产配置", "机器学习", "深度学习", "通用方法"}
    for p in f.parents:
        if p.name in known:
            return p.name
    return "通用方法"


def _infer_institution(f: Path) -> str:
    # Filename like "中信证券-动量因子.pdf" → "中信证券".
    name = f.stem
    for sep in ("-", "_", " "):
        if sep in name:
            return name.split(sep, 1)[0]
    return "unknown"


def _infer_topic(f: Path) -> str:
    name = f.stem
    for sep in ("-", "_"):
        if sep in name:
            return name.split(sep, 1)[1]
    return name


def _today() -> str:
    return dt.date.today().isoformat()


def _next_seq(meta: MetaStore, *, year: int, institution: str, topic: str) -> int:
    """Allocate next 3-digit sequence for this (year, institution, topic) triple."""
    from .utils.ids import _safe_slug  # type: ignore
    prefix = f"src-{year}-{_safe_slug(institution, 24)}-{_safe_slug(topic, 32)}-"
    cur = meta.con.execute(
        "SELECT id FROM sources WHERE id LIKE ?", (prefix + "%",),
    )
    nums = []
    for (sid,) in cur.fetchall():
        tail = sid[len(prefix):]
        try:
            nums.append(int(tail))
        except ValueError:
            pass
    return (max(nums) + 1) if nums else 1


def _write_source_stub(
    paths: Paths, *, sid: str, raw: Path, sha: str, status: str,
    domain: str, institution: str, license: str,
    parser: str, parser_version: str, date_str: str,
) -> None:
    md_path = paths.sources / f"{sid}.md"
    if md_path.exists():
        return  # don't clobber a curated card
    fm = {
        "id": sid, "type": "source", "title": raw.stem,
        "institution": institution, "authors": [], "date": date_str,
        "as_of": date_str, "domains": [domain], "asset_classes": [],
        "tags": [], "license": license, "source_hash": sha,
        "parser": parser, "parser_version": parser_version,
        "status": status, "raw_path": str(raw),
        "ingested_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    body = (
        f"# {raw.stem}\n\n"
        f"> Stub Source Card. Enrich via `kb compile {sid}`.\n\n"
        f"## 关键结论\n\n"
        f"_TODO 由 `kb compile` 自动抽取草稿，需人工 review。_\n\n"
        f"## 方法\n\n"
        f"_TODO_\n\n"
        f"## 适用场景与局限\n\n"
        f"_TODO_\n\n"
        f"## 引用\n\n"
        f"converted: [doc.md](../../converted/{sid}/doc.md)、manifest: [manifest.json](../../converted/{sid}/manifest.json)\n"
    )
    write_md(md_path, fm, body)
