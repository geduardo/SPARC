#!/usr/bin/env python
# experiments/quickstart_animation.py
"""
Run a quickstart Wire-EDM simulation (gap or voltage control) with full-field
wire temperature logging, then animate the thermal evolution. Supports saving
as GIF/MP4 or live preview.

Usage examples:
    # Run 30 ms sim (position control, gap controller), save GIF
    python experiments/quickstart_animation.py --duration 30000 --save --out quickstart.gif

    # Load existing data and preview live at faster playback
    python experiments/quickstart_animation.py --load-data logs/smoke_test_position_control.npz --playback-speed 5
"""
from __future__ import annotations

import argparse
import pathlib
from typing import Any, Optional

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from experiments.run_simulation import (
    run_simulation,
    setup_logger,
)
from src.wedm.envs import WireEDMEnv
from src.wedm.modules.wire import WireModuleParameters


def run_quickstart_sim(
    duration_us: int,
    control_mode: str,
    controller: str,
    out_basename: str,
    verbose: bool = False,
    *,
    segments: int | None = None,
    segment_len_mm: float | None = None,
    workpiece_height: float = 20.0,
    current_mode: int = 7,
):
    # Import necessary modules
    from src.wedm.core.env_config import EnvironmentConfig

    # Determine environment and wire parameters
    if segment_len_mm is not None:
        wire_params = WireModuleParameters(
            segment_len=float(segment_len_mm), moving_segments=True
        )
        config = EnvironmentConfig(workpiece_height=workpiece_height)
        env = WireEDMEnv(config=config)
        # Override wire module with custom parameters
        from src.wedm.modules.wire import WireModule

        env.wire = WireModule(env, parameters=wire_params)
    elif segments is not None and segments > 0:
        # Calculate segment length for desired number of segments
        # Total wire length = buffer_bottom (30mm) + workpiece_height + buffer_top (30mm)
        total_length_mm = 30.0 + workpiece_height + 30.0
        # Compute segment length
        eps = 1e-9
        seg_len = max(1e-9, total_length_mm / float(segments) - eps)
        wire_params = WireModuleParameters(segment_len=seg_len, moving_segments=True)
        config = EnvironmentConfig(workpiece_height=workpiece_height)
        env = WireEDMEnv(config=config)
        # Override wire module with custom parameters
        from src.wedm.modules.wire import WireModule

        env.wire = WireModule(env, parameters=wire_params)
    else:
        config = EnvironmentConfig(workpiece_height=workpiece_height)
        env = WireEDMEnv(config=config)

    # Set initial conditions (same as initialize_environment in run_simulation.py)
    env.state.workpiece_position = 20.0  # um
    env.state.wire_position = 10.0  # um
    env.state.target_position = 5_000.0  # um
    env.state.spark_status = [0, None, 0]
    env.state.dielectric_temperature = 293.15  # Room temperature in K

    # Set current mode if specified
    env.state.current_mode = f"I{current_mode}"

    # Initialize wire temperature array
    if len(env.state.wire_temperature) == 0:
        env.wire.update(env.state)

    logger_config = setup_logger(
        control_mode, log_to_file=True, log_strategy="full_field"
    )
    # Use the output basename for file path consistency
    logger_config["backend"][
        "filepath"
    ] = f"logs/{pathlib.Path(out_basename).stem}_sim_data.npz"

    log_data, wall_time, sim_time_us = run_simulation(
        env,
        max_steps=duration_us,
        verbose=verbose,
        logger_config=logger_config,
        controller_type=controller,
    )
    # log_data is file path (numpy backend)
    return logger_config["backend"]["filepath"]


