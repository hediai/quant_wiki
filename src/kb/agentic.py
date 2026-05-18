"""Semi-autonomous factor research sandbox.

This module does not run a trading agent. It creates the guardrails and handoff
artifacts needed for a controlled multi-agent workflow:

Research -> FactorSpec -> Backtest -> Critic -> Gate -> Wiki writeback.

Only experiment artifacts are written by default. Formal wiki/factor promotion is
left to an explicit gate decision so the long-lived knowledge base is not polluted
by unverified autonomous output.
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import Paths
from .utils.ids import experiment_id


ROLES = [
    "orchestrator",
    "research",
    "factor",
    "backtest",
    "critic",
    "wiki-steward",
]


DEFAULT_GATE = {
    "min_abs_ic_t": 3.0,
    "min_long_short_sharpe": 1.0,
    "max_turnover": 5.0,
    "require_oos_window": True,
    "require_cost_model": True,
    "require_critic_clear": True,
}


AGENT_SPECS: dict[str, str] = {
    "orchestrator.md": """# Orchestrator Agent

## Mission
Coordinate the semi-autonomous factor research loop. Create tasks, enforce the
write policy, and decide whether an experiment remains draft, hold, retire, or
promote_candidate.

## Allowed Writes
- `experiments/<experiment_id>/`
- `inbox/factors/`

## Forbidden Writes
- `raw/`
- `converted/`
- `wiki/factors/` unless the gate already marked `decision: promote_candidate`
- production trading or live order files

## Inputs
- `experiment.yaml`
- `factor_spec.yaml`
- `backtest_result.json`
- `critic_report.yaml`

## Output
Update `experiment.yaml` and `decision.yaml`. Do not edit formal wiki pages
unless explicitly asked after a passing gate.
""",
    "research.md": """# Research Agent

## Mission
Use `kb search`, Source Cards, Concepts, and Thread memos to propose economically
interpretable factor hypotheses.

## Guardrails
- Every factual claim must cite a Source Card or memo.
- Do not invent empirical performance.
- Prefer narrow hypotheses that can be expressed in the factor grammar.

## Output Schema
Write the hypothesis section in `experiment.yaml`:

```yaml
hypothesis:
  statement: ""
  rationale: ""
  citations: []
  expected_direction: long_high | short_high | unknown
```
""",
    "factor.md": """# Factor Agent

## Mission
Translate an approved hypothesis into a constrained `FactorSpec`. Do not write
free-form backtest code unless the expression cannot be represented in the DSL.

## Guardrails
- Use only declared inputs and operators.
- No future returns, forward windows, post-date transforms, or full-sample stats.
- Keep expression depth small enough for audit.

## Output
Write `factor_spec.yaml` only.
""",
    "backtest.md": """# Backtest Agent

## Mission
Execute the fixed backtest protocol for a `FactorSpec`.

## Guardrails
- Do not change gate thresholds to fit a result.
- Use time-based IS/OOS separation.
- Report gross and net metrics when a cost model is available.
- Persist artifacts under the experiment folder.

## Output
Write `backtest_result.json`.
""",
    "critic.md": """# Critic Agent

## Mission
Reject fragile or contaminated experiments. The critic is independent from the
generation agents and should default to hold/retire when evidence is incomplete.

## Checks
- no look-ahead or target leakage
- OOS isolation
- transaction cost and turnover feasibility
- duplicate or highly correlated existing factor
- citation support for economic rationale
- suspicious parameter search or one-off rule tuning

## Output
Write `critic_report.yaml` with `blockers`, `warnings`, and check statuses.
""",
    "wiki-steward.md": """# Wiki Steward Agent

## Mission
Write durable research memory after the gate decision.

## Policy
- `retire`: summarize failure under the experiment folder only.
- `hold`: leave action items in `inbox/factors/`.
- `promote_candidate`: draft a Factor Card or memo with citations and backtest
  provenance, then wait for explicit approval before formal promotion.

