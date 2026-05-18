"""Deterministic ID minting per kb.schema.md."""
from __future__ import annotations

import datetime as dt
import re
from typing import Iterable

from slugify import slugify


_ID_CHARS = re.compile(r"[^a-z0-9-]")
MAX_ID_LEN = 80


def _safe_slug(s: str, max_len: int = 40) -> str:
    out = slugify(s or "", lowercase=True, allow_unicode=False, max_length=max_len)
    out = _ID_CHARS.sub("-", out).strip("-")
    return out or "x"


def source_id(
    *,
    year: int | str,
    institution: str,
    topic: str,
    seq: int,
) -> str:
    return _clip(f"src-{int(year)}-{_safe_slug(institution, 24)}-{_safe_slug(topic, 32)}-{int(seq):03d}")


def concept_id(topic: str) -> str:
    return _clip(f"concept-{_safe_slug(topic, 60)}")


def factor_id(name: str, version: str | int) -> str:
    v = str(version).lstrip("v")
    return _clip(f"factor-{_safe_slug(name, 50)}-v{v}")


def thread_id(topic: str, quarter: str | None = None) -> str:
    q = quarter or _current_quarter()
    return _clip(f"thread-{_safe_slug(topic, 50)}-{q}")


def memo_id(query: str, *, when: dt.datetime | None = None, rand_hex: str = "") -> str:
    when = when or dt.datetime.now()
    base = f"memo-{when:%Y-%m-%d}-{_safe_slug(query, 40)}"
    if rand_hex:
        base += f"-{rand_hex[:4]}"
    return _clip(base)


def experiment_id(topic: str, *, when: dt.datetime | None = None, rand_hex: str = "") -> str:
    when = when or dt.datetime.now()
    base = f"exp-{when:%Y-%m-%d}-{_safe_slug(topic, 42)}"
    if rand_hex:
        base += f"-{rand_hex[:4]}"
    return _clip(base)


def _current_quarter(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    return f"{now.year}q{(now.month - 1) // 3 + 1}"


def _clip(s: str) -> str:
    return s[:MAX_ID_LEN]


def chunk_id(source_id: str, page: int | None, offset: int) -> str:
    p = page if page is not None else 0
    return f"{source_id}:p{p}:o{offset}"


def parse_chunk_id(cid: str) -> tuple[str, int, int]:
    """Inverse of chunk_id. Returns (source_id, page, offset)."""
    src, p, o = cid.rsplit(":", 2)
    return src, int(p[1:]), int(o[1:])
