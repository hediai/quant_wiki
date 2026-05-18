"""PDF parser: Docling primary, Marker fallback, pypdf as last resort."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from .base import ParseResult, ParserError, TableBlock, FigureBlock

log = logging.getLogger(__name__)


def parse_pdf(path: Path, out_dir: Path) -> ParseResult:
    """Try parsers in order. out_dir is converted/<source_id>/ where tables/figures land."""
    errors: list[str] = []
    for name, fn in (
        ("docling", _try_docling),
        ("marker", _try_marker),
        ("pypdf", _try_pypdf),
    ):
        try:
            result = fn(path, out_dir)
            if result.text.strip():
                if errors:
                    result.errors.extend(errors)
                return result
            errors.append(f"{name}: empty output")
        except ParserError as exc:
            errors.append(f"{name}: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"{name}: {exc!r}")
            log.exception("Unexpected error in %s", name)
    raise ParserError("; ".join(errors) or "all PDF parsers failed")


def _try_docling(path: Path, out_dir: Path) -> ParseResult:
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except ImportError as exc:
        raise ParserError(f"docling missing: {exc}") from exc

    conv = DocumentConverter()
    result = conv.convert(str(path))
    doc = result.document
    text = doc.export_to_markdown()

    page_map, tables, figures = _docling_blocks(doc, out_dir)

    return ParseResult(
        text=text,
        parser="docling",
        parser_version=_pkg_version("docling"),
        page_map=page_map or [(0, 1)],
        tables=tables,
        figures=figures,
    )


def _docling_blocks(doc, out_dir: Path) -> tuple[list[tuple[int, int]], list[TableBlock], list[FigureBlock]]:
    """Extract (offset->page) map, table CSVs, figure paths from a Docling doc.

    Docling's APIs evolve quickly across versions; we defensively pull what we can.
    """
    page_map: list[tuple[int, int]] = [(0, 1)]
    tables: list[TableBlock] = []
    figures: list[FigureBlock] = []

    tables_dir = out_dir / "tables"
    figures_dir = out_dir / "figures"

    try:
        for i, tbl in enumerate(getattr(doc, "tables", []) or []):
            page = _safe_page(tbl)
            caption = _safe_caption(tbl)
            csv_rel = f"tables/{i:03d}.csv"
            md_rel = f"tables/{i:03d}.md"
            try:
                df = tbl.export_to_dataframe()
                tables_dir.mkdir(parents=True, exist_ok=True)
                df.to_csv(out_dir / csv_rel, index=False)
                # Indexable md: caption + header + first 3 rows.
                head = df.head(3).to_markdown(index=False) if len(df) else ""
                md_payload = f"# 表 {i} {caption}\n\n{head}\n"
                (out_dir / md_rel).write_text(md_payload, encoding="utf-8")
                tables.append({
                    "page": page, "caption": caption,
                    "csv_path": csv_rel, "md": md_payload,
                })
            except Exception as exc:
                log.debug("table %s export failed: %s", i, exc)
    except Exception as exc:
        log.debug("docling tables enumeration failed: %s", exc)

    try:
        for i, fig in enumerate(getattr(doc, "pictures", []) or []):
            page = _safe_page(fig)
            caption = _safe_caption(fig)
            try:
                pil = fig.image.pil_image if hasattr(fig, "image") else None
                if pil is not None:
                    figures_dir.mkdir(parents=True, exist_ok=True)
                    img_rel = f"figures/{i:03d}.png"
                    pil.save(out_dir / img_rel)
                    figures.append({"page": page, "image_path": img_rel, "caption": caption})
            except Exception as exc:
                log.debug("figure %s export failed: %s", i, exc)
    except Exception as exc:
        log.debug("docling pictures enumeration failed: %s", exc)

    return page_map, tables, figures


def _safe_page(obj) -> int:
    for attr in ("page_no", "page", "page_number"):
        v = getattr(obj, attr, None)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    prov = getattr(obj, "prov", None)
    if prov:
        try:
            return int(prov[0].page_no)
        except Exception:
            pass
    return 1


def _safe_caption(obj) -> str:
    cap = getattr(obj, "caption", None) or getattr(obj, "captions", None)
    if isinstance(cap, list) and cap:
        return str(cap[0])
    return str(cap or "")


def _try_marker(path: Path, out_dir: Path) -> ParseResult:
    try:
        from marker.converters.pdf import PdfConverter  # type: ignore
        from marker.models import create_model_dict  # type: ignore
        from marker.output import text_from_rendered  # type: ignore
    except ImportError as exc:
        raise ParserError(f"marker missing: {exc}") from exc

    try:
        converter = PdfConverter(artifact_dict=create_model_dict())
        rendered = converter(str(path))
        text, _, _ = text_from_rendered(rendered)
    except Exception as exc:
        raise ParserError(f"marker failed: {exc}") from exc

    if not text:
        raise ParserError("marker produced empty output")

    return ParseResult(
        text=text,
        parser="marker",
        parser_version=_pkg_version("marker-pdf"),
        page_map=[(0, 1)],
    )


def _try_pypdf(path: Path, out_dir: Path) -> ParseResult:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise ParserError(f"pypdf missing: {exc}") from exc

    reader = PdfReader(str(path))
    parts: list[str] = []
    page_map: list[tuple[int, int]] = []
    cursor = 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        page_map.append((cursor, i))
        block = t.strip()
        if block:
            parts.append(block)
            cursor += len(block) + 2  # we'll join with \n\n

    text = "\n\n".join(parts)
    if not text.strip():
        raise ParserError("pypdf could not extract any text (likely scanned PDF)")

    return ParseResult(
        text=text,
        parser="marker",  # not strictly marker; record as fallback string
        parser_version=f"pypdf-{_pkg_version('pypdf')}",
        page_map=page_map or [(0, 1)],
    )


def _pkg_version(name: str) -> str:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return "unknown"
