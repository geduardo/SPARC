from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_verify_candidate_command_uses_frozen_preset_and_baseline(tmp_path: Path) -> None:
    module = load_module(
        REPO_ROOT / "scripts" / "verify_realtime_candidate.py",
        "verify_realtime_candidate",
    )
    output_path = tmp_path / "candidate.json"
    baseline_path = tmp_path / "baseline.json"

    command = module.build_profile_command(output_path, baseline_path)

    assert command[0].endswith("python.exe") or command[0].endswith("python")
    assert str(REPO_ROOT / "scripts" / "profile_simulation.py") in command
    assert "--compare-to" in command
    assert command[command.index("--compare-to") + 1] == str(baseline_path)
    assert "--current-mode" in command
    assert command[command.index("--current-mode") + 1] == "1"
    assert "--json-out" in command
    assert command[-1] == str(output_path)


def test_build_verification_summary_reports_throughput_deltas() -> None:
    module = load_module(
        REPO_ROOT / "scripts" / "verify_realtime_candidate.py",
        "verify_realtime_candidate_summary",
    )
    baseline_report = {
        "scenarios": [
            {
                "segment_len_mm": 0.2,
                "n_segments": 400,
                "benchmark": {"median_steps_per_second": 38000.0},
            }
        ]
    }
    candidate_report = {
        "scenarios": [
            {
                "segment_len_mm": 0.2,
                "n_segments": 400,
                "benchmark": {"median_steps_per_second": 40000.0},
                "fidelity_signature": {"termination_reason": "completed"},
            }
        ],
        "fidelity_comparison": {
            "passed": True,
            "scenarios": [{"scenario": "0.200000|400", "passed": True}],
        },
    }

    summary = module.build_verification_summary(
        baseline_report,
        candidate_report,
        REPO_ROOT / "outputs" / "profiling" / "baseline.json",
    )

    assert summary["fidelity_passed"] is True
    assert summary["baseline_report_name"] == "baseline"
    assert len(summary["scenarios"]) == 1
    assert summary["scenarios"][0]["scenario"] == "0.20 mm / 400 seg"
    assert summary["scenarios"][0]["delta_steps_per_second"] == 2000.0
    assert abs(summary["scenarios"][0]["delta_pct"] - 5.2631578947368425) < 1e-12
