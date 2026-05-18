"""Concept evolution: stubs, evidence aggregation, contradiction detection.

Design
------
A *claim* is one bullet/sentence extracted from a Source Card's "关键结论" /
"主要结论" section. For each new source we:

1. Extract its claims.
2. For each claim, find the most semantically similar Concept Card via vector
   similarity over concept titles + "定义" + existing "关键结论".
3. If similarity ≥ MATCH_THRESHOLD:
   - call `llm.judge_stance(claim, concept_summary)` → support | contradict | unrelated
   - support → append to `## Evidence For`
   - contradict → append to `## Evidence Against`, log to conflicts.jsonl,
     set concept.status='disputed'
   - unrelated → ignore
4. If no match above threshold and the claim has ≥ MIN_NOVELTY content terms,
   write a *stub proposal* into `inbox/concepts/<slug>.md` for human review —
   we never auto-create concept pages.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from slugify import slugify

from .config import Paths
from .index import MetaStore
from .llm import LLMClient, Passage, Stance
from .utils.frontmatter_io import read_md, write_md
from .utils.ids import concept_id

log = logging.getLogger(__name__)


MATCH_THRESHOLD = float(0.55)
PROPOSAL_THRESHOLD = float(0.35)  # below: too vague to even propose a stub
MIN_CLAIM_LEN = 8
MAX_CLAIM_LEN = 220


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

_CLAIM_SECTION_RE = re.compile(
    r"^#{1,4}\s+(?:关键结论|主要结论|核心观点|结论|key takeaways?|conclusions?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_NEXT_HEADING_RE = re.compile(r"^#{1,4}\s+", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*•]\s+(.+)$", re.MULTILINE)


def extract_claims(text: str) -> list[str]:
    section = _find_section(text)
    if section is None:
        return []
    bullets = _BULLET_RE.findall(section)
    out: list[str] = []
    for b in bullets:
        s = _clean_claim(b)
        if MIN_CLAIM_LEN <= len(s) <= MAX_CLAIM_LEN:
            out.append(s)
    return out


def _find_section(text: str) -> str | None:
    m = _CLAIM_SECTION_RE.search(text)
    if not m:
        return None
    start = m.end()
    n = _NEXT_HEADING_RE.search(text, start)
    end = n.start() if n else len(text)
    return text[start:end]


def _clean_claim(s: str) -> str:
    # strip footnote markers and trailing punctuation noise
    s = re.sub(r"\[\^[^\]]+\]", "", s)
    return s.strip(" .。；;")


# ---------------------------------------------------------------------------
# Concept index (read-side)
# ---------------------------------------------------------------------------


@dataclass
class ConceptDigest:
    id: str
    title: str
    path: Path
    summary: str          # title + 定义 + 关键结论 (truncated)


def load_concepts(paths: Paths) -> list[ConceptDigest]:
    if not paths.concepts.exists():
        return []
    out: list[ConceptDigest] = []
    for md in sorted(paths.concepts.glob("*.md")):
        try:
            fm, body = read_md(md)
        except Exception as exc:
            log.warning("concept %s unreadable: %s", md, exc)
            continue
        cid = fm.get("id") or concept_id(md.stem)
        title = fm.get("title") or md.stem
        summary = _concept_summary(title, body)
        out.append(ConceptDigest(id=cid, title=title, path=md, summary=summary))
    return out


_DEF_RE = re.compile(r"^#{1,4}\s+(?:定义|definition).*?\n(.+?)(?=\n#|\Z)", re.IGNORECASE | re.DOTALL | re.MULTILINE)
_CONCL_RE = re.compile(r"^#{1,4}\s+(?:关键结论|核心观点).*?\n(.+?)(?=\n#|\Z)", re.IGNORECASE | re.DOTALL | re.MULTILINE)


def _concept_summary(title: str, body: str) -> str:
    parts = [title]
    m = _DEF_RE.search(body)
    if m:
        parts.append(m.group(1).strip())
    m = _CONCL_RE.search(body)
    if m:
        parts.append(m.group(1).strip())
    return "\n".join(parts)[:1200]


# ---------------------------------------------------------------------------
# Matching + evidence aggregation
# ---------------------------------------------------------------------------


@dataclass
class EvidenceUpdate:
    concept_id: str
    concept_path: Path
    claim: str
    stance: Stance
    source_id: str
    page: int


def attach_evidence(
    *,
    source_id: str,
    claims: list[str],
    paths: Paths,
    meta: MetaStore,
    embedder,
    llm: LLMClient,
    page: int = 1,
) -> tuple[list[EvidenceUpdate], list[dict]]:
    """Return (updates_applied, proposals_written).

    Proposals (claims with no good concept match) are dropped as stubs into
    `inbox/concepts/` for the user to triage.
    """
    if not claims:
        return [], []

    concepts = load_concepts(paths)
    proposals: list[dict] = []
    applied: list[EvidenceUpdate] = []

    if concepts:
        c_vecs = embedder.encode([c.summary for c in concepts])
    else:
        c_vecs = []

    claim_vecs = embedder.encode(claims)

    for claim, qv in zip(claims, claim_vecs):
        best_score, best = -1.0, None
        for c, cv in zip(concepts, c_vecs):
            s = _cosine(qv, cv)
            if s > best_score:
                best_score, best = s, c

        if best is None or best_score < PROPOSAL_THRESHOLD:
            proposals.append(_write_concept_proposal(paths, claim, source_id, page))
            continue
        if best_score < MATCH_THRESHOLD:
            proposals.append(_write_concept_proposal(paths, claim, source_id, page, near=best.id))
            continue

        stance = llm.judge_stance(claim, best.summary)
        if stance == "unrelated":
            continue
        _append_evidence(best.path, claim=claim, source_id=source_id, page=page, stance=stance)
        if stance == "contradict":
            _record_conflict(paths, concept_id=best.id, claim=claim, source_id=source_id, page=page, score=best_score)
            _mark_disputed(best.path)
        applied.append(EvidenceUpdate(
            concept_id=best.id, concept_path=best.path,
            claim=claim, stance=stance, source_id=source_id, page=page,
        ))

    return applied, proposals


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _append_evidence(path: Path, *, claim: str, source_id: str, page: int, stance: Stance) -> None:
    section_title = "## Evidence For" if stance == "support" else "## Evidence Against"
    fm, body = read_md(path)
    entry = f"- [{source_id}#page-{page}] {claim}"
    body = _upsert_section(body, section_title, entry)
    # Touch last_reviewed.
    fm["last_reviewed"] = dt.date.today().isoformat()
    write_md(path, fm, body)


def _mark_disputed(path: Path) -> None:
    fm, body = read_md(path)
    if fm.get("status") == "disputed":
        return
    fm["status"] = "disputed"
    today = dt.date.today().isoformat()
    body = _upsert_section(body, "## Changelog", f"- {today}: 状态置为 disputed（contradiction detected）")
    write_md(path, fm, body)


def _record_conflict(paths: Paths, *, concept_id: str, claim: str, source_id: str, page: int, score: float) -> None:
    paths.conflicts.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "concept_id": concept_id, "claim": claim,
        "source_id": source_id, "page": page,
        "similarity": round(score, 3),
        "detected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    with open(paths.conflicts, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_concept_proposal(paths: Paths, claim: str, source_id: str, page: int, *, near: str | None = None) -> dict:
    inbox = paths.root / "inbox" / "concepts"
    inbox.mkdir(parents=True, exist_ok=True)
    slug = slugify(claim, lowercase=True, allow_unicode=False, max_length=40) or "claim"
    path = inbox / f"{slug}.md"
    note = (
        f"# 候选概念：{claim[:80]}\n\n"
        f"> 由 `kb compile {source_id}` 触发的概念候选。请人工审查后决定是否在 `wiki/concepts/` 建页。\n\n"
        f"- claim: {claim}\n"
        f"- 来源: {source_id}#page-{page}\n"
        + (f"- 最接近的现有概念: {near}（未达 match 阈值）\n" if near else "")
    )
    if not path.exists():
        path.write_text(note, encoding="utf-8")
    return {"path": str(path), "claim": claim, "source_id": source_id, "near": near}


# ---------------------------------------------------------------------------
# Concept stub creation (manual or LLM-assisted later)
# ---------------------------------------------------------------------------


def create_concept_stub(
    title: str,
    *,
    paths: Paths,
    definition: str = "",
    domains: list[str] | None = None,
) -> Path:
    cid = concept_id(title)
    path = paths.concepts / f"{cid}.md"
    if path.exists():
        return path
    fm = {
        "id": cid, "type": "concept", "title": title,
        "domains": domains or [],
        "status": "active",
        "last_reviewed": dt.date.today().isoformat(),
        "superseded_by": None,
    }
    body = (
        f"# {title}\n\n"
        f"## 定义\n\n{definition or '_TODO_'}\n\n"
        f"## 关键结论\n\n_TODO_\n\n"
        f"## Evidence For\n\n_由 `kb compile` 自动聚合。_\n\n"
        f"## Evidence Against\n\n_由 `kb compile` 自动聚合。_\n\n"
        f"## 适用条件\n\n_TODO_\n\n"
        f"## 相关\n\n_TODO_\n\n"
        f"## Changelog\n\n- {dt.date.today().isoformat()}: 新建 stub\n"
    )
    write_md(path, fm, body)
    return path


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _cosine(a, b) -> float:
    if not a or not b:
        return 0.0
    s = sum(x * y for x, y in zip(a, b))
    # Both bge-m3 and ZeroEmbedder return L2-normalised vectors → dot product = cosine.
    return float(s)


def _upsert_section(body: str, heading: str, line: str) -> str:
    """Append `line` under `heading` (creating the section if missing).

    Idempotent: skips when `line` is already present.
    """
    if heading not in body:
        sep = "\n\n" if body and not body.endswith("\n\n") else ""
        return body + f"{sep}{heading}\n\n{line}\n"
    parts = body.split(heading, 1)
    head, rest = parts[0], parts[1]
    # rest is the body of the section + everything after
    next_h = _NEXT_HEADING_RE.search(rest)
    if next_h is None:
        section, tail = rest, ""
    else:
        section, tail = rest[: next_h.start()], rest[next_h.start():]
    section = section.rstrip()
    if line in section:
        return body  # already there
    section += "\n" + line + "\n"
    return head + heading + section + ("\n" + tail if tail else "\n")
