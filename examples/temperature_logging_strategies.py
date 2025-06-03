#!/usr/bin/env python
# examples/temperature_logging_strategies.py
"""
Example demonstrating different temperature logging strategies.

Run with:
    python examples/temperature_logging_strategies.py
"""
import sys, pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from src.wedm.envs import WireEDMEnv
from src.wedm.modules.wire import WireModule
import numpy as np


def example_1_full_field_only():
    """Example 1: Log full temperature field, compute zone mean post-processing."""
    print("🔬 Example 1: Full Field Logging (Most efficient)")
    print("=" * 50)

    env = WireEDMEnv(mechanics_control_mode="velocity")
    env.reset(seed=42)

    # Default: compute_zone_mean=False (maximum performance)
    print(f"Zone mean calculation during simulation: DISABLED")
    print(f"Full temperature field: Available every step")

    # Run a few steps
    action = {
        "servo": np.array([100.0], dtype=np.float32),
        "generator_control": {
            "target_voltage": np.array([80.0], dtype=np.float32),
            "peak_current": np.array([200.0], dtype=np.float32),
            "ON_time": np.array([2.0], dtype=np.float32),
            "OFF_time": np.array([5.0], dtype=np.float32),
        },
    }

    for step in range(1000):
        obs, reward, done, truncated, info = env.step(action)

        # Compute zone mean only when you need it (e.g., every 100 steps for monitoring)
        if step % 100 == 0:
            zone_mean = env.wire.compute_zone_mean_temperature(
                env.state.wire_temperature
            )
            print(f"  Step {step}: Zone mean = {zone_mean:.2f} K")

    print(f"✅ Best for: Detailed analysis, post-processing, maximum performance")
    print()


def example_2_zone_mean_only():
    """Example 2: Log only zone mean temperature (lighter logging)."""
    print("🔬 Example 2: Zone Mean Only (Lighter logging)")
    print("=" * 50)

    env = WireEDMEnv(mechanics_control_mode="velocity")
    env.reset(seed=42)

    # Replace with zone mean calculation enabled
    env.wire = WireModule(env, compute_zone_mean=True)

    print(f"Zone mean calculation during simulation: ENABLED")
    print(f"Full temperature field: Still available but not logged")

    action = {
        "servo": np.array([100.0], dtype=np.float32),
        "generator_control": {
            "target_voltage": np.array([80.0], dtype=np.float32),
            "peak_current": np.array([200.0], dtype=np.float32),
            "ON_time": np.array([2.0], dtype=np.float32),
            "OFF_time": np.array([5.0], dtype=np.float32),
        },
    }

    for step in range(1000):
        obs, reward, done, truncated, info = env.step(action)

        if step % 100 == 0:
            # Zone mean available directly from state
            zone_mean = env.state.wire_average_temperature
            print(f"  Step {step}: Zone mean = {zone_mean:.2f} K")

    print(
        f"✅ Best for: Real-time monitoring, reduced log file size, summary statistics"
    )
    print()


def example_3_both():
    """Example 3: Log both for comprehensive analysis."""
    print("🔬 Example 3: Both Full Field + Zone Mean")
    print("=" * 50)

    env = WireEDMEnv(mechanics_control_mode="velocity")
    env.reset(seed=42)

    # Enable zone mean calculation
    env.wire = WireModule(env, compute_zone_mean=True)

    print(f"Zone mean calculation during simulation: ENABLED")
    print(f"Full temperature field: Available and logged")
    print(f"Zone mean: Available and logged")

    action = {
        "servo": np.array([100.0], dtype=np.float32),
        "generator_control": {
            "target_voltage": np.array([80.0], dtype=np.float32),
            "peak_current": np.array([200.0], dtype=np.float32),
            "ON_time": np.array([2.0], dtype=np.float32),
            "OFF_time": np.array([5.0], dtype=np.float32),
        },
    }

    for step in range(1000):
        obs, reward, done, truncated, info = env.step(action)

        if step % 100 == 0:
            zone_mean = env.state.wire_average_temperature
            full_field_mean = np.mean(env.state.wire_temperature)  # For verification
            print(
                f"  Step {step}: Zone mean = {zone_mean:.2f} K, Full mean = {full_field_mean:.2f} K"
            )

    print(f"✅ Best for: Research, debugging, validation")
    print()


