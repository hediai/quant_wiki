"""Document parsers. All return a ParseResult."""
from .base import ParseResult, ParserError
from .dispatcher import parse

__all__ = ["ParseResult", "ParserError", "parse"]
