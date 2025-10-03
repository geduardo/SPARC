#!/usr/bin/env python3
"""
Quick start example for Wire EDM Learning Environment.

This example demonstrates the basic usage of the environment
with a PI voltage controller and data logging.
"""

import numpy as np
from datetime import datetime
from wedm import WireEDMEnv, EnvironmentConfig
from wedm.utils.logger import SimulationLogger


def create_voltage_controller(target_voltage: float = 30.0):
    """Create PI voltage controller that targets average voltage over last 1ms."""
    
    # PI controller state
    integral_error = 0.0
    
    # PI gains
    Kp = 0.05  # Proportional gain
    Ki = 0.1  # Integral gain
    
    def controller(env: WireEDMEnv, voltage_history: list = None):
        nonlocal integral_error
        
        # Calculate average voltage over the provided history (last 1ms of data)
        if voltage_history and len(voltage_history) > 0:
            avg_voltage = np.mean(voltage_history)
        else:
            # Fallback to current voltage if no history provided
            avg_voltage = env.state.voltage if env.state.voltage is not None else 0.0
        
        # PI control
        error = target_voltage - avg_voltage
        integral_error += error
        
        # Integral windup protection
        integral_error = np.clip(integral_error, -100.0, 100.0)
        
        # PI output - when voltage is too high (negative error),
        # we want positive delta to move wire closer and reduce gap
        pi_output = -(Kp * error + Ki * integral_error * 0.001)
        
        if env.mechanics.control_mode == "position":
            # Position control: return position increment [µm]
            delta = pi_output
            delta = np.clip(delta, -5.0, 5.0)  # Limit position command
        else:  # velocity control
            # Velocity control: return target velocity [µm/s]
            delta = pi_output * 100.0  # Scale for velocity control
            delta = np.clip(delta, -1000.0, 1000.0)  # Limit velocity command
        
        return {
            "servo": np.array([delta], dtype=np.float32),
            "generator_control": {
                "target_voltage": np.array([80.0], dtype=np.float32),
                "current_mode": np.array([7], dtype=np.int32),
                "ON_time": np.array([2.0], dtype=np.float32),
                "OFF_time": np.array([33.0], dtype=np.float32),
            },
        }
    
    return controller


def main():
    print("=== Wire EDM Environment Quick Start ===")
    print("Using PI Voltage Controller\n")

    # Create environment with custom workpiece height
    config = EnvironmentConfig(
        workpiece_height=5.0,  # mm (changed from default 20.0 mm)
    )
    env = WireEDMEnv(config=config)

    # Set up simulation data logger for dashboard
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_filepath = f"quickstart_data_{timestamp}.json"
    
    sim_logger_config = {
        "signals_to_log": [
            "time",
            "workpiece_position",
            "wire_position",
            "gap_width",
            "wire_average_temperature",
            "voltage",
            "current",
            "spark_status",
        ],
        "log_frequency": {"type": "every_step"},
        "backend": {
            "type": "json",
            "filepath": json_filepath,
            "indent": 2
        }
    }
    sim_logger = SimulationLogger(sim_logger_config, env)

    # Create voltage controller (target 30V average)
    target_voltage = 30.0
    controller = create_voltage_controller(target_voltage)
    
    # Voltage history tracking (for last 1ms)
    voltage_history = []
    time_history = []

    # Reset environment
    obs, info = env.reset()
    print(f"Environment reset. Initial gap: {env.state.workpiece_position:.1f} µm")
    print(f"Target cutting distance: {env.state.target_position:.1f} µm")
    print(f"Target average voltage: {target_voltage:.1f} V\n")

    # Initialize with default action
    action = controller(env, None)

    # Run simulation
    step_count = 0
    spark_count = 0

    print("Running simulation...")
    for i in range(200000):
        obs, reward, terminated, truncated, info = env.step(action)

        # Log simulation data
        sim_logger.collect(env.state, info)

        # Track voltage history every µs
        current_voltage = env.state.voltage if env.state.voltage is not None else 0.0
        voltage_history.append(current_voltage)
        time_history.append(env.state.time)
        
        # Keep only last 1ms of data (1000 µs)
        cutoff_time = env.state.time - 1000.0
        while time_history and time_history[0] < cutoff_time:
            voltage_history.pop(0)
            time_history.pop(0)

        # Count sparks
        if info.get("spark_state", 0) == 1:
            spark_count += 1

        # Update action on control steps
        if info.get("control_step", False):
            step_count += 1
            action = controller(env, voltage_history.copy())
            
            # Print progress every 10 control steps
            if step_count % 10 == 0:
                gap = env.state.workpiece_position - env.state.wire_position
                progress = (
                    env.state.workpiece_position / env.state.target_position
                ) * 100
                avg_voltage = np.mean(voltage_history) if voltage_history else 0.0
                print(
                    f"Step {step_count}: Gap={gap:.1f}µm, AvgV={avg_voltage:.1f}V, Progress={progress:.1f}%, Sparks={spark_count}"
                )

        if terminated:
            print(f"\nSimulation terminated: {info}")
            break

    # Finalize simulation logger
    sim_logger.finalize()

    # Final statistics
    print(f"\n=== Simulation Complete ===")
    print(f"Total control steps: {step_count}")
    print(f"Total sparks: {spark_count}")
    print(f"Final position: {env.state.workpiece_position:.1f} µm")
    print(f"Wire broken: {env.state.is_wire_broken}")
    print(f"Target reached: {env.state.is_target_distance_reached}")
    if voltage_history:
        print(f"Final average voltage: {np.mean(voltage_history):.1f} V")
    
    print(f"\n✅ Data saved to: {json_filepath}")


if __name__ == "__main__":
    main()
