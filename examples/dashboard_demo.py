#!/usr/bin/env python3
"""
Dashboard Demo - Generate simulation data and export to JSON for web visualization.

This example demonstrates:
1. Running a Wire EDM simulation
2. Logging relevant signals for visualization
3. Exporting data to JSON format
4. Opening the web dashboard automatically

Usage:
    python examples/dashboard_demo.py
"""

import numpy as np
from wedm import WireEDMEnv, EnvironmentConfig
from wedm.utils.logger import SimulationLogger, LoggerConfig


def main():
    print("=== SPARC Dashboard Demo ===\n")

    # Configure environment
    config = EnvironmentConfig(
        workpiece_height=15.0,
        wire_diameter=0.25,
        target_cutting_distance=500.0,  # Shorter distance for quick demo
    )

    # Create environment
    env = WireEDMEnv(config=config, mechanics_control_mode="position")

    # Configure logger with JSON backend
    logger_config: LoggerConfig = {
        "signals_to_log": [
            # Essential signals for all panels
            "time",                         # Timeline
            "voltage",                      # Oscilloscope
            "current",                      # Oscilloscope
            "wire_position",                # Side view
            "workpiece_position",           # Side view
            "spark_status",                 # Side view & top view
            "debris_density",               # Top view
            "wire_temperature",             # Thermal profile
            "wire_average_temperature",     # Thermal profile (scalar)
            "dielectric_conductivity",      # Additional info
            "is_short_circuit",             # Status info
            "is_wire_broken",               # Status info
        ],
        "log_frequency": {"type": "interval", "value": 50},  # Log every 50 µs
        "backend": {
            "type": "json",
            "filepath": "visualization/data/simulation_data.json",
            "indent": 0  # Compact format for smaller file size
        }
    }

    logger = SimulationLogger(logger_config, env)

    # Reset environment
    obs, info = env.reset()
    print("Environment initialized\n")

    # Define control action
    action = {
        "servo": np.array([0.2]),  # Moderate feed rate
        "generator_control": {
            "target_voltage": np.array([80.0]),
            "current_mode": np.array([7]),  # I7
            "ON_time": np.array([3.0]),
            "OFF_time": np.array([50.0]),
        },
    }

    # Run simulation
    print("Running simulation...")
    step_count = 0
    max_steps = 10000  # Limit to prevent too long simulation

    while step_count < max_steps:
        # Step environment
        obs, reward, terminated, truncated, info = env.step(action)

        # Log current state
        logger.collect(env.state, info)

        # Print progress
        if info.get("control_step", False):
            step_count += 1
            if step_count % 100 == 0:
                progress = (env.state.workpiece_position / env.state.target_position) * 100
                gap = env.state.workpiece_position - env.state.wire_position
                print(f"  Step {step_count}: Progress {progress:.1f}%, Gap {gap:.1f}µm")

        if terminated or truncated:
            print(f"\nSimulation completed: {info}")
            break

    # Finalize logging (saves JSON file)
    print("\nSaving data to JSON...")
    logger.finalize()

    # Add metadata to the JSON file for visualization
    json_filepath = logger.get_data()
    if json_filepath:
        import json
        import pathlib

        # Load existing data
        path = pathlib.Path(json_filepath)
        with open(path, 'r') as f:
            data = json.load(f)

        # Add metadata for visualization
        data['metadata'] = {
            'wire_diameter': config.wire_diameter,
            'initial_gap': config.initial_gap,
            'workpiece_height': config.workpiece_height,
            'target_cutting_distance': config.target_cutting_distance,
        }

        # Save back
        with open(path, 'w') as f:
            json.dump(data, f, separators=(',', ':'))

        print(f"✓ Added metadata to JSON")

    print(f"\n✓ Data saved to: {json_filepath}")
    print(f"✓ Dashboard HTML: visualization/dashboard.html")
    print("\nTo view the dashboard:")
    print("  1. Open visualization/dashboard.html in your web browser")
    print("  2. Click 'Load Data' and select the JSON file")
    print("  3. Use timeline controls to play/pause the animation")

    # Optional: Try to open dashboard automatically
    try:
        import webbrowser
        import pathlib
        dashboard_path = pathlib.Path("visualization/dashboard.html").resolve()
        if dashboard_path.exists():
            print(f"\nOpening dashboard in browser...")
            webbrowser.open(f"file://{dashboard_path}")
        else:
            print(f"\nNote: Dashboard file not found at {dashboard_path}")
    except Exception as e:
        print(f"\nCouldn't open browser automatically: {e}")

    print("\n=== Demo Complete ===")


if __name__ == "__main__":
    main()
