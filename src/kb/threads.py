"""Thread / project archive helpers."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from .config import Paths
from .utils.frontmatter_io import write_md
from .utils.ids import thread_id


def new_thread(topic: str, *, paths: Paths, hypotheses: list[str] | None = None) -> Path:
    tid = thread_id(topic)
    slug = tid[len("thread-"):]
    folder = paths.threads / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "memos").mkdir(exist_ok=True)

    fm = {
        "id": tid, "type": "thread", "title": topic,
        "status": "exploring",
        "hypotheses": hypotheses or [],
        "open_questions": [],
        "sources_read": [],
        "sources_queue": [],
        "started_at": dt.date.today().isoformat(),
        "domains": [],
    }
    body = (
        f"# {topic}\n\n"
        f"## 当前假设\n\n_TODO_\n\n"
        f"## Open Questions\n\n_TODO_\n\n"
        f"## 已读 / 待读\n\n_TODO_\n\n"
        f"## 阶段性结论\n\n_TODO_\n\n"
        f"## Changelog\n\n- {dt.date.today().isoformat()}: 新建 thread\n"
    )
    main_path = folder / "thread.md"
    write_md(main_path, fm, body)
    return main_path


def list_threads(paths: Paths) -> list[dict]:
    out: list[dict] = []
    if not paths.threads.exists():
        return out
    for d in sorted(paths.threads.iterdir()):
        if not d.is_dir():
            continue
        main = d / "thread.md"
        if not main.exists():
            continue
        from .utils.frontmatter_io import read_md
        fm, _ = read_md(main)
        out.append({
            "id": fm.get("id"), "title": fm.get("title"),
            "status": fm.get("status"), "path": str(main.relative_to(paths.root)),
        })
    return out
