#!/usr/bin/env python3
"""Roll out a saved SB3 policy and export a dashboard-compatible .npz recording."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wedm import EnvironmentConfig
from wedm.rl.policy_rollout import rollout_servo_control_policy_to_npz


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the policy-visualization CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Load a saved SB3 servo-control policy, run one offline rollout, "
            "and export a standard SPARC .npz pack for the recording dashboard."
        )
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Path to the saved SB3 model (.zip).",
    )
    parser.add_argument(
        "--output",
        default="artifacts/policy_rollout/policy_rollout.npz",
        help="Output path for the dashboard-compatible .npz recording.",
    )
    parser.add_argument(
        "--summary",
        help=(
            "Optional training summary JSON to reuse saved env settings. If omitted, "
            "the script looks for `servo_control_training_summary.json` next to --model."
        ),
    )
    parser.add_argument(
        "--max-episode-steps",
        type=int,
        default=3_000,
        help=(
            "Maximum number of public servo-control steps to record "
            "(default: 3000, which is 3 s at 1000 us/control-step)."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=123,
        help="Rollout seed (default: 123).",
    )
    parser.add_argument(
        "--use-modular",
        action="store_true",
        default=None,
        help="Use the modular simulator path instead of the compiled path.",
    )
    parser.add_argument(
        "--mechanics-control-mode",
        default=None,
        choices=["position", "velocity"],
        help="Mechanics control mode passed to the env.",
    )
    parser.add_argument(
        "--stochastic",
        action="store_true",
        help="Use stochastic policy sampling instead of deterministic inference.",
    )
    parser.add_argument(
        "--workpiece-height",
        type=float,
        help="Override workpiece height [mm].",
    )
    parser.add_argument(
        "--wire-diameter",
        type=float,
        help="Override wire diameter [mm].",
    )
    parser.add_argument(
        "--wire-material",
        type=str,
        help="Override wire material.",
    )
    parser.add_argument(
        "--servo-interval",
        type=int,
        help="Override control interval [us].",
    )
    parser.add_argument(
        "--initial-gap",
        type=float,
        help="Override initial gap [um].",
    )
    parser.add_argument(
        "--target-cutting-distance",
        type=float,
        help="Override target cutting distance [um].",
    )
    return parser


def load_summary(summary_path: pathlib.Path | None) -> dict[str, object] | None:
    """Load a training summary JSON if one is available."""
    if summary_path is None:
        return None
    return json.loads(summary_path.read_text())


def resolve_summary_path(
    args: argparse.Namespace,
    model_path: pathlib.Path,
) -> pathlib.Path | None:
    """Find the training summary used to configure a saved policy rollout."""
    if args.summary:
        return pathlib.Path(args.summary).resolve()

    candidate = model_path.with_name("servo_control_training_summary.json")
    if candidate.exists():
        return candidate
    return None


def build_config(
    args: argparse.Namespace,
    summary: dict[str, object] | None,
) -> EnvironmentConfig:
    """Build an EnvironmentConfig from summary defaults and CLI overrides."""
    kwargs = {}
    if summary is not None and isinstance(summary.get("environment_config"), dict):
        kwargs.update(summary["environment_config"])
    if args.workpiece_height is not None:
        kwargs["workpiece_height"] = args.workpiece_height
    if args.wire_diameter is not None:
        kwargs["wire_diameter"] = args.wire_diameter
    if args.wire_material is not None:
        kwargs["wire_material"] = args.wire_material
    if args.servo_interval is not None:
        kwargs["servo_interval"] = args.servo_interval
    if args.initial_gap is not None:
        kwargs["initial_gap"] = args.initial_gap
    if args.target_cutting_distance is not None:
        kwargs["target_cutting_distance"] = args.target_cutting_distance
    return EnvironmentConfig(**kwargs)


def resolve_mechanics_control_mode(
    args: argparse.Namespace,
    summary: dict[str, object] | None,
) -> str:
    """Choose the rollout mechanics mode from CLI overrides or saved metadata."""
    if args.mechanics_control_mode is not None:
        return args.mechanics_control_mode
    if summary is not None and isinstance(summary.get("mechanics_control_mode"), str):
        return summary["mechanics_control_mode"]
    return "position"


def resolve_use_compiled(
    args: argparse.Namespace,
    summary: dict[str, object] | None,
) -> bool:
    """Choose the simulator path from CLI overrides or saved metadata."""
    if args.use_modular is not None:
        return not args.use_modular
    if summary is not None and "use_compiled" in summary:
        return bool(summary["use_compiled"])
    return True


def main() -> int:
    """CLI entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args()
    model_path = pathlib.Path(args.model).resolve()
    summary_path = resolve_summary_path(args, model_path)
    training_summary = load_summary(summary_path)

    rollout_summary = rollout_servo_control_policy_to_npz(
        model_path=model_path,
        output_path=args.output,
        max_episode_steps=args.max_episode_steps,
        seed=args.seed,
        use_compiled=resolve_use_compiled(args, training_summary),
        mechanics_control_mode=resolve_mechanics_control_mode(args, training_summary),
        config=build_config(args, training_summary),
        deterministic=not args.stochastic,
    )

    for key, value in rollout_summary.items():
        print(f"{key}: {value}")

    print()
    print("Next:")
    print("1. Open visualization/dashboard.html in the static dashboard server.")
    print("2. Click 'Load Data'.")
    print(f"3. Select: {rollout_summary['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
