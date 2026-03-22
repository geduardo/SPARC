#!/usr/bin/env python
"""Run the conservative realtime baseline preset and refresh the perf dashboard."""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time
from typing import List


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE_SCRIPT = REPO_ROOT / "scripts" / "profile_simulation.py"
DASHBOARD_SCRIPT = REPO_ROOT / "scripts" / "build_perf_dashboard.py"
CANONICAL_BASELINE_PATH = REPO_ROOT / "outputs" / "profiling" / "realtime_baseline_20260322_i1.json"

BASELINE_ARGS = [
    "--segment-len",
    "0.2",
    "--segment-len",
    "0.05",
    "--steps",
    "200000",
    "--warmup",
    "5000",
    "--repeats",
    "2",
    "--initial-gap",
    "12",
    "--servo-interval",
    "1",
    "--workpiece-height",
    "20",
    "--servo",
    "0.25",
    "--target-voltage",
    "90",
    "--current-mode",
    "1",
    "--on-time",
    "3",
    "--off-time",
    "20",
    "--hotspots",
    "both",
]


def default_output_path() -> pathlib.Path:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "outputs" / "profiling" / f"realtime_baseline_{timestamp}.json"


def build_profile_command(output_path: pathlib.Path) -> List[str]:
    return [
        sys.executable,
        str(PROFILE_SCRIPT),
        *BASELINE_ARGS,
        "--json-out",
        str(output_path),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the conservative realtime baseline preset for this PC."
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Optional JSON output path. Defaults to outputs/profiling/realtime_baseline_<timestamp>.json.",
    )
    parser.add_argument(
        "--skip-dashboard",
        action="store_true",
        help="Skip regenerating the standalone performance dashboard after the profile run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = pathlib.Path(args.output) if args.output else default_output_path()
    if not output_path.is_absolute():
        output_path = REPO_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = build_profile_command(output_path)
    print("Running conservative realtime baseline preset.")
    subprocess.run(command, cwd=REPO_ROOT, check=True)

    if not args.skip_dashboard:
        subprocess.run(
            [sys.executable, str(DASHBOARD_SCRIPT)],
            cwd=REPO_ROOT,
            check=True,
        )

    print(f"Baseline report written to {output_path}")


if __name__ == "__main__":
    main()
