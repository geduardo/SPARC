#!/usr/bin/env python3
"""Inspect and open the saved reward curve from a SPARC training run."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import webbrowser


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the training-artifact viewer CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Load a SPARC training summary, print the main metrics, and open the "
            "saved reward-evolution image."
        )
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/servo_control_ppo",
        help=(
            "Training output directory containing "
            "`servo_control_training_summary.json`."
        ),
    )
    parser.add_argument(
        "--summary",
        help=(
            "Optional explicit path to `servo_control_training_summary.json`. "
            "Overrides --output-dir."
        ),
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Print the resolved artifact paths without opening the reward image.",
    )
    return parser


def _resolve_path(path_text: str | pathlib.Path, base_dir: pathlib.Path) -> pathlib.Path:
    """Resolve absolute or repo-relative artifact paths from JSON."""
    path = pathlib.Path(path_text)
    if path.is_absolute():
        return path
    candidate = (base_dir / path).resolve()
    if candidate.exists():
        return candidate
    return (REPO_ROOT / path).resolve()


def _open_path(path: pathlib.Path) -> None:
    """Open a file in the platform's default viewer."""
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    webbrowser.open(path.as_uri())


def main() -> int:
    """CLI entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.summary:
        summary_path = pathlib.Path(args.summary).resolve()
    else:
        summary_path = pathlib.Path(args.output_dir).resolve() / "servo_control_training_summary.json"

    if not summary_path.exists():
        parser.error(f"training summary not found: {summary_path}")

    summary = json.loads(summary_path.read_text())
    reward_curve_path = _resolve_path(summary["reward_curve_path"], summary_path.parent)
    model_path = _resolve_path(summary["model_path"], summary_path.parent)

    checkpoint_paths = [
        _resolve_path(path_text, summary_path.parent)
        for path_text in summary.get("checkpoint_paths", [])
    ]
    latest_checkpoint = checkpoint_paths[-1] if checkpoint_paths else None

    print(f"summary_path: {summary_path}")
    print(f"reward_curve_path: {reward_curve_path}")
    print(f"model_path: {model_path}")
    print(f"interrupted: {summary.get('interrupted')}")
    print(f"episodes_recorded: {summary.get('episodes_recorded')}")
    print(f"initial_mean_reward: {summary.get('initial_mean_reward')}")
    print(f"trained_mean_reward: {summary.get('trained_mean_reward')}")
    print(f"checkpoint_count: {len(checkpoint_paths)}")
    if latest_checkpoint is not None:
        print(f"latest_checkpoint: {latest_checkpoint}")

    if not args.no_open:
        _open_path(reward_curve_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
