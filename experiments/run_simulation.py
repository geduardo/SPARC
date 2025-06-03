#!/usr/bin/env python
# experiments/smoke_test.py
"""
Quick-n-dirty simulation run to be sure everything wires together.
Run:
    python experiments/smoke_test.py --steps 200000 --plot
    python experiments/smoke_test.py --steps 200000 --plot --mode velocity
"""
from __future__ import annotations

import argparse
import time
from typing import Dict, Any, Tuple, Optional

import numpy as np
import sys, pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from src.wedm.envs import WireEDMEnv
from src.wedm.utils.logger import SimulationLogger, LoggerConfig


def create_gap_controller(desired_gap: float = 5.0):  # µm
    """Create adaptive gap controller that works with both control modes."""

    def controller(env: WireEDMEnv) -> Dict[str, Any]:
        gap = env.state.workpiece_position - env.state.wire_position
        error = gap - desired_gap

        if env.mechanics.control_mode == "position":
            # Position control: return position increment [µm]
            delta = error * 0.1  # Conservative proportional gain
        else:  # velocity control
            # Velocity control: return target velocity [µm/s]
            delta = error * 50.0  # Higher gain for velocity control
            delta = np.clip(delta, -1000.0, 1000.0)  # Limit velocity command

        return {
            "servo": np.array([delta], dtype=np.float32),
            "generator_control": {
                "target_voltage": np.array([80.0], dtype=np.float32),
                # Current mode selection (1-19 maps directly to I1-I19):
                # Mode 13 = I13 = 215A machine current → mapped to 5A crater data
                # Other options: 5=I5(60A→1A), 9=I9(110A→3A), 17=I17(425A→11A), 19=I19(600A→17A)
                "current_mode": np.array(
                    [7], dtype=np.int32
                ),  # I13 mode - good balance for general machining
                "ON_time": np.array([2.0], dtype=np.float32),
                "OFF_time": np.array([33.0], dtype=np.float32),
            },
        }

    return controller


def create_voltage_controller(target_voltage: float = 30.0):  # V
    """Create PI voltage controller that targets average voltage over last 1ms."""

    # PI controller state
    integral_error = 0.0

    # PI gains
    Kp = 0.05  # Proportional gain
    Ki = 0.1  # Integral gain

    def controller(env: WireEDMEnv, voltage_history: list = None) -> Dict[str, Any]:
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

        # PI output - FIXED SIGN: when voltage is too high (negative error),
        # we want positive delta to move wire closer and reduce gap
        pi_output = -(
            Kp * error + Ki * integral_error * 0.001
        )  # Negated to fix direction

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


def setup_logger(
    control_mode: str,
    log_to_file: bool = True,
    log_strategy: str = "full_field",
    enable_plotting: bool = False,
) -> LoggerConfig:
    """
    Setup logger configuration with flexible temperature logging strategy.

    Args:
        control_mode: "position" or "velocity"
        log_to_file: Whether to log to file
        log_strategy: "full_field", "zone_mean", or "both"
        enable_plotting: Whether plotting will be used (affects memory logging)
    """
    base_signals = [
        "time",
        "voltage",
        "current",
        "wire_position",
        "wire_velocity",
        "workpiece_position",
        "target_delta",
        "debris_concentration",
        "dielectric_flow_rate",
        "is_short_circuit",
        "flow_rate",  # Dimensionless flow condition (0-1)
    ]

    # Add temperature signals based on strategy
    if log_strategy == "full_field":
        signals_to_log = base_signals + ["wire_temperature"]
    elif log_strategy == "zone_mean":
        signals_to_log = base_signals + ["wire_average_temperature"]
    elif log_strategy == "both":
        signals_to_log = base_signals + ["wire_temperature", "wire_average_temperature"]
    else:
        raise ValueError(f"Unknown log_strategy: {log_strategy}")

    if log_to_file:
        return {
            "signals_to_log": signals_to_log,
            "log_frequency": {"type": "every_step"},
            "backend": {
                "type": "numpy",
                "filepath": f"logs/smoke_test_{control_mode}_control.npz",
                "compress": True,
            },
        }
    else:
        # If plotting is enabled, log all signals to memory; otherwise just time
        memory_signals = signals_to_log if enable_plotting else ["time"]
        return {
            "signals_to_log": memory_signals,
            "log_frequency": {
                "type": "every_step" if enable_plotting else "control_step"
            },
            "backend": {"type": "memory"},
        }


