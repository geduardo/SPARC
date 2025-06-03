#!/usr/bin/env python
# experiments/single_spark_animation.py
"""
Creates an animation showing the evolution of wire temperature after a single spark event.
Records 1ms of simulation time with high-frequency logging to capture thermal dynamics.

Usage:
    python experiments/single_spark_animation.py --save --out single_spark.mp4
    python experiments/single_spark_animation.py  # Just show live animation
"""
from __future__ import annotations

import argparse
import time
import pathlib
from typing import Dict, Any, Tuple, Optional

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from src.wedm.envs import WireEDMEnv
from src.wedm.utils.logger import SimulationLogger, LoggerConfig
from src.wedm.modules.wire import WireModuleParameters


def create_single_spark_controller(
    spark_time_us: float = 50.0,  # Time when spark occurs (µs)
    spark_duration_us: float = 2.0,  # Duration of spark (µs)
    spark_location_mm: float = 25.0,  # Spark location from bottom of workpiece (mm)
    voltage: float = 80.0,  # Spark voltage (V)
    current_mode: int = 13,  # Current mode (maps to specific current levels)
):
    """
    Create a controller that provides generator settings for the single spark experiment.
    The actual spark forcing is handled in the main simulation loop.

    Args:
        spark_time_us: When to trigger the spark (microseconds from start)
        spark_duration_us: How long the spark lasts (microseconds)
        spark_location_mm: Where the spark occurs (mm from workpiece bottom)
        voltage: Generator voltage setting (V)
        current_mode: Generator current mode setting

    Returns:
        Controller function that returns actions to keep wire stationary
    """

    def controller(env: WireEDMEnv) -> Dict[str, Any]:
        """Generate action to keep wire stationary with appropriate generator settings."""
        return {
            "servo": np.array([0.0], dtype=np.float32),  # Keep wire stationary
            "generator_control": {
                "target_voltage": np.array([voltage], dtype=np.float32),
                "current_mode": np.array([current_mode], dtype=np.int32),
                "ON_time": np.array([spark_duration_us], dtype=np.float32),
                "OFF_time": np.array([1000.0], dtype=np.float32),  # Long OFF time
            },
        }

    return controller


def setup_single_spark_logger() -> LoggerConfig:
    """Setup logger for high-frequency wire temperature recording."""
    return {
        "signals_to_log": [
            "time",
            "wire_temperature",  # Full temperature field
            "voltage",
            "current",
            "spark_status",
            "wire_position",
            "workpiece_position",
        ],
        "log_frequency": {"type": "every_step"},  # Log every microsecond
        "backend": {
            "type": "numpy",
            "filepath": "logs/single_spark_temperature.npz",
            "compress": True,
        },
    }


def initialize_single_spark_environment(
    seed: int = 42, plasma_efficiency: Optional[float] = None
) -> WireEDMEnv:
    """Initialize environment optimized for single spark observation."""

    wire_params = WireModuleParameters()
    if plasma_efficiency is not None:
        print(f"💡 Using custom plasma_efficiency: {plasma_efficiency}")
        wire_params.plasma_efficiency = plasma_efficiency

    env = WireEDMEnv(mechanics_control_mode="position", wire_params=wire_params)
    env.reset(seed=seed)

    # Set initial conditions for stable observation
    env.state.workpiece_position = 50.0  # µm - starting position
    env.state.wire_position = (
        40.0  # µm - set to 10µm gap to avoid immediate termination
    )
    env.state.target_position = (
        5000.0  # µm - much larger target to avoid early termination
    )
    env.state.spark_status = [0, None, 0]  # No initial spark
    env.state.dielectric_temperature = 293.15  # Room temperature
    env.state.wire_unwinding_velocity = 0.0  # No wire movement for cleaner observation

    # Initialize wire temperature to room temperature
    if len(env.state.wire_temperature) == 0:
        env.wire.update(env.state)

    # Set all segments to room temperature initially
    env.state.wire_temperature.fill(293.15)  # 20°C in Kelvin

    print(f"🔬 Single spark observation setup:")
    print(f"   Wire segments: {len(env.state.wire_temperature)}")
    print(f"   Wire length: {env.wire.total_L:.1f} mm")
    print(f"   Segment length: {env.wire.params.segment_len:.3f} mm")
    print(
        f"   Initial gap: {env.state.workpiece_position - env.state.wire_position:.1f} µm"
    )

    return env


