#!/usr/bin/env python3
"""
Voltage Sweep Speed Analysis

This script sweeps through different voltage setpoints (5V to 80V in steps of 5V)
and measures the average advancing speed for each voltage. The goal is to 
characterize the relationship between voltage setpoint and cutting speed.

Setup:
- 0.25 mm wire diameter (via EnvironmentConfig.wire_diameter)
- 38 mm workpiece height
- 10 mm wire segments (~minimal thermal resolution vs default 0.2 mm)
- Very high WireModuleParameters.base_convection_coefficient to clamp wire
  temperature to the dielectric (effectively disables thermal transients)
- Velocity control mode

Speed measurement protocol:
- Start at 30 µm position
- Run for 0.5 seconds (stabilization)
- Run for another 0.5 seconds (measurement period)
- Calculate average speed during measurement period
"""

import numpy as np
import matplotlib.pyplot as plt
from collections import deque
from datetime import datetime
import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from src.wedm.envs import WireEDMEnv
from src.wedm.core.env_config import EnvironmentConfig
from src.wedm.modules.wire import WireModuleParameters


def create_voltage_controller(target_voltage: float = 30.0):
    """Create PI voltage controller that targets average voltage over last 1ms."""
    
    # PI controller state
    integral_error = 0.0
    
    # PI gains
    Kp = 0.05  # Proportional gain
    Ki = 0.1   # Integral gain
    
    def controller(env: WireEDMEnv, voltage_history: list = None):
        nonlocal integral_error
        
        # Calculate average voltage over the provided history (last 1ms of data)
        if voltage_history and len(voltage_history) > 0:
            avg_voltage = float(np.mean(tuple(voltage_history)))
        else:
            # Fallback to current voltage if no history provided
            avg_voltage = env.state.voltage
        
        # PI control
        error = target_voltage - avg_voltage
        integral_error += error
        
        # Integral windup protection
        integral_error = np.clip(integral_error, -100.0, 100.0)
        
        # PI output - when voltage is too high (negative error),
        # we want positive delta to move wire closer and reduce gap
        pi_output = -(Kp * error + Ki * integral_error * 0.001)
        
        # Velocity control: return target velocity [µm/s]
        delta = pi_output * 100.0  # Scale for velocity control
        delta = np.clip(delta, -1000.0, 1000.0)  # Limit velocity command
        
        return {
            "servo": np.array([delta], dtype=np.float32),
            "generator_control": {
                # Must match swept setpoint: env applies this to state.target_voltage
                "target_voltage": np.array([target_voltage], dtype=np.float32),
                "current_mode": np.array([7], dtype=np.int32),
                "ON_time": np.array([2.0], dtype=np.float32),
                "OFF_time": np.array([15.0], dtype=np.float32),
            },
        }
    
    return controller


