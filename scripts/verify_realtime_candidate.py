#!/usr/bin/env python
"""Run the frozen realtime preset as a candidate verification against the baseline."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import profile_realtime_baseline as baseline_preset


REPO_ROOT = baseline_preset.REPO_ROOT
PROFILE_SCRIPT = baseline_preset.PROFILE_SCRIPT
DASHBOARD_SCRIPT = baseline_preset.DASHBOARD_SCRIPT
DEFAULT_BASELINE = baseline_preset.CANONICAL_BASELINE_PATH


def default_output_path(engine: str = "modular") -> pathlib.Path:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    suffix = "" if engine == "modular" else f"_{engine}"
    return REPO_ROOT / "outputs" / "profiling" / f"perf_candidate{suffix}_{timestamp}.json"


def format_path(path: pathlib.Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    except Exception:
        return str(path)


def scenario_label(scenario: Dict[str, Any]) -> str:
    return (
        f"{float(scenario.get('segment_len_mm', 0.0)):.2f} mm / "
        f"{int(scenario.get('n_segments', 0))} seg"
    )


def scenario_key(scenario: Dict[str, Any]) -> str:
    return (
        f"{float(scenario.get('segment_len_mm', 0.0)):.6f}|"
        f"{int(scenario.get('n_segments', 0))}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen conservative preset and compare it to the canonical baseline."
    )
    parser.add_argument(
        "--engine",
        choices=["modular", "compiled"],
        default="modular",
        help="Execution engine to verify against the baseline (default: modular).",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        default=str(DEFAULT_BASELINE),
        help="Baseline JSON to compare against. Defaults to the canonical conservative baseline.",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Optional JSON output path. Defaults to outputs/profiling/perf_candidate_<timestamp>.json.",
    )
    parser.add_argument(
        "--skip-dashboard",
        action="store_true",
        help="Skip regenerating the standalone performance dashboard after verification.",
    )
    parser.add_argument(
        "--allow-fidelity-failure",
        action="store_true",
        help="Do not exit with code 1 when the fidelity comparison fails.",
    )
    return parser.parse_args()


def build_profile_command(
    output_path: pathlib.Path, baseline_path: pathlib.Path, engine: str = "modular"
) -> List[str]:
    return [
        sys.executable,
        str(PROFILE_SCRIPT),
        *baseline_preset.BASELINE_ARGS,
        "--engine",
        engine,
        "--compare-to",
        str(baseline_path),
        "--json-out",
        str(output_path),
    ]


def load_json(path: pathlib.Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_verification_summary(
    baseline_report: Dict[str, Any],
    candidate_report: Dict[str, Any],
    baseline_path: pathlib.Path,
) -> Dict[str, Any]:
    baseline_scenarios = {
        scenario_key(scenario): scenario for scenario in baseline_report.get("scenarios", [])
    }
    comparison = candidate_report.get("fidelity_comparison") or {}
    comparison_scenarios = {
        str(entry.get("scenario")): entry for entry in comparison.get("scenarios", [])
    }

    scenarios = []
    for candidate_scenario in candidate_report.get("scenarios", []):
        key = scenario_key(candidate_scenario)
        baseline_scenario = baseline_scenarios.get(key)
        if baseline_scenario is None:
            continue

        baseline_steps = float(
            baseline_scenario.get("benchmark", {}).get("median_steps_per_second", 0.0)
        )
        candidate_steps = float(
            candidate_scenario.get("benchmark", {}).get("median_steps_per_second", 0.0)
        )
        delta_steps = candidate_steps - baseline_steps
        delta_pct = (delta_steps / baseline_steps * 100.0) if baseline_steps > 0 else None
        fidelity = comparison_scenarios.get(key)
        scenarios.append(
            {
                "scenario": scenario_label(candidate_scenario),
                "key": key,
                "baseline_steps_per_second": baseline_steps,
                "candidate_steps_per_second": candidate_steps,
                "delta_steps_per_second": delta_steps,
                "delta_pct": delta_pct,
                "fidelity_passed": None if fidelity is None else bool(fidelity.get("passed")),
                "termination_reason": candidate_scenario.get("fidelity_signature", {}).get(
                    "termination_reason"
                ),
            }
        )

    return {
        "baseline_report_path": format_path(baseline_path),
        "baseline_report_name": pathlib.Path(baseline_path).stem,
        "fidelity_passed": bool(comparison.get("passed", False)),
        "scenarios": scenarios,
    }


def write_candidate_report(output_path: pathlib.Path, report: Dict[str, Any]) -> None:
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def print_summary(summary: Dict[str, Any]) -> None:
    print()
    print(
        "Verification summary: "
        + ("PASS" if summary.get("fidelity_passed") else "FAIL")
        + f" vs {summary.get('baseline_report_name', 'baseline')}"
    )
    for scenario in summary.get("scenarios", []):
        delta_pct = scenario.get("delta_pct")
        delta_pct_text = "n/a" if delta_pct is None else f"{delta_pct:+.2f}%"
        print(
            f"  {scenario['scenario']}: "
            f"{scenario['baseline_steps_per_second']:.2f} -> "
            f"{scenario['candidate_steps_per_second']:.2f} steps/s "
            f"({delta_pct_text}) "
            f"fidelity={'PASS' if scenario.get('fidelity_passed') else 'FAIL'}"
        )


def main() -> None:
    args = parse_args()
    baseline_path = pathlib.Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = REPO_ROOT / baseline_path
    if not baseline_path.exists():
        raise SystemExit(f"Baseline report not found: {baseline_path}")

    output_path = pathlib.Path(args.output) if args.output else default_output_path(args.engine)
    if not output_path.is_absolute():
        output_path = REPO_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Verifying candidate against {format_path(baseline_path)}")
    subprocess.run(
        build_profile_command(output_path, baseline_path, args.engine),
        cwd=REPO_ROOT,
        check=True,
    )

    baseline_report = load_json(baseline_path)
    candidate_report = load_json(output_path)
    summary = build_verification_summary(baseline_report, candidate_report, baseline_path)
    candidate_report["verification_summary"] = summary
    candidate_report.setdefault("metadata", {})["workflow"] = "candidate_verification"
    candidate_report.setdefault("metadata", {})["engine"] = args.engine
    write_candidate_report(output_path, candidate_report)
    print_summary(summary)

    if not args.skip_dashboard:
        subprocess.run([sys.executable, str(DASHBOARD_SCRIPT)], cwd=REPO_ROOT, check=True)

    print(f"Candidate report written to {output_path}")
    if (not summary.get("fidelity_passed")) and (not args.allow_fidelity_failure):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