def run_single_spark_simulation(
    env: WireEDMEnv,
    logger_config: LoggerConfig,
    spark_config: Dict[str, float],
    simulation_duration_us: int = 1000,
) -> Tuple[str, float]:
    """
    Run simulation of single spark event.

    Args:
        env: Initialized environment
        logger_config: Logger configuration
        spark_config: Spark timing and parameters
        simulation_duration_us: Total simulation time in microseconds

    Returns:
        Tuple of (log_file_path, wall_time)
    """
    # Ensure logs directory exists
    log_dir = pathlib.Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger = SimulationLogger(config=logger_config, env_reference=env)
    logger.reset()

    controller = create_single_spark_controller(**spark_config)

    start_time = time.time()

    print(f"🚀 Starting single spark simulation...")
    print(
        f"   Duration: {simulation_duration_us} µs ({simulation_duration_us/1000:.1f} ms)"
    )
    print(f"   Spark at: {spark_config['spark_time_us']} µs")
    print(f"   Spark duration: {spark_config['spark_duration_us']} µs")
    print(
        f"   Spark location: {spark_config['spark_location_mm']} mm from workpiece bottom"
    )

    # Pre-calculate spark location index
    if len(env.state.wire_temperature) == 0:
        env.wire.update(env.state)
        env.state.wire_temperature.fill(293.15)

    # Spark location is from the bottom of the WORKPIECE
    spark_y_m_from_workpiece_bottom = spark_config["spark_location_mm"] / 1000.0  # m

    # Get wire parameters for correct indexing
    # buffer_len_bottom is in mm from WireModuleParameters, segment_len is also in mm
    L_buffer_bottom_m = env.wire.params.buffer_len_bottom / 1000.0  # m
    segment_length_m = env.wire.params.segment_len / 1000.0  # m
    total_wire_segments = len(env.state.wire_temperature)

    # Absolute spark position from the very start of the simulated wire
    absolute_spark_y_m = L_buffer_bottom_m + spark_y_m_from_workpiece_bottom

    spark_location_idx = 0
    if (
        segment_length_m > 1e-9
    ):  # Avoid division by zero if segment_length is tiny or zero
        spark_location_idx = int(absolute_spark_y_m / segment_length_m)

    spark_location_idx = max(0, min(spark_location_idx, total_wire_segments - 1))

    spark_start_time = spark_config["spark_time_us"]
    spark_total_duration = spark_config["spark_duration_us"]

    # Initial log print before loop starts, using env.state
    if 1 <= 10:  # Mimic the first few steps condition for initial state print
        avg_temp = np.mean(env.state.wire_temperature) - 273.15
        max_temp = np.max(env.state.wire_temperature) - 273.15
        spark_on_state = "OFF"  # Spark hasn't started
        voltage_in_state = env.state.voltage if env.state.voltage is not None else 0.0
        current_in_state = env.state.current if env.state.current is not None else 0.0
        print(
            f"   t={0:4d} µs: avg_temp={avg_temp:5.1f}°C, max_temp={max_temp:5.1f}°C, spark={spark_on_state}, V={voltage_in_state:.1f}, I={current_in_state:.1f} (Initial)"
        )

    for step_counter in range(simulation_duration_us):
        current_time_us = step_counter + 1  # 1-indexed time

        action = controller(env)

        if step_counter == 0:
            original_ignition_update = env.ignition.update

            def disabled_ignition_update(state, dt=None):
                pass

            env.ignition.update = disabled_ignition_update

        is_spark_active_this_step = (
            spark_start_time
            <= current_time_us
            < (spark_start_time + spark_total_duration)
        )

        if is_spark_active_this_step:
            # Activate spark: [active=1, location_idx, duration_remaining=1 for this step]
            env.state.spark_status = [1, spark_config["spark_location_mm"], 1]

            # Manually set spark V/I because IgnitionModule is disabled
            OCV = spark_config["voltage"]
            spark_burning_voltage = OCV * 0.3
            env.state.voltage = spark_burning_voltage
            env.state.current = 60.0

            if current_time_us == spark_start_time:
                # spark_location_idx is still useful for verification if WireModule calculates it correctly
                print(
                    f"🔥 Spark FORCED at t={current_time_us}µs, duration={spark_total_duration}µs, loc_cfg={spark_config['spark_location_mm']:.1f}mm (expected_idx={spark_location_idx})"
                )
                print(
                    f"   Applied V={env.state.voltage:.1f}V, I={env.state.current:.1f}A for spark"
                )
        else:
            env.state.spark_status = [0, None, 0]
            env.state.voltage = spark_config["voltage"]
            env.state.current = 0.0

        state_from_step, reward, terminated, truncated, info = env.step(action)

        # Log progress (use env.state as it reflects the true state after all modules run)
        should_print_log = (
            current_time_us % 50 == 0
            or current_time_us <= 10
            or (is_spark_active_this_step and current_time_us == spark_start_time)
            or (current_time_us == (spark_start_time + spark_total_duration))
        )

        if should_print_log and current_time_us > 0:
            # Use env.state for printing the most up-to-date information
            avg_temp = np.mean(env.state.wire_temperature) - 273.15
            max_temp = np.max(env.state.wire_temperature) - 273.15
            spark_on_state = "ON" if env.state.spark_status[0] > 0 else "OFF"
            # Voltage and current in env.state should be what WireModule used
            voltage_in_state = (
                env.state.voltage if env.state.voltage is not None else 0.0
            )
            current_in_state = (
                env.state.current if env.state.current is not None else 0.0
            )
            print(
                f"   t={current_time_us:4d} µs: avg_temp={avg_temp:5.1f}°C, max_temp={max_temp:5.1f}°C, spark={spark_on_state}, V={voltage_in_state:.1f}, I={current_in_state:.1f}"
            )

        # Log data to file/memory - always use env.state for microsecond-resolution logging
        logger.collect(env.state, info)

        if terminated or truncated:
            # If termination happens, info might contain useful details like 'wire_broken'
            term_reason = "Unknown"
            if info and info.get("wire_broken"):
                term_reason = "Wire Broken"
            elif terminated:
                term_reason = "Terminated (e.g. gap too small, target reached)"
            elif truncated:
                term_reason = "Truncated (e.g. time limit)"
            print(
                f"⚠️  Simulation terminated early at t={current_time_us} µs. Reason: {term_reason}"
            )
            # Log one last time if terminated, using the final env.state
            if not (
                should_print_log and current_time_us > 0
            ):  # Avoid double print if already printed
                avg_temp = np.mean(env.state.wire_temperature) - 273.15
                max_temp = np.max(env.state.wire_temperature) - 273.15
                spark_on_state = "ON" if env.state.spark_status[0] > 0 else "OFF"
                voltage_in_state = (
                    env.state.voltage if env.state.voltage is not None else 0.0
                )
                current_in_state = (
                    env.state.current if env.state.current is not None else 0.0
                )
                print(
                    f"   t={current_time_us:4d} µs: avg_temp={avg_temp:5.1f}°C, max_temp={max_temp:5.1f}°C, spark={spark_on_state}, V={voltage_in_state:.1f}, I={current_in_state:.1f} (Final state on termination)"
                )
            break

    wall_time = time.time() - start_time

    logger.finalize()
    log_file = logger.get_data()

    print(f"✅ Simulation completed in {wall_time:.2f} seconds")
    if not log_file or (
        isinstance(log_file, str) and not pathlib.Path(log_file).exists()
    ):
        print(
            f"⚠️ Log file may not have been created or is empty. Expected at: {logger_config['backend']['filepath']}"
        )
    else:
        print(f"📁 Data saved to: {log_file}")

    return log_file, wall_time