def measure_speed_at_voltage(target_voltage: float, verbose: bool = True):
    """
    Measure average advancing speed at a specific voltage setpoint.
    
    Protocol:
    1. Initialize environment at 30 µm position
    2. Run for 0.5 seconds (500,000 µs) for stabilization
    3. Run for another 0.5 seconds for measurement
    4. Return average speed during measurement period
    
    Args:
        target_voltage: Target average voltage in V
        verbose: Print progress information
        
    Returns:
        dict with avg_speed_um_s, avg_speed_mm_min, avg_voltage, target_voltage,
        distance_traveled, time_elapsed
    """
    
    # Configure wire parameters: coarse segments + extreme convection (see wire module)
    wire_params = WireModuleParameters()
    wire_params.segment_len = 10.0  # [mm] = 10_000 µm segments
    wire_params.base_convection_coefficient = 1.0e8  # [W/m²·K] pulls T → dielectric T

    # Configure environment (wire diameter lives on config, not WireModuleParameters)
    env_config = EnvironmentConfig()
    env_config.workpiece_height = 38.0  # mm
    env_config.wire_diameter = 0.25  # mm

    # Initialize environment in velocity control mode
    env = WireEDMEnv(
        mechanics_control_mode="velocity",
        wire_params=wire_params,
        config=env_config,
    )
    env.reset(seed=0)
    
    # Set initial conditions
    env.state.workpiece_position = 30.0  # µm - start at 30 µm
    env.state.wire_position = 0.0  # µm
    env.state.target_position = 50_000.0  # µm - far target
    env.state.spark_status = [0, None, 0]
    env.state.dielectric_temperature = 293.15  # Room temperature in K
    
    # Initialize wire temperature array
    if len(env.state.wire_temperature) == 0:
        env.wire.update(env.state)
    
    # Create voltage controller
    controller = create_voltage_controller(target_voltage)
    
    # Voltage history tracking (for last 1ms)
    voltage_history: deque[float] = deque()
    time_history: deque[int] = deque()
    
    # Initialize action
    action = controller(env, None)
    
    # Phase 1: Stabilization (0.5 seconds = 500,000 µs)
    stabilization_time = 500_000  # µs
    if verbose:
        print(f"  Phase 1: Stabilizing for {stabilization_time/1000:.1f} ms...")
    
    for i in range(stabilization_time):
        obs, reward, terminated, truncated, info = env.step(action)
        
        # Track voltage history
        current_voltage = env.state.voltage
        voltage_history.append(current_voltage)
        time_history.append(env.state.time)
        
        # Keep only last 1ms of data
        cutoff_time = env.state.time - 1000.0
        while time_history and time_history[0] < cutoff_time:
            voltage_history.popleft()
            time_history.popleft()
        
        # Update action on control steps
        if info.get("control_step", False):
            action = controller(env, list(voltage_history))
        
        if terminated or truncated:
            if verbose:
                print(f"  WARNING: Simulation terminated during stabilization at t={env.state.time} us")
            return None
    
    # Record starting position and time for measurement phase
    start_position = env.state.workpiece_position
    start_time = env.state.time
    
    if verbose:
        print(f"  Phase 2: Measuring for {stabilization_time/1000:.1f} ms...")
        print(f"    Start position: {start_position:.2f} um")
    
    # Phase 2: Measurement (0.5 seconds = 500,000 µs)
    measurement_time = 500_000  # µs
    voltage_samples = []
    
    for i in range(measurement_time):
        obs, reward, terminated, truncated, info = env.step(action)
        
        # Track voltage history
        current_voltage = env.state.voltage
        voltage_history.append(current_voltage)
        time_history.append(env.state.time)
        voltage_samples.append(current_voltage)
        
        # Keep only last 1ms of data
        cutoff_time = env.state.time - 1000.0
        while time_history and time_history[0] < cutoff_time:
            voltage_history.popleft()
            time_history.popleft()
        
        # Update action on control steps
        if info.get("control_step", False):
            action = controller(env, list(voltage_history))
        
        if terminated or truncated:
            if verbose:
                print(f"  WARNING: Simulation terminated during measurement at t={env.state.time} us")
            # Use partial measurement if we got some data
            if i > 100_000:  # At least 0.1 seconds
                break
            else:
                return None
    
    # Calculate results
    end_position = env.state.workpiece_position
    end_time = env.state.time
    
    distance_traveled = end_position - start_position  # µm
    time_elapsed = end_time - start_time  # µs
    
    avg_speed_um_s = (distance_traveled / time_elapsed) * 1e6  # µm/s
    avg_speed_mm_min = avg_speed_um_s * 0.06  # mm/min
    avg_voltage = np.mean(voltage_samples) if voltage_samples else 0.0
    
    if verbose:
        print(f"    End position: {end_position:.2f} um")
        print(f"    Distance traveled: {distance_traveled:.2f} um")
        print(f"    Time elapsed: {time_elapsed/1000:.2f} ms")
        print(f"    Average speed: {avg_speed_mm_min:.3f} mm/min ({avg_speed_um_s:.1f} um/s)")
        print(f"    Average voltage: {avg_voltage:.2f} V")
    
    return {
        "avg_speed_um_s": avg_speed_um_s,
        "avg_speed_mm_min": avg_speed_mm_min,
        "avg_voltage": avg_voltage,
        "target_voltage": target_voltage,
        "distance_traveled": distance_traveled,
        "time_elapsed": time_elapsed,
    }


