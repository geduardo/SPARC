#!/usr/bin/env python3
"""
Track individual wire segment temperatures as they travel from inlet to outlet.

This script tracks N wire segments spaced out in time as they move through the wire,
recording their temperature history and plotting temp vs time for each segment.

Strategy:
1. Wait for thermal steady state (1 second) before starting to track segments
2. Track segments that enter the wire at regular intervals (e.g., every 100ms)
3. This ensures we get diverse temperature profiles across different time periods
4. Each tracked segment is followed from inlet to outlet to capture its full thermal journey

The time-spaced sampling avoids the issue of tracking consecutive segments that are
too similar in their thermal histories.
"""

import numpy as np
import matplotlib.pyplot as plt
from collections import deque
from datetime import datetime
from wedm import WireEDMEnv, EnvironmentConfig
from wedm.utils.logger import SimulationLogger


def create_voltage_controller(target_voltage: float = 47.0):
    """Create PI voltage controller."""
    integral_error = 0.0
    Kp = 0.05
    Ki = 0.1

    def controller(env, voltage_history: list = None):
        nonlocal integral_error

        if voltage_history and len(voltage_history) > 0:
            avg_voltage = float(np.mean(tuple(voltage_history)))
        else:
            avg_voltage = env.state.voltage

        error = target_voltage - avg_voltage
        integral_error += error
        integral_error = np.clip(integral_error, -100.0, 100.0)

        pi_output = -(Kp * error + Ki * integral_error * 0.001)

        if env.mechanics.control_mode == "position":
            delta = pi_output
            delta = np.clip(delta, -5.0, 5.0)
        else:
            delta = pi_output * 100.0
            delta = np.clip(delta, -1000.0, 1000.0)

        return {
            "servo": np.array([delta], dtype=np.float32),
            "generator_control": {
                "target_voltage": np.array([80.0], dtype=np.float32),
                "current_mode": np.array([17], dtype=np.int32),
                "ON_time": np.array([2.0], dtype=np.float32),
                "OFF_time": np.array([18.0], dtype=np.float32),
            },
        }

    return controller


class SegmentTracker:
    """Efficiently track N segments spread out in time as they flow through the wire."""

    def __init__(self, wire_module, n_segments_to_track=10, sampling_interval_us=50000):
        """
        Initialize segment tracker.

        Args:
            wire_module: The WireModule instance
            n_segments_to_track: Number of segments to track (default: 10)
            sampling_interval_us: Time interval between tracking new segments in microseconds (default: 50ms)
        """
        self.wire_module = wire_module
        self.n_segments_to_track = n_segments_to_track
        self.sampling_interval_us = sampling_interval_us
        self.total_wire_length = wire_module.total_L  # mm
        self.segment_length = wire_module.segment_len_mm  # mm

        # Storage for segment histories
        # Each tracked segment has a list of (time_us, temperature_K) tuples
        self.active_segments = []  # Segments currently in the wire
        self.completed_segments = []  # Segments that have completed their journey

        # Counter for total segments that have exited
        self.segments_exited = 0

        # Track the position of the outlet segment (last segment)
        self.outlet_index = wire_module.n_segments - 1

        # Previous position to detect when a segment exits
        self.prev_outlet_position = None
        self.prev_positions = None  # Track previous positions to detect rollover

        # Track when we last started tracking a segment
        self.last_tracked_time_us = None

    def update(self, time_us, wire_module):
        """Update tracking for current timestep."""
        # Get current segment positions and temperatures
        positions = wire_module._y_start_mm  # NumPy array of positions
        temperatures = wire_module._temperature  # NumPy array of temperatures

        # Detect rollover: when positions[0] suddenly becomes very small
        # After a rollover, the wire module shifts all segments and creates a new one at index 0
        # with a small remainder position
        if self.prev_positions is not None:
            # Check if position[0] decreased significantly (rollover happened)
            # A rollover is detected when pos[0] < prev_pos[0] by a large amount
            position_drop = self.prev_positions[0] - positions[0]

            if position_drop > (self.segment_length * 0.5):
                # Rollover detected - a segment just exited and a new one entered
                self.segments_exited += 1

                # Start tracking the segment that just entered (now at index 0)
                # Only if we haven't completed tracking yet AND enough time has passed
                should_track = len(self.completed_segments) < self.n_segments_to_track

                # Check if enough time has passed since last tracked segment
                if self.last_tracked_time_us is not None:
                    time_since_last_track = time_us - self.last_tracked_time_us
                    should_track = should_track and (
                        time_since_last_track >= self.sampling_interval_us
                    )

                if should_track:
                    # Create new tracked segment history
                    new_segment = {
                        "history": [(time_us, temperatures[0])],
                        "segment_number": self.segments_exited,
                        "inlet_time_us": time_us,
                    }
                    self.active_segments.append(new_segment)
                    self.last_tracked_time_us = time_us

        # Update all active tracked segments
        # We track them by their position in the array
        # The newest segment (most recently entered) is at position 0
        # As segments move through, they stay at their index until rollover

        still_active = []
        for tracked_seg in self.active_segments:
            # Calculate how many rollovers have happened since this segment entered
            rollovers_since_entry = self.segments_exited - tracked_seg["segment_number"]

            # Current index of this segment (0 = inlet/newest, increases toward outlet)
            current_index = rollovers_since_entry

            # Check if segment is still in the wire
            if 0 <= current_index < wire_module.n_segments:
                # Segment is still in the wire, record its temperature
                temp = temperatures[current_index]
                tracked_seg["history"].append((time_us, temp))
                still_active.append(tracked_seg)
            elif current_index >= wire_module.n_segments:
                # Segment has exited, record final state and mark as complete
                tracked_seg["outlet_time_us"] = time_us
                tracked_seg["complete"] = True
                self.completed_segments.append(tracked_seg)
                # Don't add to still_active - it's completed

        # Update active segments list
        self.active_segments = still_active

        # Store current positions for next comparison
        self.prev_positions = (
            positions.copy() if self.prev_positions is not None else positions.copy()
        )

    def get_completed_segments(self):
        """Return all segments that have completed their journey."""
        return self.completed_segments

    def get_last_n_completed(self, n=10):
        """Get the last N completed segments."""
        return (
            self.completed_segments[-n:]
            if len(self.completed_segments) > n
            else self.completed_segments
        )