def export_csv(npz_filepath: str, csv_out: str, max_segments: int = 20) -> None:
    try:
        data = np.load(npz_filepath)
    except Exception as e:
        print(f"Error loading data for CSV export: {e}")
        return

    if ("wire_temperature" not in data) or ("wire_material_positions_mm" not in data):
        print(
            "CSV export requires 'wire_temperature' and 'wire_material_positions_mm' in the dataset."
        )
        print(f"Available keys: {list(data.keys())}")
        return

    time_us = data.get("time")
    temps_k = data["wire_temperature"]  # shape (T, N)
    pos_mm = data["wire_material_positions_mm"]  # shape (T, N)

    if temps_k.ndim != 2 or pos_mm.ndim != 2 or temps_k.shape != pos_mm.shape:
        print(
            f"Unexpected shapes for export: temps {temps_k.shape}, positions {pos_mm.shape}"
        )
        return

    T, N = temps_k.shape
    # If max_segments is None or >= actual number of segments, export all segments
    # Otherwise, limit to max_segments
    if max_segments is None or max_segments >= N:
        N_out = N
        segment_indices = np.arange(N)
    else:
        N_out = int(max_segments)
        # Export the first N_out segments (in order)
        segment_indices = np.arange(N_out)

    header_cols = ["time_us"] if time_us is not None else []
    for i in range(N_out):
        header_cols.append(f"pos_mm_{i}")
        header_cols.append(f"temp_K_{i}")
    header_line = ",".join(header_cols)

    # Slice to selected segments and build output matrix
    # Build interleaved [pos_0, temp_0, pos_1, temp_1, ...]
    interleaved = np.empty((T, 2 * N_out), dtype=np.float64)
    pos_slice = pos_mm[:, segment_indices].astype(np.float64)
    temp_slice = temps_k[:, segment_indices].astype(np.float64)
    for j in range(N_out):
        interleaved[:, 2 * j] = pos_slice[:, j]
        interleaved[:, 2 * j + 1] = temp_slice[:, j]

    # Prepend time column if present
    if time_us is not None:
        time_col = np.asarray(time_us).reshape(-1, 1)
        out_mat = np.concatenate([time_col, interleaved], axis=1)
    else:
        out_mat = interleaved

    csv_path = pathlib.Path(csv_out)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    # Build fmt to avoid scientific notation
    fmt_list = []
    if time_us is not None:
        # time is integer microseconds
        # Use integer format if integral, else fixed-point without exponent
        if np.issubdtype(np.asarray(time_us).dtype, np.integer):
            fmt_list.append("%d")
        else:
            fmt_list.append("%.0f")
    # For each segment: position, temperature
    for _ in range(N_out):
        fmt_list.append("%.6f")  # pos in mm
        fmt_list.append("%.6f")  # temp in K

    np.savetxt(
        csv_path.as_posix(),
        out_mat,
        delimiter=",",
        header=header_line,
        comments="",
        fmt=fmt_list if len(fmt_list) > 1 else "%.6f",
    )
    print(f"📝 CSV exported: {csv_path}")


