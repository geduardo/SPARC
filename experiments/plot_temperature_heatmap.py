#!/usr/bin/env python
# experiments/plot_temperature_heatmap.py
"""
Loads simulation log data (specifically time and wire temperature field)
and plots the wire temperature distribution as a heatmap over time,
along with the average wire temperature over time.

Usage:
    python experiments/plot_temperature_heatmap.py logs/smoke_test_wire_temps.npz
"""
import argparse
import numpy as np
import matplotlib.pyplot as plt
import pathlib


def plot_heatmap_and_average(npz_filepath: str, use_work_zone_mean: bool = True):
    """
    Loads data from an .npz file and plots:
    1. The wire temperature distribution as a heatmap over time.
    2. The average wire temperature over time.

    Args:
        npz_filepath (str): Path to the .npz file containing simulation logs.
        use_work_zone_mean (bool): If True, compute work zone mean (consistent with smoke_test.py).
                                  If False, compute full wire mean.
    """
    try:
        data = np.load(npz_filepath)
    except FileNotFoundError:
        print(f"Error: File not found at {npz_filepath}")
        return
    except Exception as e:
        print(f"Error loading .npz file: {e}")
        return

    if "time" not in data or "wire_temperature" not in data:
        print("Error: 'time' or 'wire_temperature' not found in the .npz file.")
        print(f"Available keys: {list(data.keys())}")
        return

    time_us = data["time"]
    wire_temp_field = data["wire_temperature"]  # Should be (n_timesteps, n_segments)

    if wire_temp_field.ndim != 2:
        print(
            f"Error: 'wire_temperature' data is not 2-dimensional (found {wire_temp_field.ndim} dimensions). Expected (timesteps, segments)."
        )
        return

    if len(time_us) != wire_temp_field.shape[0]:
        print(
            f"Error: Mismatch between number of time steps ({len(time_us)}) and temperature field rows ({wire_temp_field.shape[0]})."
        )
        return

    time_ms = time_us / 1000.0  # Convert time to milliseconds

    # Calculate average temperature based on user choice
    if use_work_zone_mean:
        # Calculate work zone boundaries (same logic as WireModule)
        # Standard Wire-EDM configuration
        buffer_bottom = 30.0  # mm (update this to match your configuration)
        segment_len = 0.2  # mm (update this to match your configuration)
        workpiece_height = 10.0  # mm (update this to match your configuration)

        n_segments = wire_temp_field.shape[1]
        zone_start = int(buffer_bottom // segment_len)
        zone_end = zone_start + int(workpiece_height // segment_len)
        zone_end = min(zone_end, n_segments)
        zone_start = min(zone_start, zone_end)

        actual_zone_start = min(zone_start, n_segments - 1)
        actual_zone_end = min(zone_end, n_segments)

        print(
            f"Using work zone mean: segments {actual_zone_start} to {actual_zone_end-1} ({actual_zone_end - actual_zone_start} segments)"
        )

        # Calculate work zone mean
        if actual_zone_end > actual_zone_start:
            zone_temp_field = wire_temp_field[:, actual_zone_start:actual_zone_end]
            avg_temp_over_time = np.mean(
                zone_temp_field - 273.15, axis=1
            )  # Work zone mean in Celsius
        else:
            avg_temp_over_time = np.mean(
                wire_temp_field - 273.15, axis=1
            )  # Fallback to full mean
            print("Warning: Work zone boundaries invalid, using full wire mean")
    else:
        # Original calculation: mean across ALL segments
        avg_temp_over_time = np.mean(
            wire_temp_field - 273.15, axis=1
        )  # Full wire mean in Celsius
        print(f"Using full wire mean: all {wire_temp_field.shape[1]} segments")

    n_segments = wire_temp_field.shape[1]
    segment_indices = np.arange(n_segments)

    # Create a figure with two subplots: heatmap on top, average temperature below
    fig, (ax_heatmap, ax_avg_temp) = plt.subplots(
        2,
        1,
        figsize=(10, 8),  # Adjusted figure size for two plots
        sharex=True,  # Share the x-axis (time)
        gridspec_kw={"height_ratios": [3, 1]},  # Heatmap gets more vertical space
        constrained_layout=True,  # Use constrained layout for better alignment
    )

    # Plot 1: Heatmap (on ax_heatmap)
    # Transpose wire_temp_field so segments are on y-axis and time on x-axis for imshow
    # imshow plots (M, N) data with M rows (y-axis) and N columns (x-axis)
    # Convert to Celsius for display
    wire_temp_celsius = wire_temp_field - 273.15

    im = ax_heatmap.imshow(
        wire_temp_celsius.T,
        aspect="auto",
        origin="lower",  # Place segment 0 at the bottom
        extent=[
            time_ms[0],
            time_ms[-1],
            segment_indices[0] - 0.5,
            segment_indices[-1] + 0.5,
        ],  # Match axes
        interpolation="nearest",  # Good for discrete data
        vmin=20,  # Set minimum temperature to 20 C (black)
        vmax=300,  # Set maximum temperature to 300 C (yellow/white)
        cmap="hot",  # Black -> red -> yellow/white colormap
    )
    ax_heatmap.set_xlim(time_ms[0], time_ms[-1])  # Ensure time axis is aligned

    cbar = fig.colorbar(im, ax=ax_heatmap, label="Temperature (°C)")
    ax_heatmap.set_ylabel("Wire Segment Index")

    # # Add zone boundaries to heatmap if using work zone mean
    # if (
    #     use_work_zone_mean
    #     and "actual_zone_start" in locals()
    #     and "actual_zone_end" in locals()
    # ):
    #     ax_heatmap.axhline(
    #         y=actual_zone_start - 0.5,
    #         color="red",
    #         linestyle="--",
    #         alpha=0.7,
    #         label="Work Zone",
    #     )
    #     ax_heatmap.axhline(
    #         y=actual_zone_end - 0.5, color="red", linestyle="--", alpha=0.7
    #     )
    #     ax_heatmap.legend()
    #     ax_heatmap.set_title(
    #         "Wire Temperature Distribution Over Time (Work Zone Highlighted)"
    #     )
    # else:
    #     ax_heatmap.set_title("Wire Temperature Distribution Over Time")

    # Plot 2: Average Temperature (on ax_avg_temp)
    ax_avg_temp.plot(time_ms, avg_temp_over_time, color="r", linestyle="-")

    if use_work_zone_mean:
        ax_avg_temp.set_ylabel("Work Zone Avg Temp. (°C)")
    else:
        ax_avg_temp.set_ylabel("Full Wire Avg Temp. (°C)")

    ax_avg_temp.set_xlabel("Time (ms)")  # X-label for the bottom plot (shared axis)
    ax_avg_temp.grid(True)

    # Ensure both axes share the exact same x-limits after all plotting.
    final_xlim = (time_ms[0], time_ms[-1])
    ax_heatmap.set_xlim(final_xlim)
    ax_avg_temp.set_xlim(final_xlim)  # Explicitly set for avg_temp too for robustness

    plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Plot wire temperature heatmap and average temperature from simulation log."
    )
    parser.add_argument(
        "npz_file",
        type=str,
        help="Path to the .npz file containing logged simulation data (e.g., logs/smoke_test_velocity_control.npz)",
    )
    parser.add_argument(
        "--full-wire-mean",
        action="store_true",
        help="Use full wire mean instead of work zone mean (default: work zone mean for consistency with smoke_test.py)",
    )
    args = parser.parse_args()

    npz_file_path = pathlib.Path(args.npz_file)
    if not npz_file_path.is_file():
        print(f"Error: The provided path is not a file: {npz_file_path}")
    else:
        use_work_zone = not args.full_wire_mean  # Default to work zone mean
        plot_heatmap_and_average(str(npz_file_path), use_work_zone_mean=use_work_zone)