def initialize_environment(
    control_mode: str, seed: int = 0, log_strategy: str = "full_field"
) -> WireEDMEnv:
    """
    Initialize and setup the EDM environment with appropriate wire configuration.

    Args:
        control_mode: "position" or "velocity"
        seed: Random seed
        log_strategy: "full_field", "zone_mean", or "both"
    """
    # Now using the standard environment with built-in optimizations
    env = WireEDMEnv(mechanics_control_mode=control_mode)
    env.reset(seed=seed)

    # Configure wire module based on logging strategy
    if log_strategy in ["zone_mean", "both"]:
        # Replace wire module with zone mean calculation enabled
        from src.wedm.modules.wire import WireModule

        env.wire = WireModule(env, compute_zone_mean=True)
        print(f"📊 Zone mean calculation: ENABLED (strategy: {log_strategy})")
    else:
        print(f"📊 Zone mean calculation: DISABLED (strategy: {log_strategy})")

    # Set initial conditions
    env.state.workpiece_position = 70.0  # µm
    env.state.wire_position = 10.0  # µm
    env.state.target_position = 5_000.0  # µm
    env.state.spark_status = [0, None, 0]
    env.state.dielectric_temperature = 293.15  # Room temperature in K

    # Initialize wire temperature array
    if len(env.state.wire_temperature) == 0:
        env.wire.update(env.state)

    return env


def run_simulation(
    env: WireEDMEnv,
    max_steps: int,
    verbose: bool,
    logger_config: LoggerConfig,
    controller_type: str = "gap",
    target_voltage: float = 30.0,
) -> Tuple[Any, float, int]:
    """Run the core simulation loop."""
    print(
        f"🔧 Running smoke test with {env.mechanics.control_mode.upper()} control mode"
    )

    if controller_type == "gap":
        print(f"🎯 Using GAP controller (target: 5.0 µm)")
    else:
        print(
            f"🎯 Using VOLTAGE controller (target: {target_voltage:.1f} V average over 1ms)"
        )

    logger = SimulationLogger(config=logger_config, env_reference=env)
    logger.reset()

    # Create the appropriate controller
    if controller_type == "gap":
        controller = create_gap_controller()
    else:  # voltage
        controller = create_voltage_controller(target_voltage)

    # For voltage controller, maintain voltage history over last 1ms
    voltage_history = []
    time_history = []

    action = (
        controller(env)
        if controller_type == "gap"
        else controller(env, voltage_history)
    )

    # Print simulation start message
    print(f"🚀 Starting simulation for {max_steps:,} µs...")
    start_time = time.time()

    for step in range(max_steps):
        # Run the simulation step
        obs, reward, terminated, truncated, info = env.step(action)
        logger.collect(env.state, info)

        # For voltage controller, collect voltage history every µs
        if controller_type == "voltage":
            current_voltage = (
                env.state.voltage if env.state.voltage is not None else 0.0
            )
            voltage_history.append(current_voltage)
            time_history.append(env.state.time)

            # Keep only last 1ms of data (1000 µs)
            cutoff_time = env.state.time - 1000.0
            while time_history and time_history[0] < cutoff_time:
                voltage_history.pop(0)
                time_history.pop(0)

        # Update action on control steps
        if info.get("control_step", False):
            if controller_type == "gap":
                action = controller(env)
            else:  # voltage - pass the collected voltage history
                action = controller(
                    env, voltage_history.copy()
                )  # Pass copy to avoid modification

            if verbose:
                # Calculate true average for display
                if controller_type == "voltage" and voltage_history:
                    true_avg_voltage = np.mean(voltage_history)
                    print_step_info(
                        env, step, controller_type, target_voltage, true_avg_voltage
                    )
                else:
                    print_step_info(env, step, controller_type, target_voltage)

        # Check termination
        if terminated or truncated:
            reason = get_termination_reason(info, terminated, truncated)
            print(f"\n💥 Terminated at t={env.state.time} µs ({reason}).")
            break

    wall_time = time.time() - start_time

    # Print simulation completion message
    print(f"✅ Simulation completed! Took {wall_time:.2f} seconds")

    logger.finalize()
    log_data = logger.get_data()

    # Calculate simulation time
    sim_time_us = get_simulation_time(log_data, logger_config)
    print_performance_summary(sim_time_us, wall_time)

    return log_data, wall_time, sim_time_us


