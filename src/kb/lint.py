"""Lint: structural checks on the wiki — citations, broken links, stub freshness."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import Paths
from .utils.frontmatter_io import read_md


@dataclass
class LintFinding:
    severity: str   # info | warn | error
    file: Path
    rule: str
    message: str


CITATION_RE = re.compile(r"\[\^src-[a-z0-9\-]+(?:#page-\d+)?\]")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def lint(paths: Paths) -> list[LintFinding]:
    findings: list[LintFinding] = []
    if not paths.wiki.exists():
        return findings

    valid_ids = _known_card_ids(paths)
    for md in paths.wiki.rglob("*.md"):
        if _is_scaffold(md, paths):
            continue
        fm, body = read_md(md)
        findings.extend(_lint_frontmatter(md, fm))
        findings.extend(_lint_citations(md, body, valid_ids, fm))
        findings.extend(_lint_wikilinks(md, body, paths))
        if fm.get("type") == "factor":
            findings.extend(_lint_factor(md))

    findings.extend(_lint_outputs(paths))
    findings.extend(_lint_conflicts(paths))
    findings.extend(_lint_regressions(paths))
    return findings


def _lint_factor(md_path: Path) -> list[LintFinding]:
    from .factors import validate_factor_link
    problems = validate_factor_link(md_path)
    return [
        LintFinding("warn", md_path, "factor.implementation", p)
        for p in problems
    ]


def _lint_conflicts(paths: Paths) -> list[LintFinding]:
    if not paths.conflicts.exists():
        return []
    n = sum(1 for _ in paths.conflicts.open(encoding="utf-8") if _.strip())
    if not n:
        return []
    return [LintFinding(
        "info", paths.conflicts, "concepts.conflicts",
        f"{n} contradiction(s) pending review — read conflicts.jsonl",
    )]


def _lint_regressions(paths: Paths) -> list[LintFinding]:
    if not paths.regressions.exists():
        return []
    rows = [r for r in paths.regressions.read_text(encoding="utf-8").splitlines() if r.strip()]
    if not rows:
        return []
    return [LintFinding(
        "warn", paths.regressions, "eval.regressions",
        f"{len(rows)} regression row(s) accumulated — run `kb eval` and inspect",
    )]


def _known_card_ids(paths: Paths) -> set[str]:
    out: set[str] = set()
    for sub in ("sources", "concepts", "factors", "strategies", "models", "threads"):
        d = paths.wiki / sub
        if not d.exists():
            continue
        for md in d.rglob("*.md"):
            try:
                fm, _ = read_md(md)
            except Exception:
                continue
            sid = fm.get("id")
            if sid:
                out.add(sid)
    return out


_SCAFFOLD_DIRS = {"_dashboard", "_templates", "_attachments", "attachments"}


def _is_scaffold(md: Path, paths: Paths) -> bool:
    try:
        rel = md.relative_to(paths.wiki)
    except ValueError:
        return False
    return any(part in _SCAFFOLD_DIRS or part.startswith(".") for part in rel.parts)


def _lint_frontmatter(path: Path, fm: dict) -> list[LintFinding]:
    out: list[LintFinding] = []
    required = {"id", "type", "title", "status"}
    missing = sorted(required - fm.keys())
    if missing:
        out.append(LintFinding("error", path, "fm.required",
                               f"missing frontmatter fields: {missing}"))
    return out


def _lint_citations(path: Path, body: str, valid_ids: set[str], fm: dict) -> list[LintFinding]:
    out: list[LintFinding] = []
    if fm.get("type") in {"thread", "memo"}:
        # memos are required to cite; threads need 'sources_read'.
        if fm.get("type") == "memo" and not CITATION_RE.search(body):
            out.append(LintFinding("error", path, "citation.required",
                                   "memo has no [^src-...] citations"))
    for m in CITATION_RE.finditer(body):
        token = m.group(0)
        # [^src-id#page-x] → strip [^ ] and any #page-...
        inner = token[2:-1].split("#", 1)[0]
        if inner not in valid_ids:
            out.append(LintFinding("warn", path, "citation.broken",
                                   f"citation to unknown source: {inner}"))
    return out


def _lint_wikilinks(path: Path, body: str, paths: Paths) -> list[LintFinding]:
    out: list[LintFinding] = []
    for m in WIKILINK_RE.finditer(body):
        target = m.group(1).split("|", 1)[0].strip()
        # Resolve target relative to wiki root.
        candidate = paths.wiki / (target if target.endswith(".md") else target + ".md")
        if not candidate.exists():
            out.append(LintFinding("warn", path, "wikilink.broken",
                                   f"broken double-link: {target}"))
    return out


def _lint_outputs(paths: Paths) -> list[LintFinding]:
    out: list[LintFinding] = []
    if not paths.outputs.exists():
        return out
    unassigned = list(paths.outputs.rglob("*.md"))
    if len(unassigned) > 5:
        out.append(LintFinding(
            "info", paths.outputs, "outputs.unassigned",
            f"{len(unassigned)} memo(s) sit in outputs/ without a thread — consider grouping.",
        ))
    return out
