#!/usr/bin/env python
"""Repeatable benchmark and hotspot profiler for the local simulation code.

This script forces imports from the repository's local ``src`` tree so the
results are not skewed by an unrelated editable install elsewhere on the
machine. It targets a representative active-cutting workload and emits stable
throughput numbers plus hotspot snapshots for optimization work.
"""

from __future__ import annotations

import argparse
import cProfile
import contextlib
from collections import defaultdict
from dataclasses import asdict, dataclass
import io
import json
import pathlib
import pstats
import statistics
import sys
import time
from typing import Any, Callable, DefaultDict, Dict, Iterable, List, Optional


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import numpy as np

from wedm import EnvironmentConfig, WireEDMEnv, WireModuleParameters


@dataclass
class RunSample:
    wall_seconds: float
    steps_run: int
    steps_per_second: float
    simulated_us: int
    termination_reason: str
    crater_count: int
    wire_temperature_mean: float
    wire_max_damage: float


@dataclass
class ModuleHotspot:
    name: str
    wall_share_pct: float
    avg_call_us: float
    calls: int
    total_seconds: float


@dataclass
class CProfileHotspot:
    function: str
    file: str
    line: int
    primitive_calls: int
    total_calls: int
    total_seconds: float
    cumulative_seconds: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark and profile representative active-cutting workloads."
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=100_000,
        help="Timed simulation steps per scenario (default: 100000).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=2_000,
        help="Warmup steps to run before each scenario family (default: 2000).",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Benchmark repeats per scenario for stable throughput numbers (default: 3).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=123,
        help="Seed for the representative workload (default: 123).",
    )
    parser.add_argument(
        "--initial-gap",
        type=float,
        default=12.0,
        help="Initial gap in um for the active workload (default: 12.0).",
    )
    parser.add_argument(
        "--servo-interval",
        type=int,
        default=1,
        help="Servo interval in us so each step applies control (default: 1).",
    )
    parser.add_argument(
        "--workpiece-height",
        type=float,
        default=20.0,
        help="Workpiece height in mm (default: 20.0).",
    )
    parser.add_argument(
        "--segment-len",
        action="append",
        dest="segment_lengths",
        type=float,
        help=(
            "Wire segment length in mm. Repeat the flag to compare multiple meshes. "
            "Defaults to 0.2 and 0.05."
        ),
    )
    parser.add_argument(
        "--servo",
        type=float,
        default=0.25,
        help="Fixed servo command for the benchmark action (default: 0.25).",
    )
    parser.add_argument(
        "--target-voltage",
        type=float,
        default=90.0,
        help="Fixed target voltage for the benchmark action (default: 90.0).",
    )
    parser.add_argument(
        "--current-mode",
        type=int,
        default=5,
        help="Integer current mode for the benchmark action (default: 5).",
    )
    parser.add_argument(
        "--on-time",
        type=float,
        default=3.0,
        help="Pulse ON time in us for the benchmark action (default: 3.0).",
    )
    parser.add_argument(
        "--off-time",
        type=float,
        default=20.0,
        help="Pulse OFF time in us for the benchmark action (default: 20.0).",
    )
    parser.add_argument(
        "--hotspots",
        choices=["none", "module", "cprofile", "both"],
        default="both",
        help="Hotspot report type to emit (default: both).",
    )
    parser.add_argument(
        "--profile-sort",
        choices=["cumulative", "tottime"],
        default="cumulative",
        help="Sort key for cProfile hotspots (default: cumulative).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of hotspot rows to print per table (default: 10).",
    )
    parser.add_argument(
        "--json-out",
        type=str,
        help="Optional path to write the full report as JSON.",
    )
    parser.add_argument(
        "--show-init-output",
        action="store_true",
        help="Print environment initialization messages instead of suppressing them.",
    )
    args = parser.parse_args()
    if not args.segment_lengths:
        args.segment_lengths = [0.2, 0.05]
    return args


def build_action(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "servo": np.array([args.servo], dtype=np.float32),
        "generator_control": {
            "target_voltage": np.array([args.target_voltage], dtype=np.float32),
            "current_mode": np.array([args.current_mode], dtype=np.int32),
            "ON_time": np.array([args.on_time], dtype=np.float32),
            "OFF_time": np.array([args.off_time], dtype=np.float32),
        },
    }


def create_env(
    args: argparse.Namespace, segment_len_mm: float, *, suppress_output: bool = True
) -> WireEDMEnv:
    config = EnvironmentConfig(
        initial_gap=args.initial_gap,
        servo_interval=args.servo_interval,
        workpiece_height=args.workpiece_height,
    )
    wire_params = WireModuleParameters(segment_len=segment_len_mm)

    if suppress_output and not args.show_init_output:
        with contextlib.redirect_stdout(io.StringIO()):
            return WireEDMEnv(config=config, wire_params=wire_params)
    return WireEDMEnv(config=config, wire_params=wire_params)


def prime_scenario(
    args: argparse.Namespace, segment_len_mm: float, action: Dict[str, Any]
) -> None:
    if args.warmup <= 0:
        return
    env = create_env(args, segment_len_mm)
    reset_for_run(env, seed=args.seed)
    run_step_loop(env, action, args.warmup)


