"""LLM client abstraction.

Goals:
- Run the whole Phase-2 pipeline offline with deterministic heuristics.
- Plug a real provider in (Anthropic / OpenAI / local) via env vars without code edits.
- Provide three tasks the rest of the code needs:
    * `summarise(query, passages)`   → synthesis with citations
    * `judge_stance(claim_a, claim_b)` → support | contradict | unrelated
    * `judge_support(claim, passage)` → bool (citation-faithfulness gate)
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Literal, Protocol, Sequence

log = logging.getLogger(__name__)

Stance = Literal["support", "contradict", "unrelated"]


@dataclass
class Passage:
    source_id: str
    page: int
    text: str

    def citation(self) -> str:
        return f"[^{self.source_id}#page-{self.page}]"


class LLMClient(Protocol):
    name: str
    def summarise(self, query: str, passages: Sequence[Passage], *, max_words: int = 400) -> str: ...
    def judge_stance(self, claim_a: str, claim_b: str) -> Stance: ...
    def judge_support(self, claim: str, passage: str) -> bool: ...


# ---------------------------------------------------------------------------
# Heuristic offline client — always available.
# ---------------------------------------------------------------------------

_NEG = (
    "不", "没", "无", "未", "并非", "并不",
    " not ", " no ", " never ", "doesn't", "didn't", "isn't", "aren't", "won't",
)


class HeuristicClient:
    name = "heuristic"

    def summarise(self, query: str, passages: Sequence[Passage], *, max_words: int = 400) -> str:
        if not passages:
            return f"> 推断：对查询「{query}」无检索命中，需扩大资料或调整 query。\n"
        bullets: list[str] = []
        for p in passages:
            snippet = _trim(p.text, 200)
            bullets.append(f"- {snippet} {p.citation()}")
        return (
            f"> 推断：未启用 LLM，下方为检索命中片段（人工综合）。\n\n"
            f"## 查询\n\n{query}\n\n"
            f"## 命中证据\n\n" + "\n".join(bullets) + "\n"
        )

    def judge_stance(self, claim_a: str, claim_b: str) -> Stance:
        a_neg = _has_negation(claim_a)
        b_neg = _has_negation(claim_b)
        share = _token_overlap(claim_a, claim_b)
        if share < 2:
            return "unrelated"
        if a_neg ^ b_neg:
            return "contradict"
        return "support"

    def judge_support(self, claim: str, passage: str) -> bool:
        terms = _content_terms(claim)
        if not terms:
            return True
        hits = sum(1 for t in terms if t in passage)
        return hits >= max(1, int(len(terms) * 0.6))


# ---------------------------------------------------------------------------
# Anthropic client (optional).
# ---------------------------------------------------------------------------


class AnthropicClient:
    name = "anthropic"

    def __init__(self, model: str | None = None):
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError("anthropic package missing; pip install anthropic") from exc
        self._anthropic = anthropic
        self._client = anthropic.Anthropic()
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    def _call(self, system: str, user: str, *, max_tokens: int = 800) -> str:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    def summarise(self, query: str, passages: Sequence[Passage], *, max_words: int = 400) -> str:
        ctx = "\n\n".join(
            f"### {p.citation()}\n{p.text}" for p in passages
        )
        system = (
            "你是量化研究助理。基于给定的检索片段写出回答，每个事实性结论必须挂上对应的 "
            "[^src-id#page-x] 脚注引用；不允许引用未给出的来源；中文回答。"
        )
        user = f"## 查询\n{query}\n\n## 检索片段\n{ctx}\n\n用 ≤ {max_words} 字综合回答。"
        return self._call(system, user, max_tokens=1200)

    def judge_stance(self, claim_a: str, claim_b: str) -> Stance:
        system = (
            "你判断两条量化研究结论的关系。只输出 JSON：{\"stance\":\"support|contradict|unrelated\"}。"
        )
        user = f"A: {claim_a}\nB: {claim_b}"
        out = self._call(system, user, max_tokens=60)
        m = re.search(r'"stance"\s*:\s*"(support|contradict|unrelated)"', out)
        return m.group(1) if m else "unrelated"  # type: ignore[return-value]

    def judge_support(self, claim: str, passage: str) -> bool:
        system = "判断引用片段是否真实支持给定的 claim。只输出 JSON：{\"supports\": true|false}。"
        user = f"Claim: {claim}\nPassage: {passage}"
        out = self._call(system, user, max_tokens=20)
        m = re.search(r'"supports"\s*:\s*(true|false)', out)
        return bool(m and m.group(1) == "true")


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def get_llm(prefer: str | None = None) -> LLMClient:
    pref = (prefer or os.environ.get("KB_LLM", "auto")).lower()
    if pref in ("heuristic", "offline", "none"):
        return HeuristicClient()
    if pref in ("anthropic", "claude"):
        try:
            return AnthropicClient()
        except Exception as exc:
            log.warning("AnthropicClient unavailable (%s); falling back to heuristic.", exc)
            return HeuristicClient()
    # auto: try anthropic only if API key is set, else heuristic.
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return AnthropicClient()
        except Exception as exc:
            log.warning("Anthropic auto-init failed (%s); using heuristic.", exc)
    return HeuristicClient()


# ---------------------------------------------------------------------------
# Helpers shared by the heuristic client.
# ---------------------------------------------------------------------------

def _has_negation(s: str) -> bool:
    s_low = s.lower()
    return any(neg in s_low for neg in _NEG)


def _content_terms(s: str) -> list[str]:
    # Pull mid-length tokens, dropping stopwords-ish noise.
    try:
        import jieba  # type: ignore
        toks = jieba.lcut(s)
    except ImportError:  # pragma: no cover
        toks = re.split(r"\W+", s)
    out: list[str] = []
    for t in toks:
        t = t.strip()
        if len(t) < 2:
            continue
        if t in {"的", "了", "和", "与", "或", "是", "在", "对", "为"}:
            continue
        out.append(t)
    return out


def _token_overlap(a: str, b: str) -> int:
    return len(set(_content_terms(a)) & set(_content_terms(b)))


def _trim(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"
