#!/usr/bin/env python3
"""
Plot heating curves for wire segments in a vertical orientation.
Designed for Nature-style publication quality.

Wire moves DOWNWARD: Inlet at top, Outlet at bottom.

Usage:
    python plot_heating_curve.py [--downsample N]

Options:
    --downsample N    Downsample data by factor N using rolling average (default: 1, no downsampling)
"""

import os
import glob
import csv
import argparse
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyArrowPatch
import matplotlib.patheffects as path_effects


def setup_nature_style():
    """Configure matplotlib for Nature-style publication plots."""
    plt.style.use("default")

    # Font configuration - Publication size (increased by 5-6 points)
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Arial", "Helvetica Neue", "DejaVu Sans"]
    plt.rcParams["font.size"] = 20
    plt.rcParams["axes.labelsize"] = 22
    plt.rcParams["axes.titlesize"] = 22
    plt.rcParams["xtick.labelsize"] = 20
    plt.rcParams["ytick.labelsize"] = 20
    plt.rcParams["legend.fontsize"] = 20

    # Line widths
    plt.rcParams["axes.linewidth"] = 0.8
    plt.rcParams["grid.linewidth"] = 0.4
    plt.rcParams["lines.linewidth"] = 1.2

    # Figure size - Wider to accommodate colorbar
    plt.rcParams["figure.figsize"] = (7.0, 8.0)

    # Ticks
    plt.rcParams["xtick.direction"] = "out"
    plt.rcParams["ytick.direction"] = "out"
    plt.rcParams["xtick.major.size"] = 4
    plt.rcParams["ytick.major.size"] = 4
    plt.rcParams["xtick.major.width"] = 0.8
    plt.rcParams["ytick.major.width"] = 0.8

    # Remove top and right spines for cleaner look
    plt.rcParams["axes.spines.top"] = False
    plt.rcParams["axes.spines.right"] = False