def reset_for_run(env: WireEDMEnv, *, seed: int) -> None:
    env.reset(seed=seed)
    env.state.time_since_servo = env.servo_interval


def run_step_loop(env: WireEDMEnv, action: Dict[str, Any], steps: int) -> RunSample:

    termination_reason = "completed"
    steps_run = 0
    start = time.perf_counter()
    for _ in range(steps):
        _, _, terminated, truncated, info = env.step(action)
        steps_run += 1
        if terminated or truncated:
            if info.get("wire_broken", False):
                termination_reason = "wire_broken"
            elif info.get("target_reached", False):
                termination_reason = "target_reached"
            elif truncated:
                termination_reason = "truncated"
            else:
                termination_reason = "terminated"
            break

    wall_seconds = time.perf_counter() - start
    return RunSample(
        wall_seconds=wall_seconds,
        steps_run=steps_run,
        steps_per_second=(steps_run / wall_seconds) if wall_seconds > 0 else 0.0,
        simulated_us=int(env.state.time),
        termination_reason=termination_reason,
        crater_count=len(env.material.crater_volumes_um3),
        wire_temperature_mean=float(np.mean(env.state.wire_temperature)),
        wire_max_damage=float(env.state.wire_max_damage),
    )


def benchmark_scenario(
    args: argparse.Namespace, segment_len_mm: float, action: Dict[str, Any]
) -> Dict[str, Any]:
    prime_scenario(args, segment_len_mm, action)

    samples = []
    env = None
    for _ in range(args.repeats):
        env = create_env(args, segment_len_mm)
        reset_for_run(env, seed=args.seed)
        samples.append(run_step_loop(env, action, args.steps))

    if env is None:
        raise RuntimeError("Benchmark scenario did not create an environment.")

    wall_samples = [sample.wall_seconds for sample in samples]
    throughput_samples = [sample.steps_per_second for sample in samples]

    return {
        "segment_len_mm": float(segment_len_mm),
        "n_segments": int(env.wire.n_segments),
        "benchmark": {
            "repeats": int(args.repeats),
            "steps_requested": int(args.steps),
            "median_wall_seconds": float(statistics.median(wall_samples)),
            "median_steps_per_second": float(statistics.median(throughput_samples)),
            "mean_steps_per_second": float(statistics.mean(throughput_samples)),
            "samples": [asdict(sample) for sample in samples],
        },
    }


def wrap_timed_call(
    target: Any,
    attribute: str,
    label: str,
    times_ns: DefaultDict[str, int],
    calls: DefaultDict[str, int],
) -> None:
    original = getattr(target, attribute)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_ns = time.perf_counter_ns()
        try:
            return original(*args, **kwargs)
        finally:
            times_ns[label] += time.perf_counter_ns() - start_ns
            calls[label] += 1

    setattr(target, attribute, wrapper)


def module_hotspots(
    args: argparse.Namespace, segment_len_mm: float, action: Dict[str, Any]
) -> List[ModuleHotspot]:
    prime_scenario(args, segment_len_mm, action)

    env = create_env(args, segment_len_mm)
    times_ns = defaultdict(int)
    calls = defaultdict(int)

    wrap_timed_call(env, "_apply_action", "env._apply_action", times_ns, calls)
    wrap_timed_call(
        env, "_check_termination", "env._check_termination", times_ns, calls
    )
    wrap_timed_call(env, "_get_obs", "env._get_obs", times_ns, calls)
    wrap_timed_call(env, "_calc_reward", "env._calc_reward", times_ns, calls)

    for module_name in ["ignition", "material", "dielectric", "wire", "mechanics"]:
        module = getattr(env, module_name)
        wrap_timed_call(module, "update", module_name, times_ns, calls)

    reset_for_run(env, seed=args.seed)
    sample = run_step_loop(env, action, args.steps)
    rows = []
    for name, total_ns in sorted(
        times_ns.items(), key=lambda item: item[1], reverse=True
    ):
        rows.append(
            ModuleHotspot(
                name=name,
                wall_share_pct=(
                    (total_ns / 1e9 / sample.wall_seconds * 100.0)
                    if sample.wall_seconds > 0
                    else 0.0
                ),
                avg_call_us=(total_ns / calls[name] / 1000.0) if calls[name] else 0.0,
                calls=int(calls[name]),
                total_seconds=total_ns / 1e9,
            )
        )
    return rows


def is_project_file(filename: str) -> bool:
    normalized = filename.replace("\\", "/")
    return "/src/wedm/" in normalized


def format_path(path_str: str) -> str:
    path = pathlib.Path(path_str)
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except Exception:
        return path.name


