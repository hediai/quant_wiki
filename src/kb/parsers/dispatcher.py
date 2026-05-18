"""Decide which parser to use based on extension."""
from __future__ import annotations

from pathlib import Path

from .base import ParseResult, ParserError
from .plain import parse_plain
from .pdf import parse_pdf
from .office import parse_office


_OFFICE_EXTS = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".html", ".htm", ".csv", ".tsv"}
_PLAIN_EXTS = {".md", ".markdown", ".txt"}


def parse(path: Path, out_dir: Path) -> ParseResult:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return parse_pdf(path, out_dir)
    if ext in _OFFICE_EXTS:
        try:
            return parse_office(path)
        except ParserError:
            if ext in {".html", ".htm", ".csv", ".tsv"}:
                return parse_plain(path)
            raise
    if ext in _PLAIN_EXTS:
        return parse_plain(path)
    raise ParserError(f"unsupported extension: {ext}")
