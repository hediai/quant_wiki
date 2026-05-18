"""Factor Cards: create / link to factor_mining implementation + backtest."""
from __future__ import annotations

import datetime as dt
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Paths
from .utils.frontmatter_io import read_md, write_md
from .utils.ids import factor_id

log = logging.getLogger(__name__)


@dataclass
class FactorLink:
    factor_id: str
    card_path: Path
    repo_path: Path
    module: str
    commit: str | None
    backtest_path: str | None
    backtest_metrics: dict[str, Any]


def create_factor_stub(
    name: str,
    version: str | int,
    *,
    paths: Paths,
    domain: str = "选股",
    asset_classes: list[str] | None = None,
) -> Path:
    fid = factor_id(name, version)
    path = paths.factors / f"{fid}.md"
    if path.exists():
        return path
    fm = {
        "id": fid, "type": "factor", "title": f"{name} v{version}",
        "domains": [domain],
        "asset_classes": asset_classes or ["A股"],
        "tags": [name.lower()],
        "status": "active",
        "as_of": dt.date.today().isoformat(),
        "implementation": {
            "repo_path": None, "module": None,
            "commit": None,
            "last_backtest": {"path": None, "sharpe": None, "ic": None},
        },
        "performance_over_time": [],
    }
    body = (
        f"# {name} v{version}\n\n"
        f"## 因子定义\n\n_TODO_\n\n"
        f"## 构造步骤\n\n_TODO_\n\n"
        f"## 评估结果\n\n_TODO_\n\n"
        f"## 适用条件\n\n_TODO_\n\n"
        f"## 相关\n\n- 实现：见 frontmatter `implementation`\n- 概念：_TODO_\n\n"
        f"## Changelog\n\n- {dt.date.today().isoformat()}: 新建 stub\n"
    )
    write_md(path, fm, body)
    return path


def link_factor(
    factor_id_or_name: str,
    *,
    paths: Paths,
    repo_path: Path,
    module: str,
    backtest_path: str | None = None,
    pin_commit: bool = True,
) -> FactorLink:
    """Pin a Factor Card to a concrete implementation in factor_mining.

    - Validates module path exists inside repo_path.
    - Optionally reads HEAD commit so a later git-diff can detect drift.
    - If `backtest_path` is given and exists, reads sharpe/ic from JSON.
    """
    card = _resolve_factor_card(factor_id_or_name, paths)
    fm, body = read_md(card)
    impl = dict(fm.get("implementation") or {})

    repo_path = repo_path.resolve()
    if not repo_path.exists():
        raise FileNotFoundError(f"repo not found: {repo_path}")
    module_path = repo_path / module
    if not module_path.exists():
        raise FileNotFoundError(f"module not found inside repo: {module_path}")

    commit = _git_head(repo_path) if pin_commit else impl.get("commit")

    last_bt = dict(impl.get("last_backtest") or {})
    backtest_metrics: dict[str, Any] = {}
    if backtest_path:
        bt_abs = (repo_path / backtest_path).resolve() if not Path(backtest_path).is_absolute() else Path(backtest_path)
        if bt_abs.exists():
            try:
                data = json.loads(bt_abs.read_text(encoding="utf-8"))
                for k in ("sharpe", "ic", "rank_ic", "annual_return", "max_drawdown"):
                    if k in data:
                        backtest_metrics[k] = data[k]
                last_bt = {"path": str(backtest_path), **backtest_metrics}
            except Exception as exc:
                log.warning("backtest JSON read failed: %s", exc)

    impl.update({
        "repo_path": str(repo_path),
        "module": module,
        "commit": commit,
        "last_backtest": last_bt,
    })
    fm["implementation"] = impl
    fm.setdefault("type", "factor")
    fm["last_reviewed"] = dt.date.today().isoformat()

    today = dt.date.today().isoformat()
    line = f"- {today}: linked {module} @ {commit or 'unpinned'}"
    if backtest_path:
        line += f"; backtest {backtest_path}" + (f" (sharpe={backtest_metrics.get('sharpe')})" if backtest_metrics else "")
    body = _append_changelog(body, line)
    write_md(card, fm, body)

    return FactorLink(
        factor_id=fm.get("id"), card_path=card,
        repo_path=repo_path, module=module, commit=commit,
        backtest_path=backtest_path, backtest_metrics=backtest_metrics,
    )


def validate_factor_link(card: Path) -> list[str]:
    """Return a list of human-readable problems. Empty = healthy."""
    problems: list[str] = []
    fm, _ = read_md(card)
    impl = fm.get("implementation") or {}
    repo = impl.get("repo_path")
    module = impl.get("module")
    if not repo:
        problems.append("implementation.repo_path missing")
        return problems
    if not module:
        problems.append("implementation.module missing")
        return problems
    repo_p = Path(repo)
    if not repo_p.exists():
        problems.append(f"repo_path does not exist: {repo}")
        return problems
    mod_p = repo_p / module
    if not mod_p.exists():
        problems.append(f"module missing inside repo: {module}")
    commit = impl.get("commit")
    if commit and _is_git_repo(repo_p):
        head = _git_head(repo_p)
        if head and head != commit:
            problems.append(f"pinned commit {commit[:10]} drifted from HEAD {head[:10]}")
    last_bt = impl.get("last_backtest") or {}
    bt_path = last_bt.get("path")
    if bt_path:
        bt_abs = (repo_p / bt_path) if not Path(bt_path).is_absolute() else Path(bt_path)
        if not bt_abs.exists():
            problems.append(f"backtest file missing: {bt_path}")
    return problems


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_factor_card(ident: str, paths: Paths) -> Path:
    if not paths.factors.exists():
        raise FileNotFoundError(paths.factors)
    direct = paths.factors / f"{ident}.md"
    if direct.exists():
        return direct
    # try fuzzy by title
    for md in paths.factors.glob("*.md"):
        fm, _ = read_md(md)
        if fm.get("id") == ident or ident in (fm.get("title") or ""):
            return md
    raise FileNotFoundError(f"factor card not found for: {ident}")


def _git_head(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo), check=False, capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except Exception as exc:
        log.debug("git rev-parse failed: %s", exc)
    return None


def _is_git_repo(repo: Path) -> bool:
    return (repo / ".git").exists()


def _append_changelog(body: str, line: str) -> str:
    from .concepts import _upsert_section  # type: ignore
    return _upsert_section(body, "## Changelog", line)
