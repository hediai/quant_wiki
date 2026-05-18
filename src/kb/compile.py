"""Compile: enrich Source Cards from the converted manifest + doc.md.

Phase 1 produced a Source Card stub with auto-extracted summary/conclusions.
Phase 2 layers on:
  * concept evidence aggregation — extract claims and route them to matching
    Concept Cards (Evidence For/Against) or write proposal stubs in inbox/.
  * contradiction detection via LLM stance judgement.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .concepts import attach_evidence, extract_claims
from .config import Paths
from .index import MetaStore
from .llm import LLMClient
from .utils.frontmatter_io import read_md, write_md

log = logging.getLogger(__name__)


@dataclass
class CompileResult:
    source_id: str
    card_path: Path
    claims: int
    evidence_applied: int
    proposals_written: int


def compile_source(
    source_id: str,
    *,
    paths: Paths,
    meta: MetaStore,
    embedder=None,
    llm: LLMClient | None = None,
    aggregate_evidence: bool = True,
) -> CompileResult:
    src = meta.get_source(source_id)
    if not src:
        raise KeyError(f"unknown source: {source_id}")

    out_dir = paths.converted / source_id
    manifest_path = out_dir / "manifest.json"
    doc_path = out_dir / "doc.md"
    if not manifest_path.exists() or not doc_path.exists():
        raise FileNotFoundError(f"converted artefacts missing for {source_id}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    text = doc_path.read_text(encoding="utf-8")

    md_path = paths.sources / f"{source_id}.md"
    meta_fm, _ = read_md(md_path) if md_path.exists() else ({}, "")

    fm = {**meta_fm, **{
        "id": source_id, "type": "source",
        "title": src.get("title") or source_id,
        "institution": src.get("institution"),
        "date": src.get("date"), "as_of": src.get("as_of"),
        "domains": src.get("domains") or [],
        "asset_classes": src.get("asset_classes") or [],
        "tags": src.get("tags") or [],
        "license": src.get("license"),
        "source_hash": src.get("source_hash"),
        "parser": src.get("parser"),
        "parser_version": src.get("parser_version"),
        "status": src.get("status") or "active",
        "raw_path": src.get("raw_path"),
        "ingested_at": src.get("ingested_at"),
    }}

    body_parts: list[str] = [f"# {fm['title']}\n"]
    summary = _first_summary(text)
    if summary:
        body_parts.append("## 摘要\n\n" + summary + "\n")

    conclusions = _extract_conclusions(text)
    if conclusions:
        body_parts.append("## 关键结论\n")
        for c in conclusions:
            body_parts.append(f"- {c}  [^{source_id}#page-1]")
        body_parts.append("")

    method = _extract_section(text, ("方法", "方法论", "method", "methodology"))
    if method:
        body_parts.append("## 方法\n\n" + method + "\n")

    if manifest.get("tables"):
        body_parts.append("## 关键表格\n")
        for i, t in enumerate(manifest["tables"][:5]):
            cap = (t.get("caption") or f"表 {i}").strip()
            body_parts.append(f"- {cap}（第 {t.get('page','?')} 页）— `converted/{source_id}/{t.get('csv_path','')}`")
        body_parts.append("")

    if manifest.get("figures"):
        body_parts.append("## 关键图\n")
        for i, fg in enumerate(manifest["figures"][:5]):
            cap = (fg.get("caption") or f"图 {i}").strip()
            body_parts.append(f"- {cap}（第 {fg.get('page','?')} 页）— `converted/{source_id}/{fg.get('image_path','')}`")
        body_parts.append("")

    body_parts.append("## 引用\n")
    body_parts.append(f"converted: [doc.md](../../converted/{source_id}/doc.md)、manifest: [manifest.json](../../converted/{source_id}/manifest.json)")
    body_parts.append("")
    body_parts.append("## Changelog\n")
    body_parts.append(f"- {fm.get('ingested_at','')}: `kb compile` 自动生成草稿\n")

    write_md(md_path, fm, "\n".join(body_parts))

    applied: list = []
    proposals: list = []
    if aggregate_evidence and embedder is not None and llm is not None:
        claims = extract_claims(text)
        applied, proposals = attach_evidence(
            source_id=source_id, claims=claims, paths=paths,
            meta=meta, embedder=embedder, llm=llm,
            page=1,
        )

    return CompileResult(
        source_id=source_id, card_path=md_path,
        claims=len(applied) + len(proposals),
        evidence_applied=len(applied),
        proposals_written=len(proposals),
    )


_HEADING_RE = re.compile(r"^#{1,3}\s+(.*?)\s*$", re.MULTILINE)


def _first_summary(text: str) -> str:
    # Take the first non-heading paragraph from the top of the document, capped.
    for para in text.split("\n\n"):
        s = para.strip()
        if not s or s.startswith("#"):
            continue
        return s[:600]
    return ""


def _extract_conclusions(text: str) -> list[str]:
    section = _extract_section(text, ("结论", "主要结论", "核心观点", "conclusion", "conclusions", "key takeaways"))
    if not section:
        return []
    bullets = re.findall(r"^[\-\*•]\s+(.+)$", section, re.MULTILINE)
    if bullets:
        return [b.strip()[:200] for b in bullets[:8]]
    # Fallback: split into sentences.
    sents = re.split(r"(?<=[。.！!])", section)
    return [s.strip() for s in sents if s.strip()][:6]


def _extract_section(text: str, keywords: tuple[str, ...]) -> str:
    # Find a heading that contains any keyword and return the body until the next heading.
    matches = list(_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        title = m.group(1).lower()
        if any(k.lower() in title for k in keywords):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            return text[start:end].strip()
    return ""
