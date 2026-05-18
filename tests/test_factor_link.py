"""Phase 3: factor card linkage to a sibling factor_mining repo."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kb.factors import create_factor_stub, link_factor, validate_factor_link
from kb.lint import lint


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "factor_mining"
    (repo / "factors" / "momentum").mkdir(parents=True)
    (repo / "outputs" / "2026-04").mkdir(parents=True)
    (repo / "factors" / "momentum" / "v3.py").write_text(
        "def momentum_v3(df):\n    return df\n", encoding="utf-8",
    )
    (repo / "outputs" / "2026-04" / "momentum_v3.json").write_text(
        '{"sharpe": 1.42, "ic": 0.045, "turnover": 0.6}', encoding="utf-8",
    )
    # init git so link can pin a commit
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def test_factor_link_pins_commit_and_metrics(kb_root, fake_repo):
    create_factor_stub("momentum", "3", paths=kb_root, domain="选股")
    link = link_factor(
        "factor-momentum-v3",
        paths=kb_root,
        repo_path=fake_repo,
        module="factors/momentum/v3.py",
        backtest_path="outputs/2026-04/momentum_v3.json",
    )
    assert link.commit and len(link.commit) >= 7
    assert link.backtest_metrics["sharpe"] == 1.42
    body = link.card_path.read_text(encoding="utf-8")
    assert "factor_mining" in body or "factors/momentum/v3.py" in body
    problems = validate_factor_link(link.card_path)
    assert not problems, problems


def test_factor_validate_detects_missing_module(kb_root, fake_repo):
    create_factor_stub("orphan", "1", paths=kb_root)
    link_factor(
        "factor-orphan-v1", paths=kb_root,
        repo_path=fake_repo, module="factors/momentum/v3.py",
    )
    # rename module → linkage should now fail
    (fake_repo / "factors" / "momentum" / "v3.py").rename(
        fake_repo / "factors" / "momentum" / "v3_renamed.py"
    )
    card = kb_root.factors / "factor-orphan-v1.md"
    problems = validate_factor_link(card)
    assert problems
    assert any("module" in p.lower() for p in problems)


def test_lint_picks_up_factor_drift(kb_root, fake_repo):
    create_factor_stub("momentum", "3", paths=kb_root)
    link_factor(
        "factor-momentum-v3", paths=kb_root,
        repo_path=fake_repo, module="factors/momentum/v3.py",
    )
    (fake_repo / "factors" / "momentum" / "v3.py").unlink()
    findings = lint(kb_root)
    msgs = [f.message for f in findings]
    assert any("factor" in m.lower() and ("missing" in m.lower() or "module" in m.lower())
               for m in msgs), msgs