## Output
Draft markdown in `inbox/factors/` or a thread memo. Do not silently rewrite
existing Concept or Factor definitions.
""",
}


@dataclass
class InitResult:
    agent_paths: list[Path]
    directories: list[Path]


@dataclass
class ExperimentResult:
    experiment_id: str
    experiment_dir: Path
    record_path: Path


@dataclass
class GateResult:
    experiment_id: str
    decision: str
    reasons: list[str]
    decision_path: Path


def init_agentic(paths: Paths, *, overwrite: bool = False) -> InitResult:
    """Create the semi-autonomous sandbox layout and role cards."""
    dirs = [
        paths.experiments,
        paths.root / "inbox" / "factors",
        paths.agents,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for name, content in AGENT_SPECS.items():
        p = paths.agents / name
        if overwrite or not p.exists():
            p.write_text(content.rstrip() + "\n", encoding="utf-8")
        written.append(p)

    manifest = paths.agents / "agent-manifest.yaml"
    if overwrite or not manifest.exists():
        manifest.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "mode": "semi_autonomous",
                    "roles": ROLES,
                    "write_policy": {
                        "allowed": ["experiments/<experiment_id>/", "inbox/factors/"],
                        "protected": ["raw/", "converted/", "wiki/factors/"],
                    },
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    written.append(manifest)
    return InitResult(agent_paths=written, directories=dirs)


def new_experiment(
    topic: str,
    *,
    paths: Paths,
    domain: str = "选股",
    thread: str | None = None,
    hypothesis: str = "",
    citations: list[str] | None = None,
) -> ExperimentResult:
    """Create an experiment folder with all handoff artifacts."""
    init_agentic(paths)
    now = dt.datetime.now(dt.timezone.utc)
    eid = experiment_id(topic, when=now, rand_hex=secrets.token_hex(2))
    exp_dir = paths.experiments / eid
    exp_dir.mkdir(parents=True, exist_ok=False)

    record = {
        "schema_version": 1,
        "id": eid,
        "type": "agentic_experiment",
        "status": "draft",
        "decision": "hold",
        "autonomy": "semi",
        "topic": topic,
        "domain": domain,
        "thread": thread,
        "created_at": now.isoformat(timespec="seconds"),
        "updated_at": now.isoformat(timespec="seconds"),
        "roles": ROLES,
        "write_policy": {
            "allowed": [f"experiments/{eid}/", "inbox/factors/"],
            "protected": ["raw/", "converted/", "wiki/factors/"],
        },
        "hypothesis": {
            "statement": hypothesis,
            "rationale": "",
            "citations": citations or [],
            "expected_direction": "unknown",
        },
        "paths": {
            "factor_spec": "factor_spec.yaml",
            "backtest_result": "backtest_result.json",
            "critic_report": "critic_report.yaml",
            "decision": "decision.yaml",
        },
        "gate": dict(DEFAULT_GATE),
    }
    record_path = exp_dir / "experiment.yaml"
    _write_yaml(record_path, record)
    _write_yaml(exp_dir / "factor_spec.yaml", _factor_spec_template(topic, hypothesis))
    (exp_dir / "backtest_result.json").write_text(
        json.dumps(_backtest_template(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_yaml(exp_dir / "critic_report.yaml", _critic_template())
    (exp_dir / "README.md").write_text(_experiment_readme(eid, topic), encoding="utf-8")

    return ExperimentResult(experiment_id=eid, experiment_dir=exp_dir, record_path=record_path)


def list_experiments(paths: Paths) -> list[dict[str, Any]]:
    if not paths.experiments.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(paths.experiments.glob("exp-*/experiment.yaml")):
        row = _read_yaml(p)
        out.append({
            "id": row.get("id"),
            "topic": row.get("topic"),
            "status": row.get("status"),
            "decision": row.get("decision"),
            "path": str(p.parent.relative_to(paths.root)),
        })
    return out


def gate_experiment(experiment: str, *, paths: Paths) -> GateResult:
    """Apply the fixed promotion gate to one experiment.

    The gate is deliberately conservative:
    missing data -> hold, failed thresholds -> retire, all clear -> promote_candidate.
    """
    exp_dir = _resolve_experiment_dir(experiment, paths)
    record_path = exp_dir / "experiment.yaml"
    record = _read_yaml(record_path)
    gate = {**DEFAULT_GATE, **(record.get("gate") or {})}

    backtest = _read_json(exp_dir / (record.get("paths", {}).get("backtest_result") or "backtest_result.json"))
    critic = _read_yaml(exp_dir / (record.get("paths", {}).get("critic_report") or "critic_report.yaml"))
    metrics = backtest.get("metrics") or {}
    window = backtest.get("data_window") or {}

    reasons: list[str] = []
    hard_fail = False

    blockers = critic.get("blockers") or []
    if gate["require_critic_clear"] and blockers:
        hard_fail = True
        reasons.append(f"critic blockers: {len(blockers)}")

    if gate["require_oos_window"] and not (window.get("oos_start") and window.get("oos_end")):
        reasons.append("missing OOS window")

    if gate["require_cost_model"] and metrics.get("cost_bps_one_way") is None and metrics.get("net_ann_return") is None:
        reasons.append("missing transaction-cost result")

    ic_t = _num(metrics.get("ic_t") if metrics.get("ic_t") is not None else metrics.get("rank_ic_t"))
    if ic_t is None:
        reasons.append("missing IC t-stat")
    elif abs(ic_t) < float(gate["min_abs_ic_t"]):
        hard_fail = True
        reasons.append(f"IC t-stat {ic_t:.3f} below {gate['min_abs_ic_t']}")

    sharpe = _num(metrics.get("long_short_sharpe"))
    if sharpe is None:
        reasons.append("missing long-short Sharpe")
    elif sharpe < float(gate["min_long_short_sharpe"]):
        hard_fail = True
        reasons.append(f"long-short Sharpe {sharpe:.3f} below {gate['min_long_short_sharpe']}")

    turnover = _num(metrics.get("turnover"))
    if turnover is not None and turnover > float(gate["max_turnover"]):
        hard_fail = True
        reasons.append(f"turnover {turnover:.3f} above {gate['max_turnover']}")

    if hard_fail:
        decision = "retire"
        status = "reviewed"
    elif reasons:
        decision = "hold"
        status = "draft"
    else:
        decision = "promote_candidate"
        status = "reviewed"
        reasons.append("all gate checks passed")

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    record["decision"] = decision
    record["status"] = status
    record["updated_at"] = now
    _write_yaml(record_path, record)

    decision_payload = {
        "schema_version": 1,
        "experiment_id": record.get("id") or exp_dir.name,
        "decision": decision,
        "reasons": reasons,
        "evaluated_at": now,
        "gate": gate,
    }
    decision_path = exp_dir / "decision.yaml"
    _write_yaml(decision_path, decision_payload)
    return GateResult(
        experiment_id=decision_payload["experiment_id"],
        decision=decision,
        reasons=reasons,
        decision_path=decision_path,
    )


def _resolve_experiment_dir(experiment: str, paths: Paths) -> Path:
    direct = paths.experiments / experiment
    if (direct / "experiment.yaml").exists():
        return direct
    matches = list(paths.experiments.glob(f"*{experiment}*/experiment.yaml"))
    if len(matches) == 1:
        return matches[0].parent
    if not matches:
        raise FileNotFoundError(f"experiment not found: {experiment}")
    raise ValueError(f"experiment id is ambiguous: {experiment}")


def _factor_spec_template(topic: str, hypothesis: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "draft",
        "name": None,
        "topic": topic,
        "hypothesis": hypothesis,
        "rationale": None,
        "citations": [],
        "inputs": [],
        "operators": [],
        "expression": None,
        "direction": "unknown",
        "horizon": "1d",
        "lookback_windows": [],
        "constraints": {
            "no_lookahead": True,
            "cross_sectional_only_for_same_date": True,
            "max_expression_depth": 4,
        },
    }


def _backtest_template() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "pending",
        "data_window": {
            "is_start": None,
            "is_end": None,
            "oos_start": None,
            "oos_end": None,
        },
        "metrics": {
            "rank_ic_mean": None,
            "ic_t": None,
            "long_short_sharpe": None,
            "ann_return": None,
            "max_drawdown": None,
            "turnover": None,
            "cost_bps_one_way": None,
            "net_ann_return": None,
        },
        "artifacts": [],
        "notes": "",
    }


def _critic_template() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "pending",
        "blockers": [],
        "warnings": [],
        "checks": {
            "no_lookahead": "unknown",
            "oos_isolated": "unknown",
            "cost_model": "unknown",
            "duplicate_factor": "unknown",
            "citation_support": "unknown",
        },
    }


def _experiment_readme(eid: str, topic: str) -> str:
    return f"""# {eid}

Topic: {topic}

Semi-autonomous workflow:

1. Research Agent fills `experiment.yaml` hypothesis fields with citations.
2. Factor Agent writes `factor_spec.yaml`.
3. Backtest Agent writes `backtest_result.json` under the fixed protocol.
4. Critic Agent writes `critic_report.yaml`.
5. Orchestrator runs `kb agentic gate {eid}`.
6. Wiki Steward writes only to `inbox/factors/` unless the gate returns `promote_candidate`.
"""


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