def cprofile_hotspots(
    args: argparse.Namespace, segment_len_mm: float, action: Dict[str, Any]
) -> List[CProfileHotspot]:
    prime_scenario(args, segment_len_mm, action)

    env = create_env(args, segment_len_mm)
    reset_for_run(env, seed=args.seed)
    profiler = cProfile.Profile()
    profiler.enable()
    run_step_loop(env, action, args.steps)
    profiler.disable()

    stats = pstats.Stats(profiler)
    stats.sort_stats(args.profile_sort)

    rows = []
    for func in stats.fcn_list or []:
        filename, line_no, func_name = func
        if not is_project_file(filename):
            continue
        primitive_calls, total_calls, total_seconds, cumulative_seconds, _ = (
            stats.stats[func]
        )
        rows.append(
            CProfileHotspot(
                function=func_name,
                file=format_path(filename),
                line=int(line_no),
                primitive_calls=int(primitive_calls),
                total_calls=int(total_calls),
                total_seconds=float(total_seconds),
                cumulative_seconds=float(cumulative_seconds),
            )
        )
        if len(rows) >= args.top:
            break

    return rows


def print_header(args: argparse.Namespace) -> None:
    print("=== Simulation Profiling Harness ===")
    print(f"repo_root: {REPO_ROOT}")
    print(f"import_root: {SRC_ROOT}")
    print(
        "workload: "
        f"steps={args.steps} warmup={args.warmup} repeats={args.repeats} seed={args.seed} "
        f"initial_gap_um={args.initial_gap} servo_interval_us={args.servo_interval}"
    )
    print(
        "action: "
        f"servo={args.servo} target_voltage={args.target_voltage} "
        f"current_mode=I{args.current_mode} on_time_us={args.on_time} off_time_us={args.off_time}"
    )
    print(
        "meshes: "
        + ", ".join(f"{segment_len:.4f} mm" for segment_len in args.segment_lengths)
    )


def print_benchmark(report: Dict[str, Any]) -> None:
    benchmark = report["benchmark"]
    print(
        f"Benchmark: median={benchmark['median_steps_per_second']:.2f} steps/s "
        f"mean={benchmark['mean_steps_per_second']:.2f} steps/s "
        f"segments={report['n_segments']}"
    )
    for index, sample in enumerate(benchmark["samples"], start=1):
        print(
            f"  repeat {index}: {sample['steps_per_second']:.2f} steps/s "
            f"wall={sample['wall_seconds']:.6f}s steps={sample['steps_run']} "
            f"termination={sample['termination_reason']} craters={sample['crater_count']}"
        )


def print_module_hotspots(rows: Iterable[Dict[str, Any]]) -> None:
    print("Module hotspots:")
    for row in rows:
        print(
            f"  {row['name']:<22} share={row['wall_share_pct']:6.2f}% "
            f"avg_call={row['avg_call_us']:8.3f} us calls={row['calls']:6d}"
        )


def print_cprofile_hotspots(rows: Iterable[Dict[str, Any]], sort_key: str) -> None:
    print(f"cProfile hotspots ({sort_key}):")
    for row in rows:
        print(
            f"  {row['function']:<28} {row['file']}:{row['line']} "
            f"cum={row['cumulative_seconds']:.6f}s total={row['total_seconds']:.6f}s "
            f"calls={row['total_calls']}"
        )


def write_json_report(report: Dict[str, Any], output_path_str: str) -> None:
    output_path = pathlib.Path(output_path_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"JSON report written to {output_path}")


def main() -> None:
    args = parse_args()
    action = build_action(args)

    print_header(args)

    report = {
        "metadata": {
            "repo_root": str(REPO_ROOT),
            "import_root": str(SRC_ROOT),
            "steps": int(args.steps),
            "warmup": int(args.warmup),
            "repeats": int(args.repeats),
            "seed": int(args.seed),
            "initial_gap_um": float(args.initial_gap),
            "servo_interval_us": int(args.servo_interval),
            "workpiece_height_mm": float(args.workpiece_height),
            "segment_lengths_mm": [float(value) for value in args.segment_lengths],
            "hotspots": args.hotspots,
            "profile_sort": args.profile_sort,
        },
        "action": {
            "servo": float(args.servo),
            "target_voltage": float(args.target_voltage),
            "current_mode": f"I{args.current_mode}",
            "on_time_us": float(args.on_time),
            "off_time_us": float(args.off_time),
        },
        "scenarios": [],
    }

    for segment_len_mm in args.segment_lengths:
        print()
        print(f"=== Scenario: segment_len={segment_len_mm:.4f} mm ===")
        scenario_report = benchmark_scenario(args, segment_len_mm, action)
        print_benchmark(scenario_report)

        if args.hotspots in ("module", "both"):
            module_rows = [
                asdict(row) for row in module_hotspots(args, segment_len_mm, action)
            ]
            scenario_report["module_hotspots"] = module_rows[: args.top]
            print_module_hotspots(scenario_report["module_hotspots"])

        if args.hotspots in ("cprofile", "both"):
            cprofile_rows = [
                asdict(row) for row in cprofile_hotspots(args, segment_len_mm, action)
            ]
            scenario_report["cprofile_hotspots"] = cprofile_rows[: args.top]
            print_cprofile_hotspots(
                scenario_report["cprofile_hotspots"], args.profile_sort
            )

        report["scenarios"].append(scenario_report)

    if args.json_out:
        write_json_report(report, args.json_out)


if __name__ == "__main__":
    main()
