"""Office / HTML / CSV parser via MarkItDown when available."""
from __future__ import annotations

from pathlib import Path

from .base import ParseResult, ParserError


def parse_office(path: Path) -> ParseResult:
    try:
        from markitdown import MarkItDown  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dep
        raise ParserError(
            "markitdown not installed; pip install 'quant-wiki[parsers]'"
        ) from exc

    md = MarkItDown()
    try:
        result = md.convert(str(path))
    except Exception as exc:
        raise ParserError(f"markitdown failed on {path.name}: {exc}") from exc

    text = getattr(result, "text_content", None) or getattr(result, "text", "") or ""
    if not text.strip():
        raise ParserError(f"markitdown produced empty output for {path.name}")

    version = _markitdown_version()
    return ParseResult(
        text=text,
        parser="markitdown",
        parser_version=version,
        page_map=[(0, 1)],
    )


def _markitdown_version() -> str:
    try:
        from importlib.metadata import version
        return version("markitdown")
    except Exception:  # pragma: no cover
        return "unknown"
