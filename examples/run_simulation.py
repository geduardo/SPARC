#!/usr/bin/env python3
"""
Run a configurable Wire EDM simulation.

This script provides full control over simulation parameters via command-line
arguments. Output is saved to outputs/simulation_<timestamp>.npz.

Usage:
    python examples/run_simulation.py --help
    python examples/run_simulation.py --steps 100000 --workpiece-height 10
    python examples/run_simulation.py --current-mode 13 --target-gap 20
"""

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np

from wedm import WireEDMEnv, EnvironmentConfig
from wedm.utils.logger import SimulationLogger


def parse_args():
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
        help="Servo control mode",
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
        "--target-voltage", type=float, default=80.0, help="Target voltage in V"
    )
    parser.add_argument("--on-time", type=float, default=2.0, help="ON time in us")
    parser.add_argument("--off-time", type=float, default=20.0, help="OFF time in us")

    # Controller parameters
    parser.add_argument(
        "--target-gap", type=float, default=15.0, help="Target gap for controller in um"
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

    return parser.parse_args()


def main():
    args = parse_args()

    # Environment configuration
    config = EnvironmentConfig(
        workpiece_height=args.workpiece_height,
        initial_gap=args.initial_gap,
        target_cutting_distance=args.target_distance,
    )

    env = WireEDMEnv(
        config=config,
        mechanics_control_mode=args.control_mode,
    )

    # Output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_dir = Path(__file__).parent.parent / "outputs"
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"simulation_{timestamp}.npz"

    # Logger
    logger = SimulationLogger(
        {
            "signals_to_log": [
                "time",
                "workpiece_position",
                "wire_position",
                "gap_width",
                "wire_temperature",
                "wire_material_positions_mm",
                "wire_damage",
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

    # PI gap controller
    target_gap = args.target_gap
    integral_error = 0.0
    Kp, Ki = 50.0, 10.0

    def get_action():
        nonlocal integral_error
        gap = env.state.workpiece_position - env.state.wire_position
        error = target_gap - gap
        integral_error = np.clip(integral_error + error * 0.001, -50.0, 50.0)
        velocity = np.clip(Kp * error + Ki * integral_error, -500.0, 500.0)
        return {
            "servo": np.array([velocity], dtype=np.float32),
            "generator_control": {
                "target_voltage": np.array([args.target_voltage], dtype=np.float32),
                "current_mode": np.array([args.current_mode], dtype=np.int32),
                "ON_time": np.array([args.on_time], dtype=np.float32),
                "OFF_time": np.array([args.off_time], dtype=np.float32),
            },
        }

    # Print configuration
    if not args.quiet:
        print("Wire EDM Simulation")
        print("=" * 40)
        print(f"Steps: {args.steps:,}")
        print(f"Workpiece height: {args.workpiece_height} mm")
        print(f"Initial gap: {args.initial_gap} um")
        print(f"Target gap: {args.target_gap} um")
        print(f"Current mode: I{args.current_mode}")
        print(f"Control mode: {args.control_mode}")
        print(f"Output: {output_path}")
        print()

    # Run simulation
    env.reset(seed=args.seed)
    action = get_action()
    spark_count = 0
    control_steps = 0

    for i in range(args.steps):
        obs, reward, terminated, truncated, info = env.step(action)
        logger.collect(env.state, info)

        if info.get("spark_state", 0) == 1:
            spark_count += 1

        if info.get("control_step", False):
            control_steps += 1
            action = get_action()

            if not args.quiet and control_steps % 100 == 0:
                gap = env.state.workpiece_position - env.state.wire_position
                max_temp = np.max(env.state.wire_temperature)
                print(
                    f"Step {control_steps}: gap={gap:.1f}um, "
                    f"max_temp={max_temp:.0f}K, sparks={spark_count}"
                )

        if terminated:
            break

    logger.finalize()

    # Summary
    if not args.quiet:
        gap = env.state.workpiece_position - env.state.wire_position
        print()
        print("Simulation complete:")
        print(f"  Total steps: {i + 1:,}")
        print(f"  Control steps: {control_steps:,}")
        print(f"  Sparks: {spark_count:,}")
        print(f"  Final gap: {gap:.1f} um")
        print(f"  Wire broken: {env.state.is_wire_broken}")
        print(f"\nData saved to: {output_path}")


if __name__ == "__main__":
    main()