def main():
    print("=== Segment Temperature Tracking ===")
    print("Running 100,000 microsecond simulation...\n")

    # Create environment with custom wire parameters
    from wedm.modules.wire import WireModuleParameters

    # Calculate segment length to get exactly 200 segments
    # Total wire length = buffer_bottom + workpiece_height + buffer_top
    # Default buffers are 30mm each, workpiece is 100mm -> total 160mm
    # segment_len = 160mm / 200 = 0.8mm
    wire_params = WireModuleParameters(
        segment_len=0.5,  # mm
        moving_segments=True,
    )

    config = EnvironmentConfig(workpiece_height=30.0)
    env = WireEDMEnv(config=config)

    # Override wire module with custom parameters
    from wedm.modules.wire import WireModule

    env.wire = WireModule(env, parameters=wire_params)

    # Disable wire breaking for this tracking script
    # Set wire tension to 0 so no damage accumulates (damage model requires stress)
    env.wire.params.wire_tension_force = 0.0
    env.wire.wire_stress_mpa = 0.0
    print("Wire breaking disabled for temperature tracking (tension set to 0).")

    # Initialize controller
    target_voltage = 70.0
    controller = create_voltage_controller(target_voltage)

    # Voltage history tracking
    voltage_history: deque[float] = deque()
    time_history: deque[int] = deque()

    # Reset environment
    obs, info = env.reset()
    print(f"Environment initialized.")
    print(f"Wire segments: {env.wire.n_segments}")
    print(f"Total wire length: {env.wire.total_L:.2f} mm")
    print(f"Segment length: {env.wire.segment_len_mm:.2f} mm")
    print(f"Wire velocity: {env.state.wire_unwinding_velocity:.4f} um/us\n")

    # Calculate expected transit time
    # Wire velocity: 0.2 µm/µs, Wire length: 85 mm = 85,000 µm
    wire_velocity_um_per_us = env.state.wire_unwinding_velocity  # µm/µs
    expected_transit_time_us = (
        env.wire.total_L * 1000
    ) / wire_velocity_um_per_us  # Convert mm to µm
    expected_transit_time_ms = expected_transit_time_us / 1000.0
    print(
        f"Expected segment transit time: {expected_transit_time_us:.1f} µs ({expected_transit_time_ms:.1f} ms)"
    )
    print(f"Expected transit time: {expected_transit_time_ms/1000:.2f} seconds\n")

    # Simulation parameters
    # Strategy: Wait for thermal steady state, then track 10 segments spaced out in time

    # Time to wait for steady state (microseconds)
    steady_state_wait_us = 1000000  # 1 second = 1,000,000 microseconds

    # Sampling interval: time between tracking new segments (microseconds)
    sampling_interval_us = 100000  # 100ms = 100,000 microseconds

    # Calculate total simulation time needed:
    # = steady_state_wait + (9 * sampling_interval) + transit_time + buffer
    # We need 9 intervals for 10 segments (first segment at t=0 of tracking)
    n_segments_to_track = 5
    buffer_time_us = 100000  # Extra 100ms buffer

    max_sim_time_us = (
        steady_state_wait_us
        + ((n_segments_to_track - 1) * sampling_interval_us)
        + expected_transit_time_us
        + buffer_time_us
    )

    # Start tracking after steady state wait
    tracking_start_time_us = steady_state_wait_us

    print(f"\n{'='*70}")
    print(f"TRACKING STRATEGY:")
    print(f"{'='*70}")
    print(
        f"Steady state wait time: {steady_state_wait_us/1000:.1f} ms ({steady_state_wait_us/1e6:.1f} s)"
    )
    print(
        f"Sampling interval: {sampling_interval_us/1000:.1f} ms ({sampling_interval_us/1e6:.3f} s)"
    )
    print(f"Segments to track: {n_segments_to_track}")
    print(
        f"Tracking duration: {(n_segments_to_track - 1) * sampling_interval_us/1000:.1f} ms"
    )
    print(
        f"Start tracking at: {tracking_start_time_us/1000:.1f} ms ({tracking_start_time_us/1e6:.1f} s)"
    )
    print(
        f"Total simulation time: {max_sim_time_us/1000:.1f} ms ({max_sim_time_us/1e6:.2f} s)"
    )
    print(f"{'='*70}\n")

    # Initialize segment tracker with time-spaced sampling
    tracker = SegmentTracker(
        env.wire,
        n_segments_to_track=n_segments_to_track,
        sampling_interval_us=sampling_interval_us,
    )
    tracker_active = False  # Will activate at the calculated time

    # Initialize action
    action = controller(env, None)

    # Run simulation
    step_count = 0
    control_step_count = 0

    # Progress tracking
    import time

    start_time = time.time()
    last_progress_time = start_time

    print("Starting simulation...")
    print(f"Target: {max_sim_time_us:,} microseconds ({max_sim_time_us/1000:.1f} ms)")
    print(f"Waiting for steady state before tracking...\n")

    # Run simulation loop until we reach max simulation time
    while True:
        obs, reward, terminated, truncated, info = env.step(action)

        # Track voltage history
        current_voltage = env.state.voltage
        voltage_history.append(current_voltage)
        time_history.append(env.state.time)

        # Keep only last 1ms
        cutoff_time = env.state.time - 1000.0
        while time_history and time_history[0] < cutoff_time:
            voltage_history.popleft()
            time_history.popleft()

        # Increment simulation step counter
        step_count += 1

        # Check if tracker should be activated (every microsecond)
        current_sim_time_us = env.state.time  # Already in microseconds
        if not tracker_active and current_sim_time_us >= tracking_start_time_us:
            tracker_active = True
            print(f"\n{'='*70}")
            print(
                f">>> TRACKING ACTIVATED at {current_sim_time_us/1000:.1f} ms ({current_sim_time_us/1e6:.1f} s) <<<"
            )
            print(f"System has reached thermal steady state.")
            print(f"Will track 1 segment every {sampling_interval_us/1000:.1f} ms")
            print(f"{'='*70}\n")

        # Update segment tracker every microsecond when active
        # Track how many segments we had before
        prev_active_count = len(tracker.active_segments) if tracker_active else 0
        prev_completed_count = len(tracker.completed_segments) if tracker_active else 0

        if tracker_active:
            tracker.update(env.state.time, env.wire)

            # Check if a new segment started being tracked
            new_active_count = len(tracker.active_segments)
            new_completed_count = len(tracker.completed_segments)

            if new_active_count > prev_active_count:
                print(
                    f"  → Segment #{tracker.segments_exited} entered wire - now tracking (at t={current_sim_time_us/1000:.1f} ms)"
                )

            if new_completed_count > prev_completed_count:
                print(
                    f"  ✓ Segment completed full transit! ({new_completed_count}/{n_segments_to_track} complete)"
                )

        # Update action on control steps
        if info.get("control_step", False):
            control_step_count += 1
            action = controller(env, list(voltage_history))

        # Progress update every 10,000 simulation steps
        if step_count % 10000 == 0:
            completed = len(tracker.get_completed_segments()) if tracker_active else 0
            active = len(tracker.active_segments) if tracker_active else 0
            sim_time_us = env.state.time
            sim_time_ms = sim_time_us / 1000.0
            sim_time_s = sim_time_us / 1e6  # µs to seconds

            # Calculate real time metrics
            current_real_time = time.time()
            elapsed_real_time = current_real_time - start_time
            steps_per_second = (
                step_count / elapsed_real_time if elapsed_real_time > 0 else 0
            )
            remaining_steps = max_sim_time_us - step_count
            estimated_remaining_time = (
                remaining_steps / steps_per_second if steps_per_second > 0 else 0
            )

            # Progress percentage
            progress_pct = (step_count / max_sim_time_us) * 100

            # Tracking status
            if not tracker_active:
                tracking_status = "Steady-state warmup"
                segment_info = f"starts at {tracking_start_time_us/1000:.0f}ms"
            else:
                tracking_status = "TRACKING"
                segment_info = (
                    f"Active: {active}, Complete: {completed}/{n_segments_to_track}"
                )

            print(
                f"Progress: {progress_pct:5.1f}% | "
                f"SimTime: {sim_time_ms:.0f}ms ({sim_time_s:.2f}s) | "
                f"[{tracking_status}] {segment_info} | "
                f"Speed: {steps_per_second:.0f} µs/s | "
                f"ETA: {estimated_remaining_time:.1f}s"
            )

        # Stop after reaching max simulation time
        if env.state.time >= max_sim_time_us:
            print(
                f"\n✓ Reached {max_sim_time_us:,} microseconds ({max_sim_time_us/1000:.1f} ms)"
            )
            break

        if terminated:
            print(f"\nSimulation terminated: {info}")
            break

    # Final statistics
    total_real_time = time.time() - start_time
    avg_steps_per_second = step_count / total_real_time if total_real_time > 0 else 0
    final_sim_time_us = env.state.time

    print(f"\n{'='*70}")
    print(f"[ok] Simulation Complete!")
    print(f"{'='*70}")
    print(f"Total simulation steps: {step_count:,} ({final_sim_time_us:,} us)")
    print(f"Total control steps: {control_step_count:,}")
    print(
        f"Total real time elapsed: {total_real_time:.1f} seconds ({total_real_time/60:.2f} minutes)"
    )
    print(f"Average speed: {avg_steps_per_second:.0f} simulation steps/second")
    print(f"Total segments exited: {tracker.segments_exited}")
    print(f"Completed tracked segments: {len(tracker.get_completed_segments())}")
    print(f"{'='*70}\n")

    # Get all completed segments
    completed_segments = tracker.get_completed_segments()
    print(
        f"\nPlotting {len(completed_segments)} tracked segments (sampled every {sampling_interval_us/1000:.0f}ms)..."
    )

    # Save heating curves to CSV files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if len(completed_segments) > 0:
        import csv
        import os

        # Create output directory if it doesn't exist
        csv_dir = "heating_curves"
        os.makedirs(csv_dir, exist_ok=True)

        print(f"\nSaving heating curves to CSV files in '{csv_dir}/'...")

        for idx, segment in enumerate(completed_segments):
            # Extract time and temperature data
            times = [t for t, _ in segment["history"]]
            temps = [T for _, T in segment["history"]]

            # Convert temperatures from K to °C
            temps_celsius = [T - 273.15 for T in temps]

            # Calculate relative time (time since segment entered inlet) in milliseconds
            inlet_time_us = segment["inlet_time_us"]
            relative_times_ms = [(t - inlet_time_us) / 1000.0 for t in times]

            # Create CSV filename
            csv_filename = os.path.join(csv_dir, f"segment_{idx+1:02d}_{timestamp}.csv")

            # Get geometry from environment
            total_wire_length = env.wire.total_L  # mm
            buffer_bottom = env.wire.params.buffer_len_bottom  # mm
            buffer_top = env.wire.params.buffer_len_top  # mm
            workpiece_height = env.config.workpiece_height  # mm
            contact_offset_bottom = env.wire.params.contact_offset_bottom  # mm
            contact_offset_top = env.wire.params.contact_offset_top  # mm

            # Calculate positions
            pos_inlet = 0.0
            pos_contact_lower = buffer_bottom - contact_offset_bottom
            pos_workpiece_start = buffer_bottom
            pos_workpiece_end = buffer_bottom + workpiece_height
            pos_contact_upper = buffer_bottom + workpiece_height + contact_offset_top
            pos_outlet = total_wire_length

            # Write CSV file
            with open(csv_filename, "w", newline="") as csvfile:
                writer = csv.writer(csvfile)
                # Write header with metadata
                writer.writerow(["# Segment Temperature History"])
                writer.writerow([f'# Segment Number: {segment["segment_number"]}'])
                writer.writerow([f'# Inlet Time (us): {segment["inlet_time_us"]}'])
                writer.writerow(
                    [f'# Outlet Time (us): {segment.get("outlet_time_us", "N/A")}']
                )
                writer.writerow([f"# Transit Time (ms): {relative_times_ms[-1]:.2f}"])
                writer.writerow(["# "])
                # Write geometry metadata
                writer.writerow(["# === Geometry (mm) ==="])
                writer.writerow([f"# Total Wire Length (mm): {total_wire_length:.2f}"])
                writer.writerow([f"# Workpiece Height (mm): {workpiece_height:.2f}"])
                writer.writerow([f"# Buffer Bottom (mm): {buffer_bottom:.2f}"])
                writer.writerow([f"# Buffer Top (mm): {buffer_top:.2f}"])
                writer.writerow([f"# Pos Inlet (mm): {pos_inlet:.2f}"])
                writer.writerow([f"# Pos Contact Lower (mm): {pos_contact_lower:.2f}"])
                writer.writerow(
                    [f"# Pos Workpiece Start (mm): {pos_workpiece_start:.2f}"]
                )
                writer.writerow([f"# Pos Workpiece End (mm): {pos_workpiece_end:.2f}"])
                writer.writerow([f"# Pos Contact Upper (mm): {pos_contact_upper:.2f}"])
                writer.writerow([f"# Pos Outlet (mm): {pos_outlet:.2f}"])
                writer.writerow(["# "])
                # Write column headers
                writer.writerow(
                    [
                        "Time_Since_Inlet_ms",
                        "Temperature_Celsius",
                        "Absolute_Time_us",
                        "Temperature_Kelvin",
                    ]
                )
                # Write data rows
                for rel_t, temp_c, abs_t, temp_k in zip(
                    relative_times_ms, temps_celsius, times, temps
                ):
                    writer.writerow(
                        [
                            f"{rel_t:.6f}",
                            f"{temp_c:.4f}",
                            f"{abs_t:.1f}",
                            f"{temp_k:.4f}",
                        ]
                    )

            print(f"  [ok] Saved: {csv_filename}")

        print(f"\n[ok] All {len(completed_segments)} heating curves saved to CSV!")

    # Plot each segment's temperature history
    if len(completed_segments) > 0:
        # Create figure with subplots for each segment
        n_segments = len(completed_segments)
        fig, axes = plt.subplots(n_segments, 1, figsize=(12, 3 * n_segments))

        # Handle single subplot case
        if n_segments == 1:
            axes = [axes]

        for idx, segment in enumerate(completed_segments):
            ax = axes[idx]

            # Extract time and temperature data
            times = [t for t, _ in segment["history"]]
            temps = [T for _, T in segment["history"]]

            # Convert temperatures from K to °C
            temps_celsius = [T - 273.15 for T in temps]

            # Calculate relative time (time since segment entered inlet) in milliseconds
            inlet_time_us = segment["inlet_time_us"]
            relative_times_ms = [(t - inlet_time_us) / 1000.0 for t in times]

            # Plot
            ax.plot(relative_times_ms, temps_celsius, linewidth=1.5, color="steelblue")
            ax.set_xlabel("Time since inlet entry (ms)", fontsize=10)
            ax.set_ylabel("Temperature (°C)", fontsize=10)
            # ax.set_title(
            #     f'Segment #{segment["segment_number"]} Temperature Evolution',
            #     fontsize=11,
            #     fontweight="bold",
            # )
            ax.grid(True, alpha=0.3)

            # Add statistics
            max_temp = max(temps_celsius)
            avg_temp = np.mean(temps_celsius)
            transit_time_ms = relative_times_ms[-1]

            textstr = f"Transit time: {transit_time_ms:.1f} ms\nMax temp: {max_temp:.1f}°C\nAvg temp: {avg_temp:.1f}°C"
            ax.text(
                0.02,
                0.98,
                textstr,
                transform=ax.transAxes,
                fontsize=9,
                verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
            )

        plt.tight_layout()

        # Save figure
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"segment_temperature_tracking_{timestamp}.png"
        plt.savefig(filename, dpi=150, bbox_inches="tight")
        print(f"\n[ok] Figure saved: {filename}")

        plt.show()
    else:
        print("\nWarning: No completed segments to plot!")
        print(
            "The simulation may need to run longer for segments to complete their journey."
        )


if __name__ == "__main__":
    main()