def print_step_info(
    env: WireEDMEnv,
    step: int,
    controller_type: str = "gap",
    target_voltage: float = 30.0,
    true_avg_voltage: float = None,
) -> None:
    """Print verbose step information."""
    gap = env.state.workpiece_position - env.state.wire_position
    target_unit = "µm" if env.mechanics.control_mode == "position" else "µm/s"

    # Compute wire average temperature only when needed for printing
    avg_wire_temp = env.wire.compute_zone_mean_temperature(env.state.wire_temperature)

    if controller_type == "gap":
        print(
            f"[{env.state.time/1000:.1f} ms] "
            f"gap={gap:6.1f} µm   "
            f"target_delta={env.state.target_delta:6.1f} {target_unit}   "
            f"wire_vel={env.state.wire_velocity:6.1f} µm/s   "
            f"V={env.state.voltage or 0.0:6.1f}  I={env.state.current or 0.0:6.1f}  "
            f"AvgWireT={avg_wire_temp:6.1f} K"
        )
    else:  # voltage controller
        current_voltage = env.state.voltage or 0.0
        # Use true average if available, otherwise use current voltage
        display_avg = (
            true_avg_voltage if true_avg_voltage is not None else current_voltage
        )
        voltage_error = target_voltage - display_avg
        print(
            f"[{env.state.time/1000:.1f} ms] "
            f"Vavg={display_avg:6.1f} (target={target_voltage:4.1f}, err={voltage_error:6.1f})   "
            f"gap={gap:6.1f} µm   "
            f"target_delta={env.state.target_delta:6.1f} {target_unit}   "
            f"wire_vel={env.state.wire_velocity:6.1f} µm/s   "
            f"I={env.state.current or 0.0:6.1f}  "
            f"AvgWireT={avg_wire_temp:6.1f} K"
        )


def get_termination_reason(info: Dict, terminated: bool, truncated: bool) -> str:
    """Determine termination reason."""
    if info.get("target_reached", False):
        return "target reached"
    elif info.get("wire_broken", False):
        return "wire broken"
    elif terminated:
        return "terminated"
    elif truncated:
        return "truncated"
    else:
        return "unknown"


def get_simulation_time(log_data: Any, logger_config: LoggerConfig) -> int:
    """Extract simulation time from log data."""
    if logger_config["backend"]["type"] == "memory":
        data = log_data
    else:  # numpy backend
        try:
            data = np.load(log_data) if isinstance(log_data, str) else None
        except:
            data = None

    if data and "time" in data and len(data["time"]) > 0:
        return int(data["time"][-1])
    return 0


def print_performance_summary(sim_time_us: int, wall_time: float) -> None:
    """Print simulation performance summary."""
    if wall_time > 0 and sim_time_us > 0:
        speed_factor = sim_time_us / wall_time / 1e6  # sim_seconds / real_seconds
        print(
            f"Simulated {sim_time_us:,} µs ({sim_time_us / 1e3:.2f} ms) "
            f"in {wall_time:.2f} s → {speed_factor:.1f}× realtime."
        )

        sim_time_s = sim_time_us / 1_000_000.0
        wall_time_per_sim_time = wall_time / sim_time_s
        print(
            f"Performance: {wall_time_per_sim_time:.3f} wall-clock seconds per simulated second."
        )
    else:
        print(f"Simulation completed in {wall_time:.2f} s")


