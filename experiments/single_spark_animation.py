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
from src.wedm.core.env_config import EnvironmentConfig


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


def setup_single_spark_logger(log_interval: int = 1) -> LoggerConfig:
    """Setup logger for high-frequency wire temperature recording."""
    log_freq = (
        {"type": "every_step"}
        if log_interval <= 1
        else {"type": "interval", "value": int(log_interval)}
    )
    return {
        "signals_to_log": [
            "time",
            "wire_temperature",  # Full temperature field
            "wire_material_positions_mm",  # Lagrangian positions per segment (mm)
            "voltage",
            "current",
            "spark_status",
            "wire_position",
            "workpiece_position",
            # Movement diagnostics (from WireModule)
            "wire_head_idx",
            "wire_offset_mm",
        ],
        "log_frequency": log_freq,
        "backend": {
            "type": "numpy",
            "filepath": "logs/single_spark_temperature.npz",
            "compress": True,
        },
    }


def initialize_single_spark_environment(
    seed: int = 42,
    plasma_efficiency: Optional[float] = None,
    wire_velocity_um_us: float = 0.2,
    workpiece_height_mm: float = 20.0,
    n_segments: Optional[int] = None,
) -> WireEDMEnv:
    """Initialize environment optimized for single spark observation."""
    
    # Create environment config with specified workpiece height
    env_config = EnvironmentConfig(workpiece_height=workpiece_height_mm)
    
    # Set up wire parameters
    wire_params = WireModuleParameters()
    if plasma_efficiency is not None:
        print(f"[INFO] Using custom plasma_efficiency: {plasma_efficiency}")
        wire_params.plasma_efficiency = plasma_efficiency
    
    # Calculate segment length to get desired number of segments
    if n_segments is not None:
        total_length = (
            wire_params.buffer_len_bottom
            + workpiece_height_mm
            + wire_params.buffer_len_top
        )
        # Calculate segment length to get exactly n_segments
        # The wire module uses: n_segments = int(total_L / segment_len)
        # To get exactly n_segments, we need: n_segments <= total_L / segment_len < n_segments + 1
        # So: total_L / (n_segments + 1) < segment_len <= total_L / n_segments
        # We use total_L / n_segments but with a tiny reduction to ensure we don't exceed n_segments+1
        base_segment_len = total_length / n_segments
        # Ensure we get at least n_segments by making segment_len slightly smaller
        # This ensures total_L / segment_len >= n_segments
        calculated_segment_len = base_segment_len * (1.0 - 1e-6)
        wire_params.segment_len = calculated_segment_len
        print(f"[INFO] Setting segment length to {calculated_segment_len:.6f} mm for {n_segments} segments (total_L={total_length:.2f} mm)")

    env = WireEDMEnv(
        mechanics_control_mode="position",
        config=env_config,
        wire_params=wire_params,
    )
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
    # Wire movement (µm/µs). Example: 0.2 → ~1 turnover per ms for 0.2 mm segments
    env.state.wire_unwinding_velocity = float(wire_velocity_um_us)

    # Initialize wire temperature to room temperature
    if len(env.state.wire_temperature) == 0:
        env.wire.update(env.state)

    # Set all segments to room temperature initially
    env.state.wire_temperature.fill(293.15)  # 20°C in Kelvin

    print(f"[INFO] Single spark observation setup:")
    print(f"   Wire segments: {len(env.state.wire_temperature)}")
    print(f"   Wire length: {env.wire.total_L:.1f} mm")
    print(f"   Segment length: {env.wire.params.segment_len:.3f} mm")
    print(
        f"   Initial gap: {env.state.workpiece_position - env.state.wire_position:.1f} µm"
    )
    print(f"   Wire velocity: {env.state.wire_unwinding_velocity:.3f} µm/µs")

    return env


