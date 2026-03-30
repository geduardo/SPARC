"""Repeatable A/B benchmark for modular vs compiled scheduler paths."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wedm import EnvironmentConfig, WireEDMEnv
from wedm.envs.wire_edm import build_scalar_action
from wedm.modules.wire import WireModuleParameters


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark modular vs compiled scheduler paths."
    )
    parser.add_argument("--steps", type=int, default=200_000)
    parser.add_argument("--warmup", type=int, default=5_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument(
        "--segment-len",
        action="append",
        dest="segment_lengths",
        type=float,
        help="Wire segment length in mm. Repeat to benchmark multiple meshes.",
    )
    parser.add_argument("--servo", type=float, default=0.25)
    parser.add_argument("--target-voltage", type=float, default=90.0)
    parser.add_argument("--current-mode", type=int, default=1)
    parser.add_argument("--on-time", type=float, default=3.0)
    parser.add_argument("--off-time", type=float, default=20.0)
    args = parser.parse_args()
    if not args.segment_lengths:
        args.segment_lengths = [0.2, 0.05]
    return args


def make_env(segment_len_mm: float) -> WireEDMEnv:
    return WireEDMEnv(
        config=EnvironmentConfig(initial_gap=12.0, servo_interval=1, workpiece_height=20.0),
        wire_params=WireModuleParameters(segment_len=segment_len_mm),
    )


def reset_for_run(env: WireEDMEnv, *, seed: int) -> None:
    env.reset(seed=seed)
    env.state.time_since_servo = env.servo_interval


def warmup_modular(env: WireEDMEnv, action, warmup: int) -> None:
    for _ in range(warmup):
        if hasattr(env, "step_fast"):
            env.step_fast(action)
        else:
            env.step(action)


def warmup_compiled(env: WireEDMEnv, action, warmup: int) -> None:
    env.init_compiled_scheduler()
    for _ in range(warmup):
        if hasattr(env, "step_compiled_fast"):
            env.step_compiled_fast(action)
        else:
            env.step_compiled(action)


def run_modular(segment_len_mm: float, action, args: argparse.Namespace) -> list[float]:
    samples = []
    for _ in range(args.repeats):
        env = make_env(segment_len_mm)
        reset_for_run(env, seed=args.seed)
        warmup_modular(env, action, args.warmup)
        reset_for_run(env, seed=args.seed)

        t0 = time.perf_counter()
        for _ in range(args.steps):
            if hasattr(env, "step_fast"):
                terminated, truncated = env.step_fast(action)
            else:
                _, _, terminated, truncated, _ = env.step(action)
            if terminated or truncated:
                break
        wall = time.perf_counter() - t0
        samples.append(env.state.time / wall)
    return samples


def run_compiled(segment_len_mm: float, action, args: argparse.Namespace) -> list[float]:
    # One up-front JIT warmup outside timing.
    env = make_env(segment_len_mm)
    reset_for_run(env, seed=args.seed)
    warmup_compiled(env, action, 1_000)

    samples = []
    for _ in range(args.repeats):
        env = make_env(segment_len_mm)
        reset_for_run(env, seed=args.seed)
        warmup_compiled(env, action, args.warmup)
        reset_for_run(env, seed=args.seed)
        env.init_compiled_scheduler()

        t0 = time.perf_counter()
        for _ in range(args.steps):
            if hasattr(env, "step_compiled_fast"):
                terminated, truncated = env.step_compiled_fast(action)
            else:
                _, _, terminated, truncated, _ = env.step_compiled(action)
            if terminated or truncated:
                break
        wall = time.perf_counter() - t0
        samples.append(env._hot_state.time / wall)
    return samples


def main() -> None:
    args = parse_args()
    action = build_scalar_action(
        servo=args.servo,
        target_voltage=args.target_voltage,
        current_mode=args.current_mode,
        ON_time=args.on_time,
        OFF_time=args.off_time,
    )

    for segment_len_mm in args.segment_lengths:
        modular = run_modular(segment_len_mm, action, args)
        compiled = run_compiled(segment_len_mm, action, args)

        modular_median = statistics.median(modular)
        compiled_median = statistics.median(compiled)

        print(f"segment_len={segment_len_mm:.4f} mm")
        print(f"  modular samples : {[round(x, 2) for x in modular]}")
        print(f"  compiled samples: {[round(x, 2) for x in compiled]}")
        print(f"  modular median  : {modular_median:.2f} steps/s")
        print(f"  compiled median : {compiled_median:.2f} steps/s")
        print(f"  speedup         : {compiled_median / modular_median:.3f}x")


if __name__ == "__main__":
    main()
