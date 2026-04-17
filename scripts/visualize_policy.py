#!/usr/bin/env python3
"""Roll out a saved SB3 policy and export a dashboard-compatible .npz recording."""

from __future__ import annotations

import argparse
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
        help="Use the modular simulator path instead of the compiled path.",
    )
    parser.add_argument(
        "--mechanics-control-mode",
        default="position",
        choices=["position", "velocity"],
        help="Mechanics control mode passed to the env (default: position).",
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


def build_config(args: argparse.Namespace) -> EnvironmentConfig:
    """Build an EnvironmentConfig from CLI overrides."""
    kwargs: dict[str, object] = {}
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


def main() -> int:
    """CLI entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args()

    summary = rollout_servo_control_policy_to_npz(
        model_path=args.model,
        output_path=args.output,
        max_episode_steps=args.max_episode_steps,
        seed=args.seed,
        use_compiled=not args.use_modular,
        mechanics_control_mode=args.mechanics_control_mode,
        config=build_config(args),
        deterministic=not args.stochastic,
    )

    for key, value in summary.items():
        print(f"{key}: {value}")

    print()
    print("Next:")
    print("1. Open visualization/dashboard.html in the static dashboard server.")
    print("2. Click 'Load Data'.")
    print(f"3. Select: {summary['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
