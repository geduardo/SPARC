from __future__ import annotations


def build_realtime_summary(
    sim_time_us: int,
    wall_time_s: float,
    *,
    label: str = "Simulation",
) -> list[str]:
    """Return human-readable runtime vs realtime summary lines."""
    if wall_time_s <= 0.0:
        return [f"{label}: completed instantly."]

    if sim_time_us <= 0:
        return [
            f"{label}: completed in {wall_time_s:.2f} s with no simulated time elapsed."
        ]

    sim_time_s = sim_time_us / 1_000_000.0
    realtime_factor = sim_time_s / wall_time_s
    wall_seconds_per_sim_second = wall_time_s / sim_time_s

    lines = [
        f"{label}: simulated {sim_time_us:,} us ({sim_time_us / 1_000.0:.2f} ms) in {wall_time_s:.2f} s.",
        f"{label} performance: {realtime_factor:.3f}x realtime.",
        f"{label} wall-clock seconds per simulated second: {wall_seconds_per_sim_second:.3f}.",
    ]

    if wall_seconds_per_sim_second >= 1.0:
        lines.append(
            f"That is {wall_seconds_per_sim_second:.3f}x slower than realtime."
        )
    else:
        lines.append(
            f"That is {1.0 / wall_seconds_per_sim_second:.3f}x faster than realtime."
        )

    return lines


def print_realtime_summary(
    sim_time_us: int,
    wall_time_s: float,
    *,
    label: str = "Simulation",
) -> None:
    """Print runtime vs realtime summary lines."""
    for line in build_realtime_summary(sim_time_us, wall_time_s, label=label):
        print(line)