def create_animation(
    npz_filepath: str,
    save_animation: bool = False,
    output_filename: str = "quickstart_animation.gif",
    playback_speed: float = 1.0,
    target_video_duration_s: Optional[float] = None,
    target_video_fps: int = 20,
) -> None:
    try:
        data = np.load(npz_filepath)
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    if "wire_temperature" not in data:
        print("wire_temperature not found in data; ensure log_strategy='full_field'.")
        print(f"Available keys: {list(data.keys())}")
        return

    if "wire_material_positions_mm" not in data:
        print(
            "wire_material_positions_mm not found in data; required for Lagrangian visualization."
        )
        print(f"Available keys: {list(data.keys())}")
        return

    time_us = data.get("time")
    wire_temp_k = data["wire_temperature"]
    pos_mm = data["wire_material_positions_mm"]  # Lagrangian positions (T, N)

    if time_us is None:
        print("'time' not found; proceeding with inferred timeline")
        time_us = np.arange(wire_temp_k.shape[0])

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

    # Physical dimensions - compute segment length from first timestep positions
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

    # Get workpiece height (needed for total_length calculation)
    workpiece_height_mm = (
        getattr(getattr(wire_params, "__class__", object), "workpiece_height", 20.0)
        if hasattr(wire_params, "workpiece_height")
        else 20.0
    )

    # Find max and min positions across all timesteps to determine total length
    max_pos = np.max(pos_mm)
    min_pos = np.min(pos_mm)
    # Total length is approximately the range plus one segment
    total_length_mm = max(
        max_pos + segment_len_mm - min_pos,
        buffer_bottom_mm + workpiece_height_mm + buffer_top_mm,
    )

    # Playback timing
    sim_duration_ms_data = time_ms[-1] - time_ms[0] if n_timesteps_data > 1 else 0.0
    live_preview_interval_ms = 50
    if n_timesteps_data > 1 and playback_speed > 0:
        live_preview_interval_ms = max(
            10, (sim_duration_ms_data / n_timesteps_data) / playback_speed
        )

    print("\n[ANIM] Animation data:")
    print(f"   Total data timesteps: {n_timesteps_data}")
    print(f"   Wire segments: {n_segments}")
    print(f"   Simulation duration recorded: {sim_duration_ms_data:.1f} ms")

    animation_frame_indices = np.arange(n_timesteps_data)
    num_animation_render_frames = n_timesteps_data
    actual_save_fps = target_video_fps

    output_path = pathlib.Path(output_filename)
    is_gif_output = output_path.suffix.lower() == ".gif"

    if save_animation and target_video_duration_s and target_video_duration_s > 0:
        num_animation_render_frames = int(target_video_duration_s * target_video_fps)
        if num_animation_render_frames <= 0:
            num_animation_render_frames = 100
        num_animation_render_frames = min(num_animation_render_frames, n_timesteps_data)
        animation_frame_indices = np.linspace(
            0, n_timesteps_data - 1, num=num_animation_render_frames, dtype=int
        )
        actual_save_fps = target_video_fps
        if is_gif_output:
            actual_save_fps = min(actual_save_fps, 20)
            print(
                f"   Subsampling for {target_video_duration_s}s GIF at {actual_save_fps} FPS (capped for GIF):"
            )
        else:
            print(
                f"   Subsampling for {target_video_duration_s}s video at {actual_save_fps} FPS:"
            )
        print(f"     Rendering {num_animation_render_frames} frames from data.")
    elif save_animation:
        actual_save_fps = 1000.0 / live_preview_interval_ms
        actual_save_fps = min(actual_save_fps, 20.0 if is_gif_output else 30.0)
        actual_save_fps = max(5.0, actual_save_fps)
        print(
            f"   Saving with FPS derived from playback_speed: {actual_save_fps:.1f} FPS"
        )

    # Figure
    plt.rcParams.update(
        {
            "font.size": 16,
            "axes.titlesize": 20,
            "axes.labelsize": 18,
            "xtick.labelsize": 16,
            "ytick.labelsize": 16,
            "legend.fontsize": 16,
            "figure.titlesize": 24,
        }
    )

    fig, (ax_wire, ax_temp) = plt.subplots(1, 2, figsize=(16, 8))
    fig.patch.set_facecolor("white")
    wire_diameter_mm = 0.2
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

    for i in range(n_segments):
        y_start = initial_positions[i]
        rect = Rectangle(
            (-visual_thickness / 2, y_start),
            visual_thickness,
            segment_len_mm,
            facecolor=cmap(norm(initial_temps[i])),
            edgecolor="black",
            linewidth=0.5,
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

    # Workpiece
    ax_wire.axhline(
        buffer_bottom_mm,
        color="gray",
        linestyle="--",
        alpha=0.8,
        linewidth=2,
        label="Workpiece Bottom",
    )
    ax_wire.axhline(
        buffer_bottom_mm + workpiece_height_mm,
        color="gray",
        linestyle="--",
        alpha=0.8,
        linewidth=2,
        label="Workpiece Top",
    )
    ax_wire.set_xlim(-visual_thickness * 4, visual_thickness * 4)
    ax_wire.set_xticks([])
    ax_wire.set_xlabel("")
    ax_wire.set_ylabel("Position along wire (mm from bottom)")
    ax_wire.set_title("Wire Temperature Field (Quickstart)")

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

    ax_temp.axhspan(
        buffer_bottom_mm,
        buffer_bottom_mm + workpiece_height_mm,
        alpha=0.2,
        color="gray",
        label="Workpiece",
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
        f"Quickstart - Sim Time: {time_ms[animation_frame_indices[0]]:.3f} ms",
        fontsize=24,
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
            f"Quickstart - Sim Time: {time_ms[actual_idx]:.3f} ms (Frame {frame_k+1}/{num_animation_render_frames})"
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
            save_dpi = 100
        else:
            if animation.writers["ffmpeg"].isAvailable():
                writer_name = "ffmpeg"
            else:
                print("⚠️ FFmpeg writer not available. Saving GIF instead.")
                output_filename = str(output_path.with_suffix(".gif"))
                writer_name = "pillow"
                save_dpi = 100
                if target_video_duration_s is not None:
                    actual_save_fps = min(target_video_fps, 20)
                else:
                    derived_fps = 1000.0 / live_preview_interval_ms
                    actual_save_fps = max(5.0, min(derived_fps, 15.0))
        print(
            f"[SAVE] Saving animation to {output_filename} (FPS: {actual_save_fps:.1f}, Writer: {writer_name}, DPI: {save_dpi})..."
        )
        ani.save(output_filename, writer=writer_name, fps=actual_save_fps, dpi=save_dpi)
        print("[OK] Animation saved successfully!")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Quickstart full-field thermal animation"
    )
    sim_group = parser.add_argument_group("Simulation")
    sim_group.add_argument(
        "--duration", type=int, default=10000, help="Simulation duration (µs)"
    )
    sim_group.add_argument(
        "--mode",
        type=str,
        choices=["position", "velocity"],
        default="position",
        help="Control mode",
    )
    sim_group.add_argument(
        "--controller",
        type=str,
        choices=["gap", "voltage"],
        default="gap",
        help="Controller type",
    )
    sim_group.add_argument(
        "--segments",
        type=int,
        default=None,
        help="Desired number of segments (auto-compute segment_len)",
    )
    sim_group.add_argument(
        "--segment-len",
        type=float,
        default=None,
        dest="segment_len",
        help="Segment length in mm (overrides --segments)",
    )
    sim_group.add_argument(
        "--workpiece-height",
        type=float,
        default=100.0,
        dest="workpiece_height",
        help="Workpiece height in mm (default: 100.0)",
    )
    sim_group.add_argument(
        "--current-mode",
        type=int,
        default=13,
        dest="current_mode",
        help="Current mode setting (default: 13 for I13)",
    )
    sim_group.add_argument(
        "--verbose", action="store_true", help="Verbose simulation logs"
    )

    load_group = parser.add_argument_group("Loading")
    load_group.add_argument(
        "--load-data", type=str, default=None, help="Path to .npz data to animate"
    )

    anim_group = parser.add_argument_group("Animation")
    anim_group.add_argument(
        "--playback-speed",
        type=float,
        default=2.0,
        help="Live preview speed multiplier",
    )
    anim_group.add_argument(
        "--save", action="store_true", help="Save animation instead of live preview"
    )
    anim_group.add_argument(
        "--out",
        type=str,
        default="quickstart_animation.gif",
        help="Output filename (.gif or .mp4)",
    )
    anim_group.add_argument(
        "--target-video-duration",
        type=float,
        default=5.0,
        help="Target duration for saved video (s)",
    )
    anim_group.add_argument(
        "--target-video-fps", type=int, default=20, help="Target FPS for saved video"
    )
    # CSV export
    anim_group.add_argument(
        "--export-csv",
        action="store_true",
        help="Export per-step positions and temperatures to CSV",
    )
    anim_group.add_argument(
        "--csv-out",
        type=str,
        default="logs/quickstart_export.csv",
        help="CSV output filepath",
    )
    anim_group.add_argument(
        "--csv-segments",
        type=int,
        default=20,
        help="Max segments to include in CSV (default: 20)",
    )

    args = parser.parse_args()

    if args.load_data:
        data_path = args.load_data
    else:
        data_path = run_quickstart_sim(
            duration_us=args.duration,
            control_mode=args.mode,
            controller=args.controller,
            out_basename=args.out,
            verbose=args.verbose,
            segments=args.segments,
            segment_len_mm=args.segment_len,
            workpiece_height=args.workpiece_height,
            current_mode=args.current_mode,
        )

    if args.export_csv:
        export_csv(data_path, args.csv_out, max_segments=args.csv_segments)

    create_animation(
        data_path,
        save_animation=args.save,
        output_filename=args.out,
        playback_speed=args.playback_speed,
        target_video_duration_s=args.target_video_duration if args.save else None,
        target_video_fps=args.target_video_fps,
    )


if __name__ == "__main__":
    main()
