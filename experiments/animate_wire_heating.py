#!/usr/bin/env python
# experiments/animate_wire_heating.py
"""
Loads simulation log data (specifically time and wire temperature field)
and creates an animation of the wire heating up over time.

Usage:
    python experiments/animate_wire_heating.py logs/smoke_test_wire_temps.npz
"""
import argparse
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import pathlib


def animate_wire(
    npz_filepath: str,
    save_animation: bool = False,
    output_filename: str = "wire_heating_animation.mp4",
):
    """
    Loads data from an .npz file and creates an animation of the wire temperature.

    Args:
        npz_filepath (str): Path to the .npz file containing simulation logs.
        save_animation (bool): Whether to save the animation to a file.
        output_filename (str): Filename for the saved animation.
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
    wire_temp_field_k = data[
        "wire_temperature"
    ]  # Should be (n_timesteps, n_segments), assumed Kelvin

    if wire_temp_field_k.ndim != 2:
        print(
            f"Error: 'wire_temperature' data is not 2-dimensional (found {wire_temp_field_k.ndim} dimensions). Expected (timesteps, segments)."
        )
        return

    if len(time_us) != wire_temp_field_k.shape[0]:
        print(
            f"Error: Mismatch between number of time steps ({len(time_us)}) and temperature field rows ({wire_temp_field_k.shape[0]})."
        )
        return

    # Convert temperature data from Kelvin (assumed) to Celsius for plotting
    wire_temp_field_c = wire_temp_field_k - 273.15

    time_ms = time_us / 1000.0  # Convert time to milliseconds
    n_timesteps, n_segments = (
        wire_temp_field_c.shape
    )  # Shape is the same for K or C versions

    # Calculate animation interval and FPS for real-time playback
    # Default to ~30 FPS if real-time calculation isn't possible or meaningful
    default_interval_ms = 1000.0 / 30.0  # approx 33.33 ms
    target_interval_ms = default_interval_ms
    target_fps = 30.0

    if n_timesteps > 0:
        # Calculate total duration of the simulation data in milliseconds
        # This is the time from the first data point to the last data point
        total_simulation_duration_ms = time_ms[n_timesteps - 1] - time_ms[0]

        if total_simulation_duration_ms > 0:
            # To make the animation's total playback time match total_simulation_duration_ms,
            # each of the n_timesteps frames should be displayed for this duration.
            calculated_interval = total_simulation_duration_ms / n_timesteps
            if calculated_interval > 0:  # Ensure interval is positive
                target_interval_ms = calculated_interval
                target_fps = 1000.0 / target_interval_ms
            # If calculated_interval is not positive, defaults are used.
        # If total_simulation_duration_ms is 0 (e.g., n_timesteps=1 or all time points are identical),
        # target_interval_ms and target_fps remain at their default values (e.g. 30fps for a single frame).
    # If n_timesteps is 0, defaults are used.

    # Physical dimensions based on src/wedm/modules/wire.py and src/wedm/envs/wire_edm.py
    actual_workpiece_height_mm = 50.0  # From wire_edm.py: env.workpiece_height
    buffer_bottom_mm = 30.0  # From wire.py: buffer_len_bottom
    buffer_top_mm = 20.0  # From wire.py: buffer_len_top
    total_simulated_wire_length_mm = (
        buffer_bottom_mm + actual_workpiece_height_mm + buffer_top_mm
    )  # Should be 120mm

    wire_diameter_mm = 0.25  # From wire_edm.py

    # Plot area dimensions
    # plot_width_mm = 20.0 # Removed - xlim will be based on 10x wire diameter
    y_padding_mm = 10.0

    fig, ax = plt.subplots(
        figsize=(10, 10),  # Significantly wider figure
        constrained_layout=True,
    )
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    temp_min_k = 20 + 273.15  # Defines the plotting range's lower bound in Kelvin
    temp_max_k = 300 + 273.15  # Defines the plotting range's upper bound in Kelvin
    temp_min_c = 20  # Min temp for color scale in Celsius
    temp_max_c = 200  # Max temp for color scale in Celsius

    # Set physical limits for the plot axes
    # X-axis will be 10x the wire diameter
    xlim_half_width = (
        wire_diameter_mm / 2
    ) * 50  # Increased multiplier for much wider x-axis view
    ax.set_xlim(-xlim_half_width, xlim_half_width)
    ax.set_ylim(-y_padding_mm, total_simulated_wire_length_mm + y_padding_mm)

    # Extent for imshow: maps the n_segments of data to the full simulated wire length [0, total_simulated_wire_length_mm]
    # Make the wire appear thicker in the visualization
    visual_thickness_factor = 10.0
    displayed_wire_visual_width_mm = wire_diameter_mm * visual_thickness_factor
    wire_x_min = -displayed_wire_visual_width_mm / 2
    wire_x_max = displayed_wire_visual_width_mm / 2
    # The wire data (n_segments) spans from y=0 to y=total_simulated_wire_length_mm on the plot
    img_extent = [wire_x_min, wire_x_max, 0, total_simulated_wire_length_mm]

    img = ax.imshow(
        wire_temp_field_c[0, :].reshape(n_segments, 1),  # Use Celsius data
        cmap="hot",
        origin="lower",  # Bottom of data array is at y=0 of img_extent
        vmin=temp_min_c,  # Use Celsius min for the scale
        vmax=temp_max_c,  # Use Celsius max for the scale
        extent=img_extent,
        interpolation="nearest",
    )

    # Add horizontal lines for the actual workpiece boundaries within the total simulated length
    workpiece_bottom_y = buffer_bottom_mm
    workpiece_top_y = buffer_bottom_mm + actual_workpiece_height_mm
    ax.axhline(
        workpiece_bottom_y,
        color="red",
        linestyle="--",
        linewidth=1.0,
        label="Workpiece Zone",
    )
    ax.axhline(workpiece_top_y, color="red", linestyle="--", linewidth=1.0)
    # Add a legend for the workpiece zone lines, but only add one label to avoid duplicates
    handles, labels = ax.get_legend_handles_labels()
    if handles:  # Check if legend items exist to prevent errors if no labels are set
        ax.legend(handles=[handles[0]], loc="upper right", fontsize="small")

    ax.set_xlabel("Position (mm)")
    ax.set_ylabel("Position (mm)")

    cbar = fig.colorbar(
        img,
        ax=ax,
        orientation="vertical",
        label="Temperature (°C)",
        shrink=0.7,  # Shrink colorbar a bit
    )

    title_text_obj = ax.set_title(f"Time: {time_ms[0]:.2f} ms", fontsize=10)

    def update(frame_index):
        current_temps_c = wire_temp_field_c[frame_index, :].reshape(
            n_segments, 1
        )  # Use Celsius data
        img.set_data(current_temps_c)
        title_text_obj.set_text(f"Time: {time_ms[frame_index]:.2f} ms")
        return [img, title_text_obj]

    # Create the animation
    ani = animation.FuncAnimation(
        fig,
        update,
        frames=n_timesteps,
        blit=True,  # blit=True means only re-draw the parts that have changed for performance
        interval=target_interval_ms,  # Use calculated interval for display
    )

    if save_animation:
        try:
            output_path = pathlib.Path(output_filename)
            writer_name = None
            if output_path.suffix.lower() == ".gif":
                writer_name = "pillow"  # PillowWriter for GIFs
            else:  # Default to ffmpeg for .mp4 or other video formats
                writer_name = "ffmpeg"

            data_duration_s = 0.0
            if n_timesteps > 1:
                data_duration_s = (time_ms[n_timesteps - 1] - time_ms[0]) / 1000.0
            elif n_timesteps == 1 and len(time_ms) > 0:  # Single point in time
                data_duration_s = 0.0

            expected_animation_duration_s = 0.0
            if target_interval_ms > 0 and n_timesteps > 0:
                expected_animation_duration_s = (
                    n_timesteps * target_interval_ms
                ) / 1000.0

            print(
                f"Saving animation to {output_filename} using writer: {writer_name}..."
            )
            print(f"Target FPS for saved file: {target_fps:.2f}")
            print(f"Target interval for live display: {target_interval_ms:.2f} ms")
            print(f"Data duration from log: {data_duration_s:.2f} s")
            print(
                f"Expected animation duration in saved file: {expected_animation_duration_s:.2f} s"
            )

            ani.save(output_filename, writer=writer_name, fps=target_fps)
            print("Animation saved.")
            print(
                "\nNote: Live preview (`plt.show()`) might run slower or faster than real-time"
            )
            print(
                "due to system performance and rendering overhead. The saved animation file"
            )
            print(
                f"({output_filename}) should have the correct duration based on the target FPS."
            )

        except Exception as e:
            print(f"Error saving animation: {e}")
            print("Make sure ffmpeg is installed and in your system's PATH.")
            print("Displaying animation instead.")
            plt.show()
    else:
        plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Animate wire temperature from simulation log."
    )
    parser.add_argument(
        "npz_file",
        type=str,
        help="Path to the .npz file containing logged simulation data (e.g., logs/smoke_test_wire_temps.npz)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save the animation to a video file instead of displaying it.",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="wire_heating_animation.mp4",
        help="Output filename for the saved animation (e.g., animation.mp4 or animation.gif). Requires --save.",
    )
    args = parser.parse_args()

    npz_file_path = pathlib.Path(args.npz_file)
    if not npz_file_path.is_file():
        print(f"Error: The provided path is not a file: {npz_file_path}")
    else:
        animate_wire(
            str(npz_file_path), save_animation=args.save, output_filename=args.out
        )