def read_heating_curve(filepath):
    """Read CSV and extract data and metadata including geometry."""
    metadata = {}
    data = {"time_ms": [], "temp_c": []}

    with open(filepath, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue

            if row[0].startswith("#"):
                content = row[0].strip("# ").strip()
                if ":" in content:
                    key, val = content.split(":", 1)
                    val = val.strip()

                    # Parse metadata
                    if "Transit Time" in key:
                        metadata["transit_time_ms"] = float(val)
                    elif "Inlet Time" in key:
                        metadata["inlet_time_us"] = float(val)
                    elif "Segment Number" in key:
                        metadata["segment_number"] = int(val)
                    # Geometry metadata
                    elif "Total Wire Length" in key:
                        metadata["total_length_mm"] = float(val)
                    elif "Workpiece Height" in key:
                        metadata["workpiece_height_mm"] = float(val)
                    elif "Buffer Bottom" in key:
                        metadata["buffer_bottom_mm"] = float(val)
                    elif "Buffer Top" in key:
                        metadata["buffer_top_mm"] = float(val)
                    elif "Pos Inlet" in key:
                        metadata["pos_inlet"] = float(val)
                    elif "Pos Contact Lower" in key:
                        metadata["pos_contact_lower"] = float(val)
                    elif "Pos Workpiece Start" in key:
                        metadata["pos_workpiece_start"] = float(val)
                    elif "Pos Workpiece End" in key:
                        metadata["pos_workpiece_end"] = float(val)
                    elif "Pos Contact Upper" in key:
                        metadata["pos_contact_upper"] = float(val)
                    elif "Pos Outlet" in key:
                        metadata["pos_outlet"] = float(val)
                continue

            if row[0].startswith("Time_Since"):
                continue

            try:
                data["time_ms"].append(float(row[0]))
                data["temp_c"].append(float(row[1]))
            except ValueError:
                continue

    return data, metadata


def downsample_data(times, temps, factor):
    """Downsample data using rolling average."""
    if factor <= 1:
        return times, temps

    n = len(times)
    n_new = n // factor

    times_ds = np.zeros(n_new)
    temps_ds = np.zeros(n_new)

    for i in range(n_new):
        start = i * factor
        end = start + factor
        times_ds[i] = np.mean(times[start:end])
        temps_ds[i] = np.mean(temps[start:end])

    return times_ds, temps_ds


def get_temperature_colormap():
    """Get the 'hot' colormap for temperature visualization."""
    return plt.cm.hot


def plot_heating_curve(filepath, output_dir, downsample_factor=1):
    """Create a vertical heating curve plot with wire moving downward."""
    filename = os.path.basename(filepath)
    name_no_ext = os.path.splitext(filename)[0]

    data, metadata = read_heating_curve(filepath)

    if not data["time_ms"]:
        print(f"No data found in {filepath}")
        return

    # Read geometry from metadata, with fallback defaults for old CSV files
    TOTAL_LENGTH_MM = metadata.get("total_length_mm", 160.0)
    POS_INLET = metadata.get("pos_inlet", 0.0)
    POS_CONTACT_LOWER = metadata.get(
        "pos_contact_lower", 20.0
    )  # Lower contact (closer to inlet)
    POS_WORKPIECE_START = metadata.get("pos_workpiece_start", 30.0)
    POS_WORKPIECE_END = metadata.get("pos_workpiece_end", 130.0)
    POS_CONTACT_UPPER = metadata.get(
        "pos_contact_upper", 140.0
    )  # Upper contact (closer to outlet)
    POS_OUTLET = metadata.get("pos_outlet", TOTAL_LENGTH_MM)

    transit_time = metadata.get("transit_time_ms", data["time_ms"][-1])

    # Convert position (mm) to time (ms)
    def pos_to_time(pos_mm):
        return (pos_mm / TOTAL_LENGTH_MM) * transit_time

    # Create figure with space for colorbar
    fig, ax = plt.subplots()

    # Color palette
    workpiece_color = "#2C3E50"
    contact_color = "#3498DB"

    # Calculate reference point: Upper contact (time and position = 0)
    # The UPPER contact (physically at top, labeled "Upper Contact") is at POS_CONTACT_LOWER in the CSV
    # This is the reference point (0 in time and position)
    t_upper_contact_ref = pos_to_time(POS_CONTACT_LOWER)  # Upper contact = 0

    # Get raw data and apply downsampling
    temps_raw = np.array(data["temp_c"])
    times_raw = np.array(data["time_ms"])

    # Downsample if requested
    if downsample_factor > 1:
        times_raw, temps_raw = downsample_data(times_raw, temps_raw, downsample_factor)

    # Shift all times so upper contact = 0 (times before are negative)
    temps = temps_raw
    times = times_raw - t_upper_contact_ref  # Shifted times (upper contact = 0)

    # Create line segments with shifted times
    points = np.array([temps, times]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)

    # Normalize temperature to 0-1 range (20°C to 500°C)
    temp_min_cmap = 20.0
    temp_max_cmap = 500.0
    norm = plt.Normalize(temp_min_cmap, temp_max_cmap)

    # Use 'hot' colormap
    cmap = get_temperature_colormap()

    # Create LineCollection with colors based on temperature
    lc = LineCollection(segments, cmap=cmap, norm=norm, linewidth=1.8, zorder=10)
    lc.set_array(temps[:-1])  # Color by temperature
    ax.add_collection(lc)

    # Calculate Y limits relative to UPPER contact (POS_CONTACT_LOWER in CSV, which is at 0):
    # In the CSV naming convention:
    #   - POS_CONTACT_LOWER (e.g. 20mm) is physically the UPPER contact (closer to inlet, TOP of plot) = REFERENCE (0)
    #   - POS_CONTACT_UPPER (e.g. 60mm) is physically the LOWER contact (closer to outlet, BOTTOM of plot)
    #
    # Y limits:
    #   - 10mm BEFORE upper contact (toward inlet) = -10mm relative (TOP of plot)
    #   - 10mm AFTER lower contact (toward outlet) = (POS_CONTACT_UPPER + 10) - POS_CONTACT_LOWER (BOTTOM of plot)

    # Relative positions (POS_CONTACT_LOWER = upper contact = 0)
    y_min_mm = -10.0  # 10mm before upper contact (toward inlet, TOP of plot)
    y_max_mm = (
        POS_CONTACT_UPPER + 10.0
    ) - POS_CONTACT_LOWER  # 10mm after lower contact (toward outlet, BOTTOM of plot)

    # Convert to time (using shifted time scale)
    t_y_min = (
        pos_to_time(max(0, POS_CONTACT_LOWER - 10.0)) - t_upper_contact_ref
    )  # 10mm before upper contact
    t_y_max = (
        pos_to_time(POS_CONTACT_UPPER + 10.0) - t_upper_contact_ref
    )  # 10mm after lower contact

    # Invert Y axis so wire moves downward visually
    # Top of plot = negative time/position (before upper contact), Bottom = positive (after upper contact)
    ax.set_ylim(t_y_max, t_y_min)

    # Get x limits for positioning elements
    temp_min = min(temps)
    temp_max = max(temps)
    temp_range = max(temp_max - temp_min, 50)  # Minimum range of 50°C
    x_margin = temp_range * 0.15
    ax.set_xlim(temp_min - x_margin, temp_max + x_margin * 1.5)

    x_left, x_right = ax.get_xlim()

    # Calculate event times relative to upper contact (shifted)
    # Upper contact (POS_CONTACT_LOWER in CSV) = 0
    t_upper_contact = 0.0  # Upper contact is reference (0)
    t_workpiece_start = pos_to_time(POS_WORKPIECE_START) - t_upper_contact_ref
    t_workpiece_end = pos_to_time(POS_WORKPIECE_END) - t_upper_contact_ref
    t_lower_contact = (
        pos_to_time(POS_CONTACT_UPPER) - t_upper_contact_ref
    )  # Lower contact (POS_CONTACT_UPPER in CSV)

    # --- Deionized Water Zone (faint blue, everywhere except workpiece) ---
    diwater_color = "#4A90D9"  # Light blue for deionized water

    # Above workpiece (from top of plot to workpiece start)
    ax.axhspan(t_y_min, t_workpiece_start, color=diwater_color, alpha=0.05, zorder=0)
    # Below workpiece (from workpiece end to bottom of plot)
    ax.axhspan(t_workpiece_end, t_y_max, color=diwater_color, alpha=0.05, zorder=0)

    # --- Workpiece Zone (shaded region) ---
    ax.axhspan(
        t_workpiece_start, t_workpiece_end, color=workpiece_color, alpha=0.08, zorder=1
    )

    # Workpiece boundaries
    ax.axhline(
        t_workpiece_start,
        color=workpiece_color,
        linestyle="-",
        alpha=0.4,
        linewidth=1.0,
        zorder=2,
    )
    ax.axhline(
        t_workpiece_end,
        color=workpiece_color,
        linestyle="-",
        alpha=0.4,
        linewidth=1.0,
        zorder=2,
    )

    # --- Electrical Contacts (dashed lines, dark grey) ---
    contact_line_color = "#444444"  # Dark grey for contact lines
    ax.axhline(
        t_upper_contact,
        color=contact_line_color,
        linestyle="--",
        alpha=0.7,
        linewidth=1.2,
        zorder=2,
    )
    ax.axhline(
        t_lower_contact,
        color=contact_line_color,
        linestyle="--",
        alpha=0.7,
        linewidth=1.2,
        zorder=2,
    )

    # --- Labels on the RIGHT side of the plot ---
    label_x = x_right - (x_right - x_left) * 0.02

    # Helper function for labels with background
    def add_label(y_pos, text, color, fontsize=10, va="center", bold=False):
        weight = "bold" if bold else "normal"
        txt = ax.text(
            label_x,
            y_pos,
            text,
            fontsize=fontsize,
            fontweight=weight,
            color=color,
            ha="right",
            va=va,
            zorder=20,
        )
        txt.set_path_effects(
            [
                path_effects.Stroke(linewidth=2, foreground="white"),
                path_effects.Normal(),
            ]
        )
        return txt

    # Y range for offset calculations (note: t_y_max > t_y_min due to inversion)
    y_range = abs(t_y_max - t_y_min)

    # Contact label color (dark grey)
    contact_label_color = "#444444"

    # Upper contact is at 0 (reference), appears at TOP of plot
    # Lower contact is at positive time, appears at BOTTOM of plot
    add_label(
        t_upper_contact + y_range * 0.025,
        "Upper Contact",
        contact_label_color,
        fontsize=20,
    )

    # Workpiece zone label (centered in zone)
    t_workpiece_center = t_workpiece_start + 7.5
    add_label(t_workpiece_center, "WORKPIECE", workpiece_color, fontsize=16, bold=True)

    add_label(
        t_lower_contact - y_range * 0.025,
        "Lower Contact",
        contact_label_color,
        fontsize=20,
    )

    # --- Add arrow indicating wire unwinding direction (top center, moved down slightly) ---
    arrow_x = x_left + (x_right - x_left) * 0.5  # Center horizontally
    # Move arrow down by converting pixels to time units (roughly 0.015 of y_range ≈ 5-10 pixels)
    arrow_y_start = t_y_min + y_range * 0.015  # Moved down from top
    arrow_y_end = t_y_min + y_range * 0.095  # Moved down accordingly

    # Use FancyArrowPatch for sharper arrow
    arrow = FancyArrowPatch(
        (arrow_x, arrow_y_start),
        (arrow_x, arrow_y_end),
        arrowstyle="-|>",
        mutation_scale=25,  # Larger head for sharper look
        linewidth=3.5,
        color="#444444",
        zorder=15,
        shrinkA=0,
        shrinkB=0,  # No shrinking for sharper appearance
    )
    ax.add_patch(arrow)

    # Text to the LEFT of the arrow
    ax.text(
        arrow_x - (x_right - x_left) * 0.03,
        (arrow_y_start + arrow_y_end) / 2,
        "Unwinding\ndirection",
        fontsize=20,
        color="#444444",
        ha="right",
        va="center",
        fontweight="medium",
    )

    # --- Axis Labels ---
    ax.set_xlabel("Temperature (°C)", fontsize=22, fontweight="medium")
    ax.set_ylabel("Time since upper contact (ms)", fontsize=22, fontweight="medium")

    # --- Secondary Y-axis for Position (relative to upper contact) ---
    ax_pos = ax.twinx()
    ax_pos.set_ylim(
        y_max_mm, y_min_mm
    )  # Match inverted scale in mm (relative to upper contact)
    ax_pos.set_ylabel(
        "Position relative to upper contact (mm)",
        fontsize=22,
        fontweight="medium",
        rotation=270,
        labelpad=25,
    )
    ax_pos.spines["top"].set_visible(False)

    # --- Colorbar for temperature (placed further right) ---
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])

    # Create colorbar with more padding to avoid overlap with right Y axis
    cbar_ax = fig.add_axes(
        [0.92, 0.25, 0.03, 0.5]
    )  # [left, bottom, width, height] - moved further right
    cbar = fig.colorbar(sm, cax=cbar_ax)
    cbar.set_label("Temperature (°C)", fontsize=20)
    cbar.ax.tick_params(labelsize=18)

    # Adjust layout - leave more space for colorbar on right
    plt.subplots_adjust(left=0.12, right=0.72, top=0.95, bottom=0.08)

    # Save
    out_path = os.path.join(output_dir, f"plot_{name_no_ext}.png")
    out_path_pdf = os.path.join(output_dir, f"plot_{name_no_ext}.pdf")

    plt.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.savefig(out_path_pdf, bbox_inches="tight", facecolor="white")
    print(f"  Saved: {out_path}")
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Plot heating curves for wire segments."
    )
    parser.add_argument(
        "--downsample",
        type=int,
        default=1,
        help="Downsample data by factor N using rolling average (default: 1, no downsampling)",
    )
    args = parser.parse_args()

    input_dir = "heating_curves"
    output_dir = "heating_curves_plots"

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    setup_nature_style()

    csv_files = sorted(glob.glob(os.path.join(input_dir, "*.csv")))
    print(f"Found {len(csv_files)} CSV files in {input_dir}/")
    if args.downsample > 1:
        print(f"Downsampling by factor {args.downsample}")
    print()

    for csv_file in csv_files:
        print(f"Processing {os.path.basename(csv_file)}...")
        plot_heating_curve(csv_file, output_dir, downsample_factor=args.downsample)

    print()
    print(f"All plots saved to {output_dir}/")


if __name__ == "__main__":
    main()
