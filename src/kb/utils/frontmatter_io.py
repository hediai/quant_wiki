"""Thin wrapper around python-frontmatter for atomic read/write."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import frontmatter


def read_md(path: Path) -> tuple[dict[str, Any], str]:
    post = frontmatter.load(str(path))
    return dict(post.metadata), post.content


def write_md(path: Path, metadata: dict[str, Any], content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(content, **metadata)
    payload = frontmatter.dumps(post, sort_keys=False)
    # Atomic write so concurrent ingest doesn't corrupt a card.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=str(path.parent), suffix=".tmp"
    ) as tmp:
        tmp.write(payload)
        if not payload.endswith("\n"):
            tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