def run_single_spark_simulation(
    env: WireEDMEnv,
    logger_config: LoggerConfig,
    spark_config: Dict[str, float],
    simulation_duration_us: int = 1000,
    *,
    fast_mode: bool = False,
    verbose: bool = False,
) -> Tuple[str, float]:
    """
    Run simulation of single spark event.

    Args:
        env: Initialized environment
        logger_config: Logger configuration
        spark_config: Spark timing and parameters
        simulation_duration_us: Total simulation time in microseconds
        fast_mode: If True, monkey-patch non-wire modules to no-op for speed
        verbose: If True, print periodic logs

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

    if verbose:
        print(f"[START] Starting single spark simulation...")
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

    # Speed optimizations: monkey-patch non-wire modules if requested
    if fast_mode:
        env.ignition.update = lambda state: None
        env.material.update = lambda state: None
        env.dielectric.update = lambda state: None
        env.mechanics.update = lambda state: None

    spark_start_time = spark_config["spark_time_us"]
    spark_total_duration = spark_config["spark_duration_us"]

    # Initial log print before loop starts
    if verbose:
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

        # Disable ignition in fast or normal mode (we drive spark manually)
        if step_counter == 0 and not fast_mode:
            env.ignition.update = lambda state, dt=None: None

        is_spark_active_this_step = (
            spark_start_time
            <= current_time_us
            < (spark_start_time + spark_total_duration)
        )

        if is_spark_active_this_step:
            # Activate spark: [active=1, location_mm, duration_remaining]
            env.state.spark_status = [1, spark_config["spark_location_mm"], 1]
            # Manually set spark V/I
            OCV = spark_config["voltage"]
            spark_burning_voltage = OCV * 0.3
            env.state.voltage = spark_burning_voltage
            env.state.current = 60.0
            if verbose and current_time_us == spark_start_time:
                print(
                    f"[SPARK] Spark FORCED at t={current_time_us}µs, duration={spark_total_duration}µs, loc_cfg={spark_config['spark_location_mm']:.1f}mm"
                )
        else:
            env.state.spark_status = [0, None, 0]
            env.state.voltage = spark_config["voltage"]
            env.state.current = 0.0

        state_from_step, reward, terminated, truncated, info = env.step(action)

        # Log data to file/memory - always use env.state for microsecond-resolution logging
        logger.collect(env.state, info)

        if (terminated or truncated) and verbose:
            term_reason = "Unknown"
            if info and info.get("wire_broken"):
                term_reason = "Wire Broken"
            elif terminated:
                term_reason = "Terminated (e.g. gap too small, target reached)"
            elif truncated:
                term_reason = "Truncated (e.g. time limit)"
            print(
                f"[WARNING] Simulation terminated early at t={current_time_us} µs. Reason: {term_reason}"
            )
            break

    wall_time = time.time() - start_time

    logger.finalize()
    log_file = logger.get_data()

    print(f"[OK] Simulation completed in {wall_time:.2f} seconds")
    if not log_file or (
        isinstance(log_file, str) and not pathlib.Path(log_file).exists()
    ):
        print(
            f"[WARNING] Log file may not have been created or is empty. Expected at: {logger_config['backend']['filepath']}"
        )
    else:
        print(f"[INFO] Data saved to: {log_file}")

    return log_file, wall_time


def create_spark_animation(
    npz_filepath: str,
    save_animation: bool = False,
    output_filename: str = "single_spark_animation.mp4",
    playback_speed: float = 0.1,
    target_video_duration_s: Optional[float] = None,
    target_video_fps: int = 30,
    show_edges: bool = False,
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
    if "wire_material_positions_mm" not in data:
        print(
            "wire_material_positions_mm not found in data; required for Lagrangian visualization."
        )
        print(f"Available keys: {list(data.keys())}")
        return
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        print(f"Missing required data: {missing_keys}")
        print(f"Available keys: {list(data.keys())}")
        return

    time_us = data["time"]
    wire_temp_k = data["wire_temperature"]
    pos_mm = data["wire_material_positions_mm"]  # Lagrangian positions (T, N)
    if wire_temp_k.ndim != 2:
        print(f"Error: Temperature data has wrong dimensions: {wire_temp_k.shape}")
        return

    if pos_mm.ndim != 2 or pos_mm.shape != wire_temp_k.shape:
        print(
            f"Error: Position data shape mismatch: {pos_mm.shape} vs {wire_temp_k.shape}"
        )
        return

    wire_temp_c = wire_temp_k - 273.15
    time_ms = time_us / 1000.0
    n_timesteps_data, n_segments = wire_temp_c.shape

    # Get actual physical dimensions from WireModuleParameters
    wire_params = WireModuleParameters()
    buffer_bottom_mm = getattr(wire_params, "buffer_len_bottom", 30.0)
    buffer_top_mm = getattr(wire_params, "buffer_len_top", 30.0)

    # Compute segment length from position differences
    first_positions = pos_mm[0, :]
    if len(first_positions) > 1:
        # Sort positions to find segment length
        sorted_pos = np.sort(first_positions)
        diffs = np.diff(sorted_pos)
        # Filter out zero differences (if segments have same position initially)
        diffs = diffs[diffs > 1e-6]
        if len(diffs) > 0:
            segment_len_mm = np.median(diffs)  # Use median to handle edge cases
        else:
            # Fallback: compute from total range
            segment_len_mm = (np.max(first_positions) - np.min(first_positions)) / max(
                1, n_segments - 1
            )
    else:
        segment_len_mm = getattr(wire_params, "segment_len", 0.2)

    # Find max and min positions across all timesteps to determine total length
    max_pos = np.max(pos_mm)
    min_pos = np.min(pos_mm)
    # Total length is approximately the range plus one segment
    total_length_mm = max_pos + segment_len_mm - min_pos
    
    # Calculate workpiece height from total length and buffer lengths
    # Formula: total_length = buffer_bottom + workpiece_height + buffer_top
    workpiece_height_mm = total_length_mm - buffer_bottom_mm - buffer_top_mm
    # Ensure non-negative
    if workpiece_height_mm < 0:
        print(f"[WARNING] Calculated workpiece_height ({workpiece_height_mm:.2f} mm) is negative, using default 20.0 mm")
        workpiece_height_mm = 20.0

    wire_diameter_mm = 0.2

    print(f"[INFO] Using actual wire parameters:")
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

    print(f"[INFO] Contact positions:")
    print(f"   Bottom contact: {contact_bottom_pos_mm} mm")
    print(f"   Top contact: {contact_top_pos_mm} mm")

    # Animation parameters for live preview (based on playback_speed)
    sim_duration_ms_data = time_ms[-1] - time_ms[0] if n_timesteps_data > 1 else 0.0
    live_preview_interval_ms = 50
    if n_timesteps_data > 1 and playback_speed > 0:
        live_preview_interval_ms = max(
            10, (sim_duration_ms_data / n_timesteps_data) / playback_speed
        )

    print(f"\n[ANIMATION] Animation data:")
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

    temp_min_c = 20
    temp_max_c = min(500, np.max(wire_temp_c))

    # Create colormap for temperature
    cmap = plt.get_cmap("hot")
    norm = plt.Normalize(vmin=temp_min_c, vmax=temp_max_c)

    # Initialize rectangles for Lagrangian visualization
    from matplotlib.patches import Rectangle

    rectangles = []
    initial_positions = pos_mm[animation_frame_indices[0], :]
    initial_temps = wire_temp_c[animation_frame_indices[0], :]
    
    # Add small overlap (5%) to segment height to prevent gaps between segments
    segment_height_viz = segment_len_mm * 1.05

    for i in range(n_segments):
        y_start = initial_positions[i]
        rect = Rectangle(
            (-visual_thickness / 2, y_start),
            visual_thickness,
            segment_height_viz,
            facecolor=cmap(norm(initial_temps[i])),
            edgecolor="black" if show_edges else "none",
            linewidth=0.5 if show_edges else 0,
        )
        ax_wire.add_patch(rect)
        rectangles.append(rect)

    ax_wire.set_xlim(-visual_thickness * 2, visual_thickness * 2)

    # Crop visualization to exclude first 2 and last 2 segments
    if n_segments > 4:
        # Get positions of segments we want to show (indices 2 to N-3)
        visible_positions = initial_positions[2:-2]
        y_min_visible = np.min(visible_positions)
        y_max_visible = np.max(visible_positions) + segment_len_mm
        # Add small padding
        padding = segment_len_mm * 0.5
        # With inverted y-axis, set limits so min appears at top and max at bottom
        ax_wire.set_ylim(y_min_visible - padding, y_max_visible + padding)
    else:
        ax_wire.set_ylim(0, total_length_mm)
    ax_wire.invert_yaxis()  # Invert so wire unwinds from top to bottom

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

    # Add colorbar using a ScalarMappable
    from matplotlib.cm import ScalarMappable

    sm = ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    fig.colorbar(
        sm, ax=ax_wire, orientation="vertical", label="Temperature (°C)", shrink=0.8
    )

    # Initialize line plot with Lagrangian positions
    initial_positions_sorted = np.sort(initial_positions)
    initial_temps_sorted = initial_temps[np.argsort(initial_positions)]
    (line_temp,) = ax_temp.plot(
        initial_temps_sorted,
        initial_positions_sorted,
        "r-",
        linewidth=3,
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

    # Crop visualization to exclude first 2 and last 2 segments (match wire plot)
    if n_segments > 4:
        visible_positions = initial_positions[2:-2]
        y_min_visible = np.min(visible_positions)
        y_max_visible = np.max(visible_positions) + segment_len_mm
        padding = segment_len_mm * 0.5
        # With inverted y-axis, set limits so min appears at top and max at bottom
        ax_temp.set_ylim(y_min_visible - padding, y_max_visible + padding)
    else:
        ax_temp.set_ylim(0, total_length_mm)
    ax_temp.invert_yaxis()  # Invert to match wire visualization
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
        actual_idx = animation_frame_indices[frame_k]

        # Get current Lagrangian positions and temperatures
        current_positions = pos_mm[actual_idx, :]
        current_temps = wire_temp_c[actual_idx, :]

        # Update rectangle positions and colors
        for i in range(n_segments):
            rectangles[i].set_y(current_positions[i])
            rectangles[i].set_facecolor(cmap(norm(current_temps[i])))

        # Update line plot - sort by position for proper visualization
        sorted_indices = np.argsort(current_positions)
        sorted_positions = current_positions[sorted_indices]
        sorted_temps = current_temps[sorted_indices]
        line_temp.set_xdata(sorted_temps)
        line_temp.set_ydata(sorted_positions)

        title_obj.set_text(
            f"Single Spark Evolution - Sim Time: {time_ms[actual_idx]:.3f} ms (Frame {frame_k+1}/{num_animation_render_frames})"
        )

        # Return all artists for blitting
        return rectangles + [line_temp, title_obj]

    ani = animation.FuncAnimation(
        fig,
        update_animation,
        frames=num_animation_render_frames,
        interval=live_preview_interval_ms,
        blit=False,
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
                    "[WARNING] FFmpeg writer not available. Trying to save as GIF with Pillow instead."
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
                    f"[SAVING] Saving animation to {output_filename} (FPS: {actual_save_fps:.1f}, Writer: {writer_name}, DPI: {save_dpi})..."
                )
                ani.save(
                    output_filename,
                    writer=writer_name,
                    fps=actual_save_fps,
                    dpi=save_dpi,
                )
                print("[OK] Animation saved successfully!")
            except Exception as e:
                print(f"[ERROR] Error saving animation with {writer_name}: {e}")
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
        default=5.0,
        help="Spark location from workpiece bottom (mm, default: 5.0)",
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
    sim_group.add_argument(
        "--velocity",
        type=float,
        default=0.2,
        help="Wire unwinding velocity [µm/µs] (default: 0.2 → ~1 turnover/ms)",
    )
    sim_group.add_argument(
        "--log-interval",
        type=int,
        default=1,
        help="Log every N µs to reduce I/O (default: 1 = every step)",
    )
    sim_group.add_argument(
        "--fast",
        action="store_true",
        help="Fast mode: skip non-wire modules to speed up simulation",
    )
    sim_group.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed progress during simulation",
    )
    sim_group.add_argument(
        "--workpiece-height",
        type=float,
        default=20.0,
        help="Workpiece height in mm (default: 20.0)",
    )
    sim_group.add_argument(
        "--n-segments",
        type=int,
        default=None,
        help="Number of wire segments (default: auto-calculated based on segment length)",
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
        help="Animation playback speed multiplier for live preview (higher = faster)",
    )
    anim_group.add_argument(
        "--save", action="store_true", help="Save animation to file"
    )
    anim_group.add_argument(
        "--out",
        type=str,
        default="single_spark_animation.gif",  # Default GIF
        help="Output animation filename (e.g., .mp4 or .gif, default: single_spark_animation.gif)",
    )
    anim_group.add_argument(
        "--target-video-duration",
        type=float,
        default=10.0,
        help="Target duration for the output video in seconds (when saving)",
    )
    anim_group.add_argument(
        "--target-video-fps",
        type=int,
        default=20,
        help="Target FPS for the output video (default: 20 for GIF, 30 for MP4)",
    )
    anim_group.add_argument(
        "--show-edges",
        action="store_true",
        help="Show edges/contours around thermal segments (default: False, edges hidden)",
    )
    parser.add_argument(
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
        if args.data_only:
            print(
                "Warning: --data-only is ignored when --load-data is used, proceeding with animation."
            )
            args.data_only = False
    else:
        # Run new simulation
        spark_config = {
            "spark_time_us": (
                args.spark_time if args.spark_time != 50.0 else int(args.duration * 0.2)
            ),
            "spark_duration_us": args.spark_duration,
            "spark_location_mm": args.spark_location,
            "voltage": args.voltage,
            "current_mode": args.current_mode,
        }
        current_plasma_efficiency = args.plasma_efficiency
        if current_plasma_efficiency is None and not args.data_only:
            current_plasma_efficiency = 0.5

        env = initialize_single_spark_environment(
            plasma_efficiency=current_plasma_efficiency,
            wire_velocity_um_us=args.velocity,
            workpiece_height_mm=args.workpiece_height,
            n_segments=args.n_segments,
        )
        logger_config = setup_single_spark_logger(args.log_interval)
        # Use a unique name for the data file if running a new sim, based on output anim name
        sim_data_identifier = pathlib.Path(args.out).stem
        logger_config["backend"][
            "filepath"
        ] = f"logs/{sim_data_identifier}_sim_data.npz"

        log_file_path, wall_time = run_single_spark_simulation(
            env,
            logger_config,
            spark_config,
            args.duration,
            fast_mode=args.fast,
            verbose=args.verbose,
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
            effective_target_fps = 30

        create_spark_animation(
            log_file_path,
            save_animation=args.save,
            output_filename=args.out,
            playback_speed=args.playback_speed,
            target_video_duration_s=args.target_video_duration if args.save else None,
            target_video_fps=(effective_target_fps if args.save else 20),
            show_edges=args.show_edges,
        )
    elif args.data_only:
        print("Simulation completed in data-only mode. No animation created.")
    elif not log_file_path:
        print(
            "No data file available (either from simulation or --load-data). Cannot create animation."
        )


if __name__ == "__main__":
    main()
