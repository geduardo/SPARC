#!/usr/bin/env python3
"""
Quickstart: Run a simple Wire EDM simulation and save data for visualization.

This script runs a short simulation with sensible defaults and saves the
output to outputs/quickstart.npz. Use this to quickly generate data for
the visualization dashboard.

Usage:
    python examples/quickstart.py
"""

import numpy as np
from pathlib import Path

from wedm import WireEDMEnv, EnvironmentConfig
from wedm.utils.logger import SimulationLogger


def main():
    print("Wire EDM Simulation - Quickstart")
    print("=" * 40)

    # Fixed configuration for quickstart
    config = EnvironmentConfig(
        workpiece_height=5.0,
        initial_gap=30.0,
        target_cutting_distance=200.0,
    )

    env = WireEDMEnv(
        config=config,
        mechanics_control_mode="velocity",
    )

    # Output path
    output_dir = Path(__file__).parent.parent / "outputs"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "quickstart.npz"

    # Logger configuration
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

    # Simple PI gap controller
    target_gap = 15.0
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
                "target_voltage": np.array([80.0], dtype=np.float32),
                "current_mode": np.array([9], dtype=np.int32),
                "ON_time": np.array([2.0], dtype=np.float32),
                "OFF_time": np.array([20.0], dtype=np.float32),
            },
        }

    # Run simulation
    env.reset()
    action = get_action()
    n_steps = 50_000
    spark_count = 0

    print(f"Running {n_steps:,} steps...")

    for i in range(n_steps):
        obs, reward, terminated, truncated, info = env.step(action)
        logger.collect(env.state, info)

        if info.get("spark_state", 0) == 1:
            spark_count += 1

        if info.get("control_step", False):
            action = get_action()

        if terminated:
            break

    logger.finalize()

    # Summary
    gap = env.state.workpiece_position - env.state.wire_position
    print(f"\nSimulation complete:")
    print(f"  Steps: {i + 1:,}")
    print(f"  Sparks: {spark_count:,}")
    print(f"  Final gap: {gap:.1f} um")
    print(f"  Wire broken: {env.state.is_wire_broken}")
    print(f"\nData saved to: {output_path}")
    print("\nTo visualize, open visualization/dashboard.html")


if __name__ == "__main__":
    main()
