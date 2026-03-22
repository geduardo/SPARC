#!/usr/bin/env python3
"""
Run a configurable Wire EDM simulation.

This script provides a standard NPZ-recording simulation entry point with
explicit controller semantics:

- ``gap``: close the servo loop on the physical gap
- ``voltage``: close the servo loop on average gap voltage over the last 1 ms
- ``fixed-servo``: apply a constant servo command

Generator voltage and controller target voltage are separate CLI arguments so
their meanings are unambiguous.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wedm import WireEDMEnv, EnvironmentConfig
from wedm.envs.wire_edm import build_scalar_action
from wedm.modules.wire import WireModuleParameters
from wedm.utils.logger import SimulationLogger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Wire EDM simulation with configurable parameters.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Simulation parameters
    parser.add_argument(
        "--steps", type=int, default=50_000, help="Number of simulation steps"
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="Random seed for reproducibility"
    )

    # Environment configuration
    parser.add_argument(
        "--workpiece-height", type=float, default=5.0, help="Workpiece height in mm"
    )
    parser.add_argument(
        "--initial-gap", type=float, default=30.0, help="Initial gap in um"
    )
    parser.add_argument(
        "--target-distance",
        type=float,
        default=200.0,
        help="Target cutting distance in um",
    )
    parser.add_argument(
        "--control-mode",
        choices=["position", "velocity"],
        default="velocity",
        help="Mechanics control mode",
    )
    parser.add_argument(
        "--controller",
        choices=["gap", "voltage", "fixed-servo"],
        default="gap",
        help="High-level servo controller used to generate the servo action",
    )
    parser.add_argument(
        "--wire-diameter", type=float, default=0.2, help="Wire diameter in mm"
    )
    parser.add_argument(
        "--segment-len", type=float, default=0.2, help="Wire segment length in mm"
    )

    # Generator parameters
    parser.add_argument(
        "--current-mode",
        type=int,
        default=9,
        choices=[1, 3, 5, 7, 9, 11, 13, 15, 17],
        help="Current mode (odd numbers only)",
    )
    parser.add_argument(
        "--generator-voltage",
        type=float,
        default=80.0,
        help="Generator target voltage in V",
    )
    parser.add_argument(
        "--target-voltage",
        dest="legacy_target_voltage",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--on-time", type=float, default=2.0, help="ON time in us")
    parser.add_argument("--off-time", type=float, default=20.0, help="OFF time in us")

    # Controller parameters
    parser.add_argument(
        "--target-gap", type=float, default=15.0, help="Target gap in um for gap control"
    )
    parser.add_argument(
        "--target-avg-voltage",
        type=float,
        default=30.0,
        help="Target average voltage in V for voltage control",
    )
    parser.add_argument(
        "--servo",
        type=float,
        default=0.25,
        help=(
            "Fixed servo command used by fixed-servo mode. Units follow "
            "--control-mode: um for position, um/s for velocity."
        ),
    )

    # Output
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: outputs/simulation_<timestamp>.npz)",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress progress output"
    )

    args = parser.parse_args()

    if args.legacy_target_voltage is not None:
        parser.error(
            "`--target-voltage` is ambiguous. Use `--generator-voltage` for the "
            "generator setpoint or `--target-avg-voltage` for voltage control."
        )

    if args.generator_voltage < 0.0:
        parser.error("`--generator-voltage` must be non-negative.")

    if args.target_avg_voltage < 0.0:
        parser.error("`--target-avg-voltage` must be non-negative.")

    return args


def build_gap_action(
    env: WireEDMEnv,
    args: argparse.Namespace,
    integral_error: float,
) -> tuple[dict[str, object], float]:
    gap = env.state.workpiece_position - env.state.wire_position
    error = gap - args.target_gap

    if args.control_mode == "position":
        servo_value = np.clip(error * 0.1, -5.0, 5.0)
        next_integral_error = integral_error
    else:
        next_integral_error = np.clip(
            integral_error + error * 0.001, -50.0, 50.0
        )
        servo_value = np.clip(
            50.0 * error + 10.0 * next_integral_error, -500.0, 500.0
        )

    action = build_scalar_action(
        servo=servo_value,
        target_voltage=args.generator_voltage,
        current_mode=args.current_mode,
        ON_time=args.on_time,
        OFF_time=args.off_time,
    )
    return action, next_integral_error


def build_voltage_action(
    env: WireEDMEnv,
    args: argparse.Namespace,
    integral_error: float,
    voltage_history: list[float],
) -> tuple[dict[str, object], float, float]:
    if voltage_history:
        avg_voltage = float(np.mean(voltage_history))
    else:
        avg_voltage = float(env.state.voltage or 0.0)

    error = args.target_avg_voltage - avg_voltage
    next_integral_error = np.clip(integral_error + error, -100.0, 100.0)
    pi_output = -(0.05 * error + 0.1 * next_integral_error * 0.001)

    if args.control_mode == "position":
        servo_value = np.clip(pi_output, -5.0, 5.0)
    else:
        servo_value = np.clip(pi_output * 100.0, -1000.0, 1000.0)

    action = build_scalar_action(
        servo=servo_value,
        target_voltage=args.generator_voltage,
        current_mode=args.current_mode,
        ON_time=args.on_time,
        OFF_time=args.off_time,
    )
    return action, next_integral_error, avg_voltage


def build_fixed_servo_action(args: argparse.Namespace) -> dict[str, object]:
    return build_scalar_action(
        servo=args.servo,
        target_voltage=args.generator_voltage,
        current_mode=args.current_mode,
        ON_time=args.on_time,
        OFF_time=args.off_time,
    )


def main() -> None:
    args = parse_args()

    config = EnvironmentConfig(
        workpiece_height=args.workpiece_height,
        initial_gap=args.initial_gap,
        target_cutting_distance=args.target_distance,
        wire_diameter=args.wire_diameter,
    )
    wire_params = WireModuleParameters(segment_len=args.segment_len)

    env = WireEDMEnv(
        config=config,
        wire_params=wire_params,
        mechanics_control_mode=args.control_mode,
    )

    if args.output:
        output_path = Path(args.output)
    else:
        output_dir = REPO_ROOT / "outputs"
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"simulation_{timestamp}.npz"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger = SimulationLogger(
        {
            "signals_to_log": [
                "time",
                "workpiece_position",
                "wire_position",
                "gap_um",
                "wire_temperature",
                "wire_damage",
                "wire_max_damage",
                "voltage",
                "current",
                "spark_status",
                "debris_density",
            ],
            "log_frequency": {"type": "every_step"},
            "backend": {"type": "numpy", "filepath": str(output_path)},
        },
        env,
    )

    if not args.quiet:
        print("Wire EDM Simulation")
        print("=" * 40)
        print(f"Steps: {args.steps:,}")
        print(f"Workpiece height: {args.workpiece_height} mm")
        print(f"Wire diameter: {args.wire_diameter} mm")
        print(f"Segment length: {args.segment_len} mm")
        print(f"Initial gap: {args.initial_gap} um")
        print(f"Mechanics mode: {args.control_mode}")
        print(f"Controller: {args.controller}")
        if args.controller == "gap":
            print(f"Target gap: {args.target_gap} um")
        elif args.controller == "voltage":
            print(f"Target average voltage: {args.target_avg_voltage} V")
        else:
            print(f"Fixed servo command: {args.servo}")
        print(f"Generator voltage: {args.generator_voltage} V")
        print(f"Current mode: I{args.current_mode}")
        print(f"Output: {output_path}")
        print()

    env.reset(seed=args.seed)

    gap_integral_error = 0.0
    voltage_integral_error = 0.0
    voltage_history: list[float] = []
    time_history: list[int] = []

    if args.controller == "gap":
        action, gap_integral_error = build_gap_action(env, args, gap_integral_error)
    elif args.controller == "voltage":
        action, voltage_integral_error, _ = build_voltage_action(
            env, args, voltage_integral_error, voltage_history
        )
    else:
        action = build_fixed_servo_action(args)

    spark_count = 0
    control_steps = 0

    for i in range(args.steps):
        _, _, terminated, truncated, info = env.step(action)
        logger.collect(env.state, info)

        if args.controller == "voltage":
            current_voltage = float(env.state.voltage or 0.0)
            voltage_history.append(current_voltage)
            time_history.append(env.state.time)

            cutoff_time = env.state.time - 1000
            while time_history and time_history[0] < cutoff_time:
                time_history.pop(0)
                voltage_history.pop(0)

        if info.get("spark_state", 0) == 1:
            spark_count += 1

        if info.get("control_step", False):
            control_steps += 1
            if args.controller == "gap":
                action, gap_integral_error = build_gap_action(
                    env, args, gap_integral_error
                )
            elif args.controller == "voltage":
                action, voltage_integral_error, avg_voltage = build_voltage_action(
                    env, args, voltage_integral_error, voltage_history
                )
            else:
                action = build_fixed_servo_action(args)
                avg_voltage = float(env.state.voltage or 0.0)

            if not args.quiet and control_steps % 100 == 0:
                gap = env.state.workpiece_position - env.state.wire_position
                max_temp = np.max(env.state.wire_temperature)
                message = (
                    f"Step {control_steps}: gap={gap:.1f}um, "
                    f"max_temp={max_temp:.0f}K, sparks={spark_count}"
                )
                if args.controller == "voltage":
                    message += f", vavg={avg_voltage:.1f}V"
                print(message)

        if terminated or truncated:
            break

    logger.finalize()

    if not args.quiet:
        gap = env.state.workpiece_position - env.state.wire_position
        print()
        print("Simulation complete:")
        print(f"  Total steps: {i + 1:,}")
        print(f"  Control steps: {control_steps:,}")
        print(f"  Sparks: {spark_count:,}")
        print(f"  Final gap: {gap:.1f} um")
        print(f"  Final voltage: {float(env.state.voltage or 0.0):.1f} V")
        print(f"  Wire broken: {env.state.is_wire_broken}")
        print(f"\nData saved to: {output_path}")


if __name__ == "__main__":
    main()