def main():
    """Main function to sweep voltages and measure speeds."""
    
    print("=" * 70)
    print("Voltage Sweep Speed Analysis")
    print("=" * 70)
    print()
    print("Configuration:")
    print("  Wire diameter: 0.25 mm")
    print("  Workpiece height: 38 mm")
    print("  Segment length: 10 mm (10_000 um)")
    print("  Wire base_convection_coefficient: 1e8 W/(m^2*K) (thermal transients quenched)")
    print("  Control mode: Velocity")
    print("  Voltage range: 5V to 80V in steps of 5V")
    print("  Measurement protocol: 0.5s stabilization + 0.5s measurement")
    print()
    
    # Voltage sweep range
    voltages = np.arange(5, 85, 5)  # 5, 10, 15, ..., 80
    
    results = []
    
    print(f"Starting voltage sweep ({len(voltages)} voltages)...")
    print()
    
    for i, voltage in enumerate(voltages):
        print(f"[{i+1}/{len(voltages)}] Testing voltage: {voltage:.1f} V")
        print("-" * 70)
        
        result = measure_speed_at_voltage(voltage, verbose=True)
        
        if result is not None:
            results.append(result)
            print(f"[ok] Success: {result['avg_speed_mm_min']:.3f} mm/min")
        else:
            print(f"[FAIL] Simulation terminated prematurely")
        
        print()
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    npz_filename = f"experiments/voltage_sweep_results_{timestamp}.npz"
    
    # Convert results to arrays
    target_voltages = np.array([r['target_voltage'] for r in results])
    avg_voltages = np.array([r['avg_voltage'] for r in results])
    avg_speeds_um_s = np.array([r['avg_speed_um_s'] for r in results])
    avg_speeds_mm_min = np.array([r['avg_speed_mm_min'] for r in results])
    np.savez(
        npz_filename,
        target_voltages=target_voltages,
        avg_voltages=avg_voltages,
        avg_speeds_um_s=avg_speeds_um_s,
        avg_speeds_mm_min=avg_speeds_mm_min,
        results=results,
    )
    
    print("=" * 70)
    print("Results Summary")
    print("=" * 70)
    print()
    print(f"{'Voltage (V)':<15} {'Avg Speed (mm/min)':<20} {'Avg Speed (um/s)':<20}")
    print("-" * 70)
    for r in results:
        print(f"{r['target_voltage']:<15.1f} {r['avg_speed_mm_min']:<20.3f} {r['avg_speed_um_s']:<20.1f}")
    print()
    print(f"Results saved to: {npz_filename}")
    print()
    
    # Create plot
    print("Generating plot...")
    
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Plot with markers and labels
    ax.plot(
        target_voltages,
        avg_speeds_mm_min,
        "o-",
        markersize=10,
        linewidth=2,
        color="steelblue",
        markeredgecolor="darkblue",
        markeredgewidth=2,
        label="Average advancing speed",
    )

    # Add value labels on each point
    for i, (x, y) in enumerate(zip(target_voltages, avg_speeds_mm_min)):
        ax.annotate(f'{y:.3f}', 
                   xy=(x, y), 
                   xytext=(0, 10),
                   textcoords='offset points',
                   ha='center',
                   fontsize=10,
                   bbox=dict(boxstyle='round,pad=0.3', 
                           facecolor='yellow', 
                           edgecolor='black',
                           alpha=0.7))
    
    ax.set_xlabel("Target generator voltage (V)", fontsize=14, fontweight="bold")
    ax.set_ylabel("Average advancing speed (mm/min)", fontsize=14, fontweight="bold")
    ax.set_title(
        "Average advancing speed vs target voltage\n"
        "(0.5 s stabilization + 0.5 s measurement per setpoint)",
        fontsize=16,
        fontweight="bold",
    )
    ax.legend(fontsize=12)
    ax.grid(True, alpha=0.3)
    
    # Save plot
    plot_filename = f"experiments/voltage_sweep_plot_{timestamp}.png"
    plt.tight_layout()
    plt.savefig(plot_filename, dpi=150, bbox_inches='tight')
    print(f"Plot saved to: {plot_filename}")
    
    plt.show()
    
    print()
    print("=" * 70)
    print("Analysis Complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
