#!/usr/bin/env python3
"""
Quick start example for Wire EDM Learning Environment.

This example demonstrates the basic usage of the environment
with a simple control strategy.
"""

import numpy as np
from wedm import WireEDMEnv, EnvironmentConfig


def main():
    print("=== Wire EDM Environment Quick Start ===\n")

    # Create environment with default settings
    env = WireEDMEnv()

    # Reset environment
    obs, info = env.reset()
    print(f"Environment reset. Initial gap: {env.state.workpiece_position:.1f} µm")
    print(f"Target cutting distance: {env.state.target_position:.1f} µm\n")

    # Simple control action
    action = {
        "servo": np.array([0.1]),  # Small positive feed
        "generator_control": {
            "target_voltage": np.array([80.0]),
            "current_mode": np.array([5]),  # I5 current mode
            "ON_time": np.array([3.0]),  # 3 µs on time
            "OFF_time": np.array([80.0]),  # 80 µs off time
        },
    }

    # Run for 100000 steps (100 control steps)
    step_count = 0
    spark_count = 0

    print("Running simulation...")
    for i in range(100000):
        obs, reward, terminated, truncated, info = env.step(action)

        # Count sparks
        if info.get("spark_state", 0) == 1:
            spark_count += 1

        # Print progress every 10 control steps
        if info.get("control_step", False):
            step_count += 1
            if step_count % 10 == 0:
                gap = env.state.workpiece_position - env.state.wire_position
                progress = (
                    env.state.workpiece_position / env.state.target_position
                ) * 100
                print(
                    f"Step {step_count}: Gap={gap:.1f}µm, Progress={progress:.1f}%, Sparks={spark_count}"
                )

        if terminated:
            print(f"\nSimulation terminated: {info}")
            break

    # Final statistics
    print(f"\n=== Simulation Complete ===")
    print(f"Total control steps: {step_count}")
    print(f"Total sparks: {spark_count}")
    print(f"Final position: {env.state.workpiece_position:.1f} µm")
    print(f"Wire broken: {env.state.is_wire_broken}")
    print(f"Target reached: {env.state.is_target_distance_reached}")


if __name__ == "__main__":
    main()