def performance_comparison():
    """Compare performance of different strategies."""
    print("\n⚡ Performance Comparison (Detailed Step Timing)")
    print("=" * 50)

    import time

    strategies = [
        ("Full field only (zone mean DISABLED)", False),
        ("Zone mean ENABLED (computed in WireModule)", True),
    ]

    num_steps = 50000  # Increase steps for more stable timing

    for name, enable_zone_mean in strategies:
        env = WireEDMEnv(mechanics_control_mode="velocity")
        env.reset(seed=42)

        if enable_zone_mean:
            env.wire = WireModule(env, compute_zone_mean=True)
        else:
            # Ensure default wire module is used (compute_zone_mean=False by default)
            env.wire = WireModule(env, compute_zone_mean=False)

        # Initialize wire module
        env.wire.update(env.state)

        action = {
            "servo": np.array([100.0], dtype=np.float32),
            "generator_control": {
                "target_voltage": np.array([80.0], dtype=np.float32),
                "peak_current": np.array([200.0], dtype=np.float32),
                "ON_time": np.array([2.0], dtype=np.float32),
                "OFF_time": np.array([5.0], dtype=np.float32),
            },
        }

        step_times = []
        overall_start_time = time.perf_counter()

        for step_idx in range(num_steps):
            step_start_time = time.perf_counter()
            obs, reward, done, truncated, info = env.step(action)
            step_end_time = time.perf_counter()
            step_times.append(step_end_time - step_start_time)
            if done or truncated:
                print(f"Simulation ended early at step {step_idx}")
                break

        overall_end_time = time.perf_counter()
        total_wall_time = overall_end_time - overall_start_time

        avg_step_time_us = np.mean(step_times) * 1e6
        std_step_time_us = np.std(step_times) * 1e6
        total_sim_time_ms = env.state.time / 1000.0
        speed_factor = total_sim_time_ms / 1000.0 / total_wall_time

        print(f"{name}:")
        print(f"  Total wall time for {num_steps} steps: {total_wall_time:.4f} s")
        print(
            f"  Average env.step() time: {avg_step_time_us:.3f} µs (std: {std_step_time_us:.3f} µs)"
        )
        print(f"  Simulated time: {total_sim_time_ms:.1f} ms")
        print(f"  Speed factor: {speed_factor:.3f}× realtime")
        print(f"  Wire module compute_zone_mean: {env.wire.compute_zone_mean}")
        print()

    print("💡 Key Insights:")
    print("• Focus on 'Average env.step() time' for core simulation performance.")
    print("• Total wall time can be affected by Python overhead outside env.step().")


if __name__ == "__main__":
    example_1_full_field_only()
    example_2_zone_mean_only()
    example_3_both()
    performance_comparison()

    print("\n🎯 USAGE GUIDELINES:")
    print("=" * 50)
    print("Choose your strategy based on your needs:")
    print()
    print("📊 FULL FIELD (--log-strategy full_field)")
    print("  • Maximum performance (no zone mean calculation)")
    print("  • Complete temperature data for detailed analysis")
    print("  • Compute zone mean post-processing when needed")
    print("  • Best for: RL training, detailed physics analysis")
    print()
    print("📈 ZONE MEAN ONLY (--log-strategy zone_mean)")
    print("  • Light computational overhead")
    print("  • Smaller log files")
    print("  • Real-time temperature monitoring")
    print("  • Best for: Process monitoring, parameter optimization")
    print()
    print("📋 BOTH (--log-strategy both)")
    print("  • Comprehensive data collection")
    print("  • Validation and debugging")
    print("  • Research applications")
    print("  • Best for: Validation, research, debugging")