def create_spark_animation(
    npz_filepath: str,
    save_animation: bool = False,
    output_filename: str = "single_spark_animation.mp4",
    playback_speed: float = 0.1,
    target_video_duration_s: Optional[float] = None,
    target_video_fps: int = 30,
) -> None:
    """
    Create animation from single spark simulation data.

    Args:
        npz_filepath: Path to simulation data
        save_animation: Whether to save animation file
        output_filename: Output filename for saved animation
        playback_speed: Playback speed multiplier (< 1.0 for slow motion)
        target_video_duration_s: Target duration for the output video in seconds (default: 10.0)
        target_video_fps: Target FPS for the output video (default: 30)
    """
    try:
        data = np.load(npz_filepath)
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    required_keys = ["time", "wire_temperature"]
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        print(f"Missing required data: {missing_keys}")
        print(f"Available keys: {list(data.keys())}")
        return

    time_us = data["time"]
    wire_temp_k = data["wire_temperature"]
    if wire_temp_k.ndim != 2:
        print(f"Error: Temperature data has wrong dimensions: {wire_temp_k.shape}")
        return
    wire_temp_c = wire_temp_k - 273.15
    time_ms = time_us / 1000.0
    n_timesteps_data, n_segments = wire_temp_c.shape

    # Get actual physical dimensions from WireModuleParameters
    # Use the same values as plot_temperature_heatmap.py for consistency
    wire_params = WireModuleParameters()

    # Use actual attributes that exist, with fallbacks to known working values
    buffer_bottom_mm = getattr(wire_params, "buffer_len_bottom", 30.0)  # mm
    buffer_top_mm = getattr(wire_params, "buffer_len_top", 20.0)  # mm
    segment_len_mm = getattr(wire_params, "segment_len", 0.2)  # mm

    # Calculate workpiece height from total segments and buffers
    # From your console: 350 total segments, work zone segments 149 to 197 (49 segments)
    workpiece_height_mm = 10.0  # mm - use same value as heatmap script
    total_length_mm = buffer_bottom_mm + workpiece_height_mm + buffer_top_mm

    # Verify this matches the actual data
    expected_total_segments = int(total_length_mm / segment_len_mm)
    if abs(expected_total_segments - n_segments) > 5:  # Allow some tolerance
        print(
            f"⚠️  Segment count mismatch: expected {expected_total_segments}, got {n_segments}"
        )
        print(f"   Adjusting total_length_mm to match actual data")
        total_length_mm = n_segments * segment_len_mm
        workpiece_height_mm = total_length_mm - buffer_bottom_mm - buffer_top_mm

    wire_diameter_mm = 0.2

    print(f"🔧 Using actual wire parameters:")
    print(f"   Buffer bottom: {buffer_bottom_mm} mm")
    print(f"   Workpiece height: {workpiece_height_mm} mm")
    print(f"   Buffer top: {buffer_top_mm} mm")
    print(f"   Segment length: {segment_len_mm} mm")
    print(f"   Total length: {total_length_mm} mm")
    print(
        f"   Total segments: {n_segments} (expected: {int(total_length_mm / segment_len_mm)})"
    )

    # Calculate contact positions using the same logic as wire.py
    contact_offset_bottom = getattr(wire_params, "contact_offset_bottom", 10.0)  # mm
    contact_offset_top = getattr(wire_params, "contact_offset_top", 10.0)  # mm

    contact_bottom_pos_mm = buffer_bottom_mm - contact_offset_bottom
    contact_top_pos_mm = buffer_bottom_mm + workpiece_height_mm + contact_offset_top

    print(f"🔌 Contact positions:")
    print(f"   Bottom contact: {contact_bottom_pos_mm} mm")
    print(f"   Top contact: {contact_top_pos_mm} mm")

    # Animation parameters for live preview (based on playback_speed)
    sim_duration_ms_data = time_ms[-1] - time_ms[0] if n_timesteps_data > 1 else 0.0
    live_preview_interval_ms = 50
    if n_timesteps_data > 1 and playback_speed > 0:
        live_preview_interval_ms = max(
            10, (sim_duration_ms_data / n_timesteps_data) / playback_speed
        )

    print(f"\n📽️  Animation data:")
    print(f"   Total data timesteps: {n_timesteps_data}")
    print(f"   Wire segments: {n_segments}")
    print(f"   Simulation duration recorded: {sim_duration_ms_data:.1f} ms")

    animation_frame_indices = np.arange(n_timesteps_data)
    num_animation_render_frames = n_timesteps_data
    actual_save_fps = target_video_fps

    output_path = pathlib.Path(output_filename)
    is_gif_output = output_path.suffix.lower() == ".gif"

    if (
        save_animation
        and target_video_duration_s is not None
        and target_video_duration_s > 0
    ):
        num_animation_render_frames = int(target_video_duration_s * target_video_fps)
        if num_animation_render_frames <= 0:
            num_animation_render_frames = 100
        num_animation_render_frames = min(num_animation_render_frames, n_timesteps_data)
        animation_frame_indices = np.linspace(
            0, n_timesteps_data - 1, num=num_animation_render_frames, dtype=int
        )
        actual_save_fps = target_video_fps
        if is_gif_output:
            actual_save_fps = min(
                actual_save_fps, 20
            )  # Cap GIF FPS for targeted duration
            print(
                f"   Subsampling for {target_video_duration_s}s GIF at {actual_save_fps} FPS (capped for GIF):"
            )
        else:
            print(
                f"   Subsampling for {target_video_duration_s}s video at {actual_save_fps} FPS:"
            )
        print(f"     Rendering {num_animation_render_frames} frames from data.")
    elif (
        save_animation
    ):  # Saving, but no specific duration target, derive FPS from playback_speed
        actual_save_fps = 1000.0 / live_preview_interval_ms
        if is_gif_output:
            actual_save_fps = min(actual_save_fps, 15.0)
        else:  # MP4 default
            actual_save_fps = min(actual_save_fps, 30.0)
        actual_save_fps = max(5.0, actual_save_fps)
        print(
            f"   Saving with FPS derived from playback_speed: {actual_save_fps:.1f} FPS"
        )

    # Setup figure with larger fonts for presentation
    plt.rcParams.update(
        {
            "font.size": 16,  # Base font size
            "axes.titlesize": 20,  # Subplot titles
            "axes.labelsize": 18,  # Axis labels
            "xtick.labelsize": 16,  # X-axis tick labels
            "ytick.labelsize": 16,  # Y-axis tick labels
            "legend.fontsize": 16,  # Legend text
            "figure.titlesize": 24,  # Main title
        }
    )

    fig, (ax_wire, ax_temp) = plt.subplots(1, 2, figsize=(16, 8))
    fig.patch.set_facecolor("white")
    visual_thickness = wire_diameter_mm * 5

    # Wire extent: [left, right, bottom, top]
    # With origin='upper', row 0 is at the top, so Y goes from total_length_mm (top) down to 0 (bottom)
    wire_extent = [-visual_thickness / 2, visual_thickness / 2, total_length_mm, 0]
    temp_min_c = 20
    temp_max_c = min(500, np.max(wire_temp_c))
    img = ax_wire.imshow(
        wire_temp_c[animation_frame_indices[0], :].reshape(n_segments, 1),
        cmap="hot",
        origin="upper",  # Changed to 'upper'
        vmin=temp_min_c,
        vmax=temp_max_c,
        extent=wire_extent,
        interpolation="bilinear",
        aspect="auto",  # Ensure it fills the axes box correctly with new origin
    )
    workpiece_bottom_display = total_length_mm - (
        buffer_bottom_mm + workpiece_height_mm
    )  # Position from top
    workpiece_top_display = total_length_mm - buffer_bottom_mm  # Position from top

    ax_wire.set_ylim(0, total_length_mm)
    # Recalculate extent for imshow to match this new y-axis orientation for ax_wire
    img.set_extent([-visual_thickness / 2, visual_thickness / 2, 0, total_length_mm])

    # Workpiece lines on wire plot (y from bottom)
    ax_wire.axhline(
        buffer_bottom_mm,
        color="gray",
        linestyle="--",
        alpha=0.8,
        label="Workpiece Bottom",
        linewidth=2,  # Make lines thicker too
    )
    ax_wire.axhline(
        buffer_bottom_mm + workpiece_height_mm,
        color="gray",
        linestyle="--",
        alpha=0.8,
        label="Workpiece Top",
        linewidth=2,
    )

    # Contact lines on wire plot
    ax_wire.axhline(
        contact_bottom_pos_mm,
        color="gray",
        linestyle=":",
        alpha=0.6,
        label="Bottom Contact",
        linewidth=2,
    )
    ax_wire.axhline(
        contact_top_pos_mm,
        color="gray",
        linestyle=":",
        alpha=0.6,
        label="Top Contact",
        linewidth=2,
    )

    ax_wire.set_xlim(-visual_thickness * 4, visual_thickness * 4)
    ax_wire.set_xticks([])
    ax_wire.set_xlabel("")
    ax_wire.set_ylabel("Position along wire (mm from bottom)")
    ax_wire.set_title("Wire Temperature Field")

    fig.colorbar(
        img, ax=ax_wire, orientation="vertical", label="Temperature (°C)", shrink=0.8
    )

    # Y positions for the line plot
    y_positions_lineplot = np.linspace(total_length_mm, 0, n_segments)
    (line_temp,) = ax_temp.plot(
        wire_temp_c[animation_frame_indices[0], :],
        y_positions_lineplot,
        "r-",
        linewidth=3,  # Make line thicker
    )

    # Workpiece shaded region on temperature profile plot
    ax_temp.axhspan(
        buffer_bottom_mm,
        buffer_bottom_mm + workpiece_height_mm,
        alpha=0.2,
        color="gray",
        label="Workpiece",
    )

    # Contact lines on temperature profile plot
    ax_temp.axhline(
        contact_bottom_pos_mm,
        color="gray",
        linestyle=":",
        alpha=0.6,
        label="Bottom Contact",
        linewidth=2,
    )
    ax_temp.axhline(
        contact_top_pos_mm,
        color="gray",
        linestyle=":",
        alpha=0.6,
        label="Top Contact",
        linewidth=2,
    )

    ax_temp.set_xlabel("Temperature (°C)")
    ax_temp.set_ylabel("Position along wire (mm from bottom)")
    ax_temp.set_ylim(0, total_length_mm)
    ax_temp.set_title("Temperature Profile")
    ax_temp.grid(True, alpha=0.3)
    ax_temp.legend(loc="upper right")
    ax_temp.set_xlim(temp_min_c, temp_max_c)

    title_obj = fig.suptitle(
        f"Single Spark Evolution - Sim Time: {time_ms[animation_frame_indices[0]]:.3f} ms",
        fontsize=24,  # Explicit large font size for title
        fontweight="bold",
    )

    def update_animation(frame_k):
        actual_data_idx = animation_frame_indices[frame_k]
        current_temp_field = wire_temp_c[actual_data_idx, :].reshape(n_segments, 1)
        img.set_data(current_temp_field)
        # The line plot - keep the same temperature data, y_positions_lineplot is now correct
        line_temp.set_xdata(wire_temp_c[actual_data_idx, :])
        title_obj.set_text(
            f"Single Spark Evolution - Sim Time: {time_ms[actual_data_idx]:.3f} ms (Frame {frame_k+1}/{num_animation_render_frames})"
        )
        return [img, line_temp, title_obj]

    ani = animation.FuncAnimation(
        fig,
        update_animation,
        frames=num_animation_render_frames,
        interval=live_preview_interval_ms,
        blit=True,
        repeat=True,
    )

    if save_animation:
        writer_name = None
        save_dpi = 150

        if is_gif_output:
            writer_name = "pillow"
            save_dpi = 100  # GIFs are better with lower DPI
        else:  # Try ffmpeg for MP4
            if animation.writers["ffmpeg"].isAvailable():
                writer_name = "ffmpeg"
            else:
                print(
                    "⚠️ FFmpeg writer not available. Trying to save as GIF with Pillow instead."
                )
                # Fallback to GIF if ffmpeg isn't there for MP4
                output_filename = str(
                    output_path.with_suffix(".gif")
                )  # Change extension
                is_gif_output = True  # Update flag
                writer_name = "pillow"
                save_dpi = 100
                # Recalculate actual_save_fps if it was for MP4 and now it's GIF
                if target_video_duration_s is not None:  # If duration was targeted
                    actual_save_fps = min(target_video_fps, 20)  # Cap for GIF
                else:  # FPS derived from playback_speed
                    derived_fps = 1000.0 / live_preview_interval_ms
                    actual_save_fps = min(derived_fps, 15.0)
                    actual_save_fps = max(5.0, actual_save_fps)
                print(
                    f"   New output: {output_filename}, Fallback FPS for GIF: {actual_save_fps:.1f}"
                )

        if writer_name:
            try:
                print(
                    f"💾 Saving animation to {output_filename} (FPS: {actual_save_fps:.1f}, Writer: {writer_name}, DPI: {save_dpi})..."
                )
                ani.save(
                    output_filename,
                    writer=writer_name,
                    fps=actual_save_fps,
                    dpi=save_dpi,
                )
                print("✅ Animation saved successfully!")
            except Exception as e:
                print(f"❌ Error saving animation with {writer_name}: {e}")
                print("Showing live preview instead (if possible)...")
                plt.show()
        else:
            print("No suitable animation writer found. Showing live preview...")
            plt.show()
    else:
        plt.show()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Simulate and animate wire temperature evolution after a single spark, or animate existing data."
    )
    # Arguments for running a new simulation
    sim_group = parser.add_argument_group("Simulation Parameters (if not loading data)")
    sim_group.add_argument(
        "--spark-time",
        type=float,
        default=50.0,
        help="When spark occurs (µs from start, default: 50)",
    )
    sim_group.add_argument(
        "--spark-duration",
        type=float,
        default=2.0,
        help="Spark duration (µs, default: 2.0)",
    )
    sim_group.add_argument(
        "--spark-location",
        type=float,
        default=25.0,
        help="Spark location from workpiece bottom (mm, default: 25.0)",
    )
    sim_group.add_argument(
        "--voltage", type=float, default=80.0, help="Spark voltage (V, default: 80.0)"
    )
    sim_group.add_argument(
        "--current-mode",
        type=int,
        default=13,
        help="Generator current mode 1-19 (default: 13)",
    )
    sim_group.add_argument(
        "--plasma-efficiency",
        type=float,
        default=None,  # Default to None, will use WireModule default or a test value
        help="Plasma heating efficiency (0.0 to 1.0, default: WireModule default or 0.5 for this script)",
    )
    sim_group.add_argument(
        "--duration",
        type=int,
        default=1000,
        help="Total simulation duration (µs, default: 1000 for 1ms)",
    )

    # Arguments for loading existing data
    load_group = parser.add_argument_group("Data Loading Parameters")
    load_group.add_argument(
        "--load-data",
        type=str,
        default=None,
        help="Path to an existing .npz file to load for animation. If provided, simulation parameters are ignored.",
    )

    # Arguments for animation (common to both modes)
    anim_group = parser.add_argument_group("Animation Parameters")
    anim_group.add_argument(
        "--playback-speed",
        type=float,
        default=0.1,
        help="Animation playback speed multiplier for live preview (default: 0.1 for slow motion)",
    )
    anim_group.add_argument(
        "--save", action="store_true", help="Save animation to file"
    )
    anim_group.add_argument(
        "--out",
        type=str,
        default="single_spark_animation.gif",  # Changed default to GIF
        help="Output animation filename (e.g., .mp4 or .gif, default: single_spark_animation.gif)",
    )
    anim_group.add_argument(
        "--target-video-duration",
        type=float,
        default=10.0,
        help="Target duration for the output video in seconds (default: 10.0)",
    )
    anim_group.add_argument(
        "--target-video-fps",
        type=int,
        default=20,  # Changed default to 20, better for GIF
        help="Target FPS for the output video (default: 20 for GIF, 30 for MP4)",
    )
    parser.add_argument(  # Moved data-only out of any specific group as it's a general flag
        "--data-only",
        action="store_true",
        help="Only run simulation, skip animation (if not loading data)",
    )

    args = parser.parse_args()

    log_file_path = None

    if args.load_data:
        print(f"Attempting to load data from: {args.load_data}")
        if not pathlib.Path(args.load_data).exists():
            print(f"Error: Data file not found at {args.load_data}")
            return
        log_file_path = args.load_data
        # If loading data, we must not be in data_only mode for animation
        if args.data_only:
            print(
                "Warning: --data-only is ignored when --load-data is used, proceeding with animation."
            )
            args.data_only = False  # Ensure animation happens
    else:
        # Run new simulation
        spark_config = {
            "spark_time_us": args.spark_time,
            "spark_duration_us": args.spark_duration,
            "spark_location_mm": args.spark_location,
            "voltage": args.voltage,
            "current_mode": args.current_mode,
        }
        current_plasma_efficiency = args.plasma_efficiency
        if current_plasma_efficiency is None and not args.data_only:
            current_plasma_efficiency = 0.5

        env = initialize_single_spark_environment(
            plasma_efficiency=current_plasma_efficiency
        )
        logger_config = setup_single_spark_logger()
        # Use a unique name for the data file if running a new sim, based on output anim name
        sim_data_identifier = pathlib.Path(args.out).stem
        logger_config["backend"][
            "filepath"
        ] = f"logs/{sim_data_identifier}_sim_data.npz"

        log_file_path, wall_time = run_single_spark_simulation(
            env, logger_config, spark_config, args.duration
        )

    if not args.data_only and log_file_path:
        if not pathlib.Path(log_file_path).exists():
            print(
                f"Error: Log file {log_file_path} not found or was not created. Cannot create animation."
            )
            return

        output_is_gif = pathlib.Path(args.out).suffix.lower() == ".gif"
        effective_target_fps = args.target_video_fps
        if output_is_gif and args.target_video_fps > 20:
            print(
                f"Note: Specified FPS {args.target_video_fps} is high for GIF. Capping to 20 FPS for {args.out}"
            )
            effective_target_fps = 20
        elif not output_is_gif and args.target_video_fps > 30:  # e.g. MP4
            effective_target_fps = 30  # Keep a reasonable default if not GIF

        create_spark_animation(
            log_file_path,
            save_animation=args.save,
            output_filename=args.out,
            playback_speed=args.playback_speed,
            target_video_duration_s=args.target_video_duration if args.save else None,
            target_video_fps=(
                effective_target_fps if args.save else 20
            ),  # Default to 20 if not saving
        )
    elif args.data_only:
        print("Simulation completed in data-only mode. No animation created.")
    elif not log_file_path:
        print(
            "No data file available (either from simulation or --load-data). Cannot create animation."
        )


if __name__ == "__main__":
    main()
