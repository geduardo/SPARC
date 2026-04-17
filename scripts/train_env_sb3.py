#!/usr/bin/env python3
"""Train a small SB3 baseline on a SPARC training env and plot reward evolution."""

from __future__ import annotations

import argparse
import pathlib
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wedm import EnvironmentConfig
from wedm.rl.sb3_training import train_servo_control_ppo


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the SB3 training CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Train a small PPO baseline on a SPARC Gym env and save a basic "
            "reward-evolution plot."
        )
    )
    parser.add_argument(
        "--env",
        default="servo_control",
        choices=["servo_control"],
        help="Training env to use. Extend this as new envs are added.",
    )
    parser.add_argument(
        "--total-timesteps",
        type=int,
        default=20_000,
        help="Total PPO training timesteps (default: 20000).",
    )
    parser.add_argument(
        "--max-episode-steps",
        type=int,
        default=200,
        help=(
            "Episode horizon in public control steps. Keep this shorter than the "
            "canonical 3000-step horizon for inexpensive early experiments."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=123,
        help="Training seed (default: 123).",
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
    parser.add_argument(
        "--output-dir",
        default="artifacts/servo_control_ppo",
        help="Directory to store the trained model, plot, and summary JSON.",
    )
    parser.add_argument(
        "--eval-episodes",
        type=int,
        default=5,
        help="Number of deterministic episodes for pre/post evaluation (default: 5).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print setup, evaluation, and periodic training progress to the console.",
    )
    parser.add_argument(
        "--progress-step-interval",
        type=int,
        default=2_000,
        help=(
            "When --verbose is enabled, print a progress line at least this often "
            "in training timesteps (default: 2000, use 0 to disable periodic "
            "progress lines)."
        ),
    )
    parser.add_argument(
        "--checkpoint-interval-episodes",
        type=int,
        default=20,
        help=(
            "Save a model checkpoint every N completed episodes "
            "(default: 20, use 0 to disable periodic checkpoints)."
        ),
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
    config = build_config(args)

    if args.env != "servo_control":
        raise ValueError(f"Unsupported env: {args.env}")

    summary = train_servo_control_ppo(
        total_timesteps=args.total_timesteps,
        output_dir=args.output_dir,
        seed=args.seed,
        max_episode_steps=args.max_episode_steps,
        use_compiled=not args.use_modular,
        mechanics_control_mode=args.mechanics_control_mode,
        config=config,
        eval_episodes=args.eval_episodes,
        verbose=args.verbose,
        progress_step_interval=args.progress_step_interval,
        checkpoint_interval_episodes=args.checkpoint_interval_episodes,
    )

    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