def load_simulation_data(log_data: Any, logger_config: LoggerConfig) -> Optional[Any]:
    """Load and return simulation data for plotting."""
    if logger_config["backend"]["type"] == "memory":
        return log_data
    elif logger_config["backend"]["type"] == "numpy" and isinstance(log_data, str):
        try:
            data = np.load(log_data)
            print(f"Successfully loaded data from {log_data}")
            return data
        except Exception as e:
            print(f"Error loading .npz file {log_data}: {e}")
            return None
    else:
        print("No valid data available for plotting.")
        return None


def plot_simulation_results(data: Any, control_mode: str) -> None:
    """Create comprehensive plots of simulation results."""
    import matplotlib.pyplot as plt

    # Validate data
    if not data or "time" not in data or len(data["time"]) == 0:
        print("No valid data available for plotting.")
        return

    t_ms = np.array(data["time"]) / 1000.0
    target_unit = "µm" if control_mode == "position" else "µm/s"

    fig, axes = plt.subplots(7, 1, sharex=True, figsize=(10, 16))

    # Position the plot window in the center of the screen
    try:
        mngr = fig.canvas.manager
        # Try different backends
        if hasattr(mngr, "window"):
            if hasattr(mngr.window, "wm_geometry"):
                # Tkinter backend
                mngr.window.wm_geometry(
                    "+100+50"
                )  # x_offset=100, y_offset=50 from top-left
            elif hasattr(mngr.window, "setGeometry"):
                # Qt backend
                mngr.window.setGeometry(100, 50, 1000, 800)  # x, y, width, height
    except:
        # If positioning fails, just continue without it
        pass

    # 1. Electrical signals with 1ms moving average for voltage
    ax_voltage = axes[0]  # Left y-axis for voltage
    ax_current = ax_voltage.twinx()  # Right y-axis for current

    if "current" in data:
        ax_current.plot(
            t_ms, data["current"], label="Current [A]", color="red", alpha=0.4
        )
    if "voltage" in data:
        voltage = np.array(data["voltage"])
        # Plot raw voltage first (so it appears behind)
        ax_voltage.plot(t_ms, voltage, label="Voltage [V]", color="blue", alpha=0.8)

        # Calculate 1ms moving average for voltage
        # Find window size for 1ms (assuming roughly uniform time steps)
        if len(t_ms) > 1:
            dt_avg = np.mean(np.diff(t_ms))  # Average time step in ms
            window_size = max(1, int(1.0 / dt_avg))  # Points in 1ms window

            # Apply moving average using convolution
            if window_size > 1 and len(voltage) >= window_size:
                voltage_avg = np.convolve(
                    voltage, np.ones(window_size) / window_size, mode="same"
                )
                # Plot 1ms average AFTER raw voltage (so it appears on top/in front)
                ax_voltage.plot(
                    t_ms,
                    voltage_avg,
                    label="Voltage 1ms avg [V]",
                    color="darkblue",
                    linewidth=3,
                    zorder=10,  # Higher zorder ensures it's drawn on top
                )

    # Set labels and colors for dual axes
    ax_voltage.set_ylabel("Voltage [V]", color="blue")
    ax_current.set_ylabel("Current [A]", color="red")
    ax_current.tick_params(axis="y", labelcolor="red")

    # Combine legends from both axes
    lines_voltage, labels_voltage = ax_voltage.get_legend_handles_labels()
    lines_current, labels_current = ax_current.get_legend_handles_labels()
    ax_voltage.legend(
        lines_voltage + lines_current, labels_voltage + labels_current, loc="upper left"
    )

    ax_voltage.grid(True, alpha=0.3)

    # 2. Positions
    if "wire_position" in data:
        axes[1].plot(t_ms, data["wire_position"], label="Wire pos", color="blue")
    if "workpiece_position" in data:
        axes[1].plot(
            t_ms, data["workpiece_position"], label="Workpiece pos", color="orange"
        )
    axes[1].set_ylabel("Position [µm]")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    # 3. Wire velocity
    if "wire_velocity" in data:
        axes[2].plot(t_ms, data["wire_velocity"], label="Wire velocity", color="green")
    axes[2].set_ylabel("Velocity [µm/s]")
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)

    # 4. Gap and control signal
    if "workpiece_position" in data and "wire_position" in data:
        gap = np.array(data["workpiece_position"]) - np.array(data["wire_position"])
        axes[3].plot(t_ms, gap, label="Gap", color="blue", linewidth=2)
    if "target_delta" in data:
        axes[3].plot(
            t_ms,
            data["target_delta"],
            label=f"Target delta [{target_unit}]",
            color="red",
            linestyle="--",
            alpha=0.7,
        )
    axes[3].axhline(y=17.0, color="k", linestyle=":", alpha=0.5, label="Desired gap")
    axes[3].set_ylabel(f"Gap [µm] / Target [{target_unit}]")
    axes[3].legend()
    axes[3].grid(True, alpha=0.3)

    # 5. Wire temperature
    if "wire_average_temperature" in data:
        temp_celsius = np.array(data["wire_average_temperature"]) - 273.15
        axes[4].plot(
            t_ms, temp_celsius, label="Avg Wire Temp (Work Zone)", color="purple"
        )
    elif "wire_temperature" in data:
        # Compute average temperature from full field if needed
        print("📊 Computing zone mean temperature from full temperature field...")
        # This would require accessing the wire module to get zone boundaries
        # For now, just skip or compute simple mean
        temp_celsius = np.array([np.mean(T) for T in data["wire_temperature"]]) - 273.15
        axes[4].plot(
            t_ms, temp_celsius, label="Avg Wire Temp (computed)", color="purple"
        )
    axes[4].set_ylabel("Temperature [°C]")
    axes[4].legend()
    axes[4].grid(True, alpha=0.3)

    # 6. Dielectric flow condition and debris concentration
    ax_debris = axes[5]  # Left y-axis for debris concentration
    ax_flow = ax_debris.twinx()  # Right y-axis for flow condition

    if "debris_concentration" in data:
        ax_debris.plot(
            t_ms,
            data["debris_concentration"],
            label="Debris Concentration",
            color="brown",
        )
    if "flow_rate" in data:
        # flow_rate is now dimensionless (0-1)
        ax_flow.plot(t_ms, data["flow_rate"], label="Flow Condition", color="cyan")

    ax_debris.set_ylabel("Debris Concentration", color="brown")
    ax_flow.set_ylabel("Flow Condition (0-1)", color="cyan")
    ax_flow.tick_params(axis="y", labelcolor="cyan")
    ax_flow.set_ylim(0, 1.1)  # Set fixed range for flow condition

    # Combine legends from both axes
    lines_debris, labels_debris = ax_debris.get_legend_handles_labels()
    lines_flow, labels_flow = ax_flow.get_legend_handles_labels()
    ax_debris.legend(
        lines_debris + lines_flow, labels_debris + labels_flow, loc="upper left"
    )
    ax_debris.grid(True, alpha=0.3)

    # 7. Short circuit status
    if "is_short_circuit" in data:
        # Convert boolean to numeric for plotting
        short_circuit_numeric = np.array(data["is_short_circuit"]).astype(int)
        axes[6].plot(
            t_ms, short_circuit_numeric, label="Short Circuit", color="red", linewidth=2
        )
        axes[6].fill_between(t_ms, 0, short_circuit_numeric, alpha=0.3, color="red")
    axes[6].set_ylabel("Short Circuit")
    axes[6].set_xlabel("Time [ms]")
    axes[6].set_ylim(-0.1, 1.1)  # Give some padding around 0 and 1
    axes[6].set_yticks([0, 1])
    axes[6].set_yticklabels(["No", "Yes"])
    axes[6].legend()
    axes[6].grid(True, alpha=0.3)

    # Calculate and display spark count in last 200ms
    if "current" in data and len(data["current"]) > 0:
        current = np.array(data["current"])
        # Find indices for last 200ms
        last_200ms_mask = t_ms >= (t_ms[-1] - 200.0)
        current_last_200ms = current[last_200ms_mask]

        # Count sparks and short pulses without double counting
        # NOTE: Sparks = current pulses NOT during short circuits
        #       Short pulses = current pulses DURING short circuits
        spark_threshold = 0.1  # A

        if "is_short_circuit" in data:
            # Count short circuits in last 200ms if available
            short_circuit_last_200ms = np.array(data["is_short_circuit"])[
                last_200ms_mask
            ]

            # Count short circuit pulses: current pulses that occurred during short circuit
            # This gives us the number of actual current pulses delivered during shorts,
            # not just the total time spent in short circuit state
            short_above_threshold = (
                current_last_200ms > spark_threshold
            ) & short_circuit_last_200ms
            short_pulse_count = np.sum(np.diff(short_above_threshold.astype(int)) > 0)

            # Count normal sparks: current pulses that occurred when NOT in short circuit
            normal_above_threshold = (current_last_200ms > spark_threshold) & (
                ~short_circuit_last_200ms
            )
            spark_count = np.sum(np.diff(normal_above_threshold.astype(int)) > 0)

            display_text = (
                f"Last 200ms - Sparks: {spark_count}, Short pulses: {short_pulse_count}"
            )
        else:
            # If no short circuit data, count all current pulses as sparks (fallback)
            above_threshold = current_last_200ms > spark_threshold
            spark_count = np.sum(np.diff(above_threshold.astype(int)) > 0)
            display_text = f"Last 200ms - Sparks: {spark_count}"

        # Add text annotation to the plot
        fig.text(
            0.02,
            0.02,
            display_text,
            fontsize=12,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightblue"),
        )

    plt.suptitle(
        f"Wire-EDM Smoke Test ({control_mode.capitalize()} Control)",
        fontsize=14,
        fontweight="bold",
    )
    plt.tight_layout()
    plt.show()


