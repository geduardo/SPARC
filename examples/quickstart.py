#!/usr/bin/env python3
"""
Quick start example for Wire EDM Learning Environment.

This example demonstrates the basic usage of the environment
with a PI gap controller and data logging for visualization.
"""

import numpy as np
from datetime import datetime
from wedm import WireEDMEnv, EnvironmentConfig
from wedm.modules.wire import WireModuleParameters
from wedm.utils.logger import SimulationLogger


def create_gap_controller(target_gap: float = 15.0):
    """Create PI gap controller that maintains target gap distance."""

    # PI controller state
    integral_error = 0.0

    # PI gains (tuned for velocity control)
    Kp = 50.0   # Proportional gain [µm/s per µm error]
    Ki = 10.0   # Integral gain

    def controller(env: WireEDMEnv):
        nonlocal integral_error

        # Calculate current gap
        gap = env.state.workpiece_position - env.state.wire_position

        # PI control
        error = target_gap - gap
        integral_error += error * 0.001  # Scale by dt (1ms control interval)

        # Integral windup protection
        integral_error = np.clip(integral_error, -50.0, 50.0)

        # PI output: velocity command [µm/s]
        # Positive error (gap too small) -> negative velocity (retract)
        # Negative error (gap too large) -> positive velocity (advance)
        velocity = Kp * error + Ki * integral_error
        velocity = np.clip(velocity, -500.0, 500.0)

        return {
            "servo": np.array([velocity], dtype=np.float32),
            "generator_control": {
                "target_voltage": np.array([80.0], dtype=np.float32),
                "current_mode": np.array([9], dtype=np.int32),  # I9
                "ON_time": np.array([2.0], dtype=np.float32),
                "OFF_time": np.array([20.0], dtype=np.float32),
            },
        }

    return controller


def main():
    print("=== Wire EDM Environment Quick Start ===")
    print("Using PI Gap Controller (velocity mode)\n")

    # Environment configuration
    config = EnvironmentConfig(
        workpiece_height=5.0,       # mm
        initial_gap=30.0,           # µm
        target_cutting_distance=200.0,  # µm
    )

    # Wire module configuration
    wire_params = WireModuleParameters(
        segment_len=0.4,  # mm (400 µm segments)
    )

    # Create environment
    env = WireEDMEnv(
        config=config,
        wire_params=wire_params,
        mechanics_control_mode="velocity",
    )

    # Set up simulation data logger
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"quickstart_{timestamp}.npz"

    logger_config = {
        "signals_to_log": [
            "time",
            "workpiece_position",
            "wire_position",
            "gap_width",
            "wire_temperature",  # Full temperature field
            "voltage",
            "current",
            "spark_status",
            "debris_density",
        ],
        "log_frequency": {"type": "every_step"},
        "backend": {"type": "numpy", "filepath": filepath},
    }
    logger = SimulationLogger(logger_config, env)

    # Create gap controller
    target_gap = 15.0  # µm
    controller = create_gap_controller(target_gap)

    # Reset environment
    obs, info = env.reset()
    print(f"Workpiece height: {config.workpiece_height} mm")
    print(f"Initial gap: {env.state.workpiece_position - env.state.wire_position:.1f} µm")
    print(f"Target gap: {target_gap} µm")
    print(f"Control mode: velocity\n")

    # Run simulation
    step_count = 0
    spark_count = 0
    action = controller(env)

    print("Running simulation (50,000 steps)...")
    for i in range(50000):
        obs, reward, terminated, truncated, info = env.step(action)

        # Log simulation data
        logger.collect(env.state, info)

        # Count sparks
        if info.get("spark_state", 0) == 1:
            spark_count += 1

        # Update action on control steps
        if info.get("control_step", False):
            step_count += 1
            action = controller(env)

            # Print progress every 50 control steps
            if step_count % 50 == 0:
                gap = env.state.workpiece_position - env.state.wire_position
                max_temp = np.max(env.state.wire_temperature)
                print(
                    f"Step {step_count}: Gap={gap:.1f}µm, MaxT={max_temp:.0f}K, Sparks={spark_count}"
                )

        if terminated:
            print(f"\nSimulation terminated: {info}")
            break

    # Finalize logger
    logger.finalize()

    # Final statistics
    print(f"\n=== Simulation Complete ===")
    print(f"Total steps: {i+1}")
    print(f"Control steps: {step_count}")
    print(f"Total sparks: {spark_count}")
    print(f"Final gap: {env.state.workpiece_position - env.state.wire_position:.1f} µm")
    print(f"Max wire temperature: {np.max(env.state.wire_temperature):.0f} K")
    print(f"Wire broken: {env.state.is_wire_broken}")

    print(f"\nData saved to: {filepath}")
    print("To visualize: move file to visualization/data/ and open dashboard.html")


if __name__ == "__main__":
    main()
