"""Text utilities: chunking, jieba-based segmentation for FTS."""
from __future__ import annotations

import re
from typing import Iterator


_PUNCT_SPLIT = re.compile(r"(?<=[。！？!?\.])\s+|\n{2,}")


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PUNCT_SPLIT.split(text) if p and p.strip()]


def chunk_text(
    text: str,
    *,
    size: int = 800,
    overlap: int = 120,
) -> list[tuple[int, str]]:
    """Greedy char-based chunker that prefers paragraph boundaries.

    Returns list of (offset, chunk_text). Offsets are character positions in the
    original string so we can map back for citation snippets.
    """
    if not text:
        return []
    text = text.strip()
    n = len(text)
    chunks: list[tuple[int, str]] = []
    i = 0
    while i < n:
        end = min(i + size, n)
        # try to back off to nearest paragraph boundary if we're not at EOF
        if end < n:
            for boundary in ("\n\n", "。", "\n", " "):
                idx = text.rfind(boundary, i + size // 2, end)
                if idx != -1:
                    end = idx + len(boundary)
                    break
        chunk = text[i:end].strip()
        if chunk:
            chunks.append((i, chunk))
        if end >= n:
            break
        i = max(i + 1, end - overlap)
    return chunks


def jieba_tokens(text: str) -> str:
    """Tokenise Chinese text with jieba into space-separated tokens for FTS.

    Falls back to identity if jieba is missing (tests/light env).
    """
    try:
        import jieba  # type: ignore
    except ImportError:  # pragma: no cover - optional dep
        return text
    return " ".join(t for t in jieba.lcut(text) if t.strip())
