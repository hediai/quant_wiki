"""Trivial plain-text/Markdown parser — always available, no heavy deps."""
from __future__ import annotations

from pathlib import Path

from .base import ParseResult


def parse_plain(path: Path) -> ParseResult:
    text = path.read_text(encoding="utf-8", errors="replace")
    return ParseResult(
        text=text,
        parser="stub",
        parser_version="plain-1",
        page_map=[(0, 1)],
    )