def plot_crater_histogram(env: WireEDMEnv) -> None:
    """Create histogram of crater volumes generated during simulation."""
    import matplotlib.pyplot as plt

    # Get crater statistics from the material removal module
    crater_stats = env.material.get_crater_statistics()

    if crater_stats["total_craters"] == 0:
        print("No craters were generated during the simulation.")
        return

    volumes_um3 = crater_stats["volumes_um3"]

    # Create histogram
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Position the plot window
    try:
        mngr = fig.canvas.manager
        if hasattr(mngr, "window"):
            if hasattr(mngr.window, "wm_geometry"):
                mngr.window.wm_geometry("+150+100")
            elif hasattr(mngr.window, "setGeometry"):
                mngr.window.setGeometry(150, 100, 1400, 600)
    except:
        pass

    # Histogram 1: Linear scale
    n_bins = min(50, max(10, len(volumes_um3) // 10))  # Adaptive bin count
    ax1.hist(volumes_um3, bins=n_bins, alpha=0.7, color="skyblue", edgecolor="black")
    ax1.set_xlabel("Crater Volume [μm³]")
    ax1.set_ylabel("Frequency")
    ax1.set_title("Crater Volume Distribution (Linear Scale)")
    ax1.grid(True, alpha=0.3)

    # Add statistics text
    stats_text = (
        f"Total craters: {crater_stats['total_craters']:,}\n"
        f"Mean: {crater_stats['mean_volume_um3']:.1f} μm³\n"
        f"Std: {crater_stats['std_volume_um3']:.1f} μm³\n"
        f"Min: {crater_stats['min_volume_um3']:.1f} μm³\n"
        f"Max: {crater_stats['max_volume_um3']:.1f} μm³"
    )
    ax1.text(
        0.02,
        0.98,
        stats_text,
        transform=ax1.transAxes,
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray"),
    )

    # Histogram 2: Log scale (if there's enough range)
    if crater_stats["max_volume_um3"] / crater_stats["min_volume_um3"] > 10:
        # Use log bins for better visualization of wide distributions
        log_bins = np.logspace(
            np.log10(max(1e-3, crater_stats["min_volume_um3"])),
            np.log10(crater_stats["max_volume_um3"]),
            n_bins,
        )
        ax2.hist(
            volumes_um3, bins=log_bins, alpha=0.7, color="lightcoral", edgecolor="black"
        )
        ax2.set_xscale("log")
        ax2.set_xlabel("Crater Volume [μm³] (log scale)")
        ax2.set_ylabel("Frequency")
        ax2.set_title("Crater Volume Distribution (Log Scale)")
    else:
        # If range is small, show cumulative distribution instead
        sorted_volumes = np.sort(volumes_um3)
        cumulative = np.arange(1, len(sorted_volumes) + 1) / len(sorted_volumes)
        ax2.plot(sorted_volumes, cumulative, "r-", linewidth=2)
        ax2.set_xlabel("Crater Volume [μm³]")
        ax2.set_ylabel("Cumulative Probability")
        ax2.set_title("Crater Volume Cumulative Distribution")

    ax2.grid(True, alpha=0.3)

    plt.suptitle("Crater Volume Analysis", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.show()


def main():
    """Main entry point with clean CLI handling."""
    parser = argparse.ArgumentParser(description="Wire-EDM smoke test")
    parser.add_argument(
        "--steps", type=int, default=200_000, help="µs to simulate (default: 200,000)"
    )
    parser.add_argument("--plot", action="store_true", help="Show plots at the end")
    parser.add_argument(
        "--verbose", action="store_true", help="Print verbose output during simulation"
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["position", "velocity"],
        default="position",
        help="Mechanics control mode (default: position)",
    )
    parser.add_argument(
        "--log-strategy",
        type=str,
        choices=["full_field", "zone_mean", "both"],
        default="full_field",
        help="Temperature logging strategy (default: full_field)",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Disable saving log files (keep only minimal data in memory)",
    )
    parser.add_argument(
        "--controller",
        type=str,
        choices=["gap", "voltage"],
        default="gap",
        help="Control strategy: 'gap' for constant gap control, 'voltage' for average voltage control (default: gap)",
    )
    parser.add_argument(
        "--target-voltage",
        type=float,
        default=30.0,
        help="Target average voltage for voltage controller in V (default: 30.0)",
    )

    args = parser.parse_args()

    # Setup
    logger_config = setup_logger(
        args.mode,
        log_to_file=not args.no_log,
        log_strategy=args.log_strategy,
        enable_plotting=args.plot,
    )
    env = initialize_environment(args.mode, seed=0, log_strategy=args.log_strategy)

    # Run simulation
    log_data, wall_time, sim_time_us = run_simulation(
        env,
        args.steps,
        args.verbose,
        logger_config,
        args.controller,
        args.target_voltage,
    )

    # Print average speed over last 100ms
    data = load_simulation_data(log_data, logger_config)
    if (
        data is not None
        and "time" in data
        and "wire_velocity" in data
        and len(data["time"]) > 0
    ):
        t_ms = np.array(data["time"]) / 1000.0  # Convert µs to ms
        wire_velocity = np.array(data["wire_velocity"])  # µm/s

        # Find data from last 100ms
        last_100ms_mask = t_ms >= (t_ms[-1] - 100.0)
        if np.any(last_100ms_mask):
            velocity_last_100ms = wire_velocity[last_100ms_mask]
            avg_velocity_um_s = np.mean(velocity_last_100ms)
            # Convert µm/s to mm/min: 1 µm/s = 0.06 mm/min
            avg_velocity_mm_min = avg_velocity_um_s * 0.06
            print(
                f"\n📈 Average wire speed (last 100ms): {avg_velocity_mm_min:.2f} mm/min ({avg_velocity_um_s:.1f} µm/s)"
            )
        else:
            print(f"\n📈 Insufficient data for last 100ms speed calculation")

    # Plotting
    if args.plot:
        print(f"\n📊 Starting plotting phase...")
        if data is None:  # Load data again if not already loaded
            data = load_simulation_data(log_data, logger_config)
        if data is not None:
            plot_simulation_results(data, args.mode)
            # Show crater histogram after main plot is closed
            plot_crater_histogram(env)


if __name__ == "__main__":
    main()
