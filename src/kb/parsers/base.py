"""Parser result types and errors."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict


class FigureBlock(TypedDict, total=False):
    page: int
    image_path: str  # relative to converted/<id>/
    caption: str


class TableBlock(TypedDict, total=False):
    page: int
    caption: str
    csv_path: str  # relative to converted/<id>/
    md: str        # caption + headers + brief summary for indexing


class FormulaBlock(TypedDict, total=False):
    page: int
    latex: str
    caption: str


@dataclass
class ParseResult:
    text: str
    parser: Literal["markitdown", "docling", "marker", "stub"] = "stub"
    parser_version: str = ""
    page_map: list[tuple[int, int]] = field(default_factory=list)
    """List of (char_offset, page_no) markers in `text`. Sorted ascending offset.

    `page_for_offset()` returns the page that contains a given char offset. If
    the parser cannot recover page info (e.g. Office files), the list contains
    a single (0, 1) sentinel.
    """
    tables: list[TableBlock] = field(default_factory=list)
    figures: list[FigureBlock] = field(default_factory=list)
    formulas: list[FormulaBlock] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def page_for_offset(self, offset: int) -> int:
        page = 1
        for ofs, p in self.page_map:
            if ofs <= offset:
                page = p
            else:
                break
        return page


class ParserError(RuntimeError):
    pass
