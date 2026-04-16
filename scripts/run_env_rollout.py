#!/usr/bin/env python3
"""Run a fixed-action rollout in one of the training-facing SPARC envs."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wedm import EnvironmentConfig
from wedm.rl import ServoControlEnv


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the rollout CLI parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Run a fixed-action rollout in a training-facing SPARC env and "
            "print a concise summary."
        )
    )
    parser.add_argument(
        "--env",
        default="servo_control",
        choices=["servo_control"],
        help="Training env to run. Extend this choice list as new envs are added.",
    )
    duration_group = parser.add_mutually_exclusive_group()
    duration_group.add_argument(
        "--sim-seconds",
        type=float,
        default=1.0,
        help="Requested simulated rollout duration in seconds (default: 1.0).",
    )
    duration_group.add_argument(
        "--sim-us",
        type=int,
        help="Requested simulated rollout duration in microseconds.",
    )
    parser.add_argument(
        "--action",
        type=float,
        default=0.0,
        help="Constant scalar action to apply at every public step (default: 0.0).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=123,
        help="Reset seed used for the rollout (default: 123).",
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
        "--json",
        action="store_true",
        help="Print the final rollout summary as JSON.",
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


def build_env(args: argparse.Namespace):
    """Instantiate the requested training-facing env."""
    config = build_config(args)
    if args.env == "servo_control":
        return ServoControlEnv(
            config=config,
            mechanics_control_mode=args.mechanics_control_mode,
            use_compiled=not args.use_modular,
        )
    raise ValueError(f"Unsupported env: {args.env}")


def resolve_requested_sim_time_us(args: argparse.Namespace) -> int:
    """Return the requested rollout duration in simulated microseconds."""
    if args.sim_us is not None:
        if args.sim_us <= 0:
            raise ValueError("--sim-us must be positive")
        return int(args.sim_us)
    if args.sim_seconds <= 0.0:
        raise ValueError("--sim-seconds must be positive")
    return int(round(args.sim_seconds * 1_000_000.0))


def resolve_step_budget(env, requested_sim_time_us: int) -> int:
    """Compute the number of public steps needed to reach the target duration."""
    control_interval_us = getattr(env, "control_interval_us", None)
    if control_interval_us is None or control_interval_us <= 0:
        raise ValueError("Env does not expose a positive control_interval_us")
    return int(math.ceil(requested_sim_time_us / control_interval_us))


def run_rollout(args: argparse.Namespace) -> dict[str, object]:
    """Execute the requested rollout and return a compact summary."""
    env = build_env(args)
    try:
        _, info = env.reset(seed=args.seed)
        requested_sim_time_us = resolve_requested_sim_time_us(args)
        step_budget = resolve_step_budget(env, requested_sim_time_us)
        action = np.array([args.action], dtype=np.float32)

        cumulative_reward = 0.0
        terminated = False
        truncated = False
        steps_run = 0

        for _ in range(step_budget):
            _, reward, terminated, truncated, info = env.step(action)
            cumulative_reward += float(reward)
            steps_run += 1
            if terminated or truncated:
                break

        return {
            "env": args.env,
            "use_compiled": not args.use_modular,
            "seed": args.seed,
            "requested_sim_time_us": requested_sim_time_us,
            "actual_sim_time_us": int(info["sim_time_us"]),
            "public_steps_run": steps_run,
            "control_interval_us": int(info["control_interval_us"]),
            "interval_microsteps_last": int(info["interval_microsteps"]),
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "wire_broken": bool(info["wire_broken"]),
            "target_reached": bool(info["target_reached"]),
            "last_action": float(info["last_action"]),
            "cumulative_reward": float(cumulative_reward),
        }
    finally:
        env.close()


def main() -> int:
    """CLI entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args()
    summary = run_rollout(args)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for key, value in summary.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
