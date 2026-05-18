"""Semi-autonomous factor experiment sandbox."""
from __future__ import annotations

import json

import yaml

from kb.agentic import gate_experiment, init_agentic, list_experiments, new_experiment


def test_agentic_init_writes_roles_and_dirs(kb_root):
    result = init_agentic(kb_root)
    assert kb_root.experiments.exists()
    assert (kb_root.root / "inbox" / "factors").exists()
    assert kb_root.agents.exists()
    names = {p.name for p in result.agent_paths}
    assert "orchestrator.md" in names
    assert "critic.md" in names
    assert "agent-manifest.yaml" in names


def test_new_experiment_creates_handoff_artifacts(kb_root):
    result = new_experiment(
        "高换手动量衰减",
        paths=kb_root,
        domain="选股",
        thread="thread-demo",
        hypothesis="高换手股票上动量信号可能反转",
        citations=["[^src-demo#page-1]"],
    )
    assert result.record_path.exists()
    assert (result.experiment_dir / "factor_spec.yaml").exists()
    assert (result.experiment_dir / "backtest_result.json").exists()
    assert (result.experiment_dir / "critic_report.yaml").exists()

    record = yaml.safe_load(result.record_path.read_text(encoding="utf-8"))
    assert record["autonomy"] == "semi"
    assert record["decision"] == "hold"
    assert record["hypothesis"]["citations"] == ["[^src-demo#page-1]"]
    assert list_experiments(kb_root)[0]["id"] == result.experiment_id


def test_gate_holds_when_required_outputs_are_missing(kb_root):
    result = new_experiment("缺少回测结果", paths=kb_root)
    gate = gate_experiment(result.experiment_id, paths=kb_root)
    assert gate.decision == "hold"
    assert any("missing" in reason for reason in gate.reasons)


def test_gate_promotes_candidate_when_metrics_pass(kb_root):
    result = new_experiment("有效候选因子", paths=kb_root)
    backtest_path = result.experiment_dir / "backtest_result.json"
    backtest = json.loads(backtest_path.read_text(encoding="utf-8"))
    backtest["data_window"] = {
        "is_start": "2004-01-01",
        "is_end": "2020-12-31",
        "oos_start": "2021-01-01",
        "oos_end": "2024-12-31",
    }
    backtest["metrics"].update({
        "ic_t": 3.5,
        "long_short_sharpe": 1.4,
        "turnover": 1.2,
        "cost_bps_one_way": 3,
        "net_ann_return": 0.12,
    })
    backtest_path.write_text(json.dumps(backtest, ensure_ascii=False, indent=2), encoding="utf-8")

    critic_path = result.experiment_dir / "critic_report.yaml"
    critic = yaml.safe_load(critic_path.read_text(encoding="utf-8"))
    critic["status"] = "passed"
    critic["checks"] = {k: "passed" for k in critic["checks"]}
    critic_path.write_text(yaml.safe_dump(critic, allow_unicode=True, sort_keys=False), encoding="utf-8")

    gate = gate_experiment(result.experiment_id, paths=kb_root)
    assert gate.decision == "promote_candidate"
    decision = yaml.safe_load(gate.decision_path.read_text(encoding="utf-8"))
    assert decision["decision"] == "promote_candidate"


def test_gate_retires_failed_metrics(kb_root):
    result = new_experiment("弱因子", paths=kb_root)
    backtest_path = result.experiment_dir / "backtest_result.json"
    backtest = json.loads(backtest_path.read_text(encoding="utf-8"))
    backtest["data_window"] = {
        "is_start": "2004-01-01",
        "is_end": "2020-12-31",
        "oos_start": "2021-01-01",
        "oos_end": "2024-12-31",
    }
    backtest["metrics"].update({
        "ic_t": 0.5,
        "long_short_sharpe": 0.2,
        "turnover": 1.0,
        "cost_bps_one_way": 3,
    })
    backtest_path.write_text(json.dumps(backtest, ensure_ascii=False, indent=2), encoding="utf-8")

    gate = gate_experiment(result.experiment_id, paths=kb_root)
    assert gate.decision == "retire"
    assert any("below" in reason for reason in gate.reasons)
