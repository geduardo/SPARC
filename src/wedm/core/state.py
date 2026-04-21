from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

crater_dtype = np.dtype(
    [
        ("radius", "f4"),
        ("y_position", "f4"),
        ("time_formed", "i4"),
        ("depth", "f4"),
    ]
)


@dataclass
class EDMState:
    """Complete simulator runtime state for one EDM episode."""

    # Time tracking [us]
    time: int = 0  # Absolute simulated time since episode start.
    time_since_servo: int = 0  # Time since the last servo/control update.
    time_since_open_voltage: int = 0  # Time since open-circuit voltage was applied.
    time_since_spark_ignition: int = 0  # Age of the active discharge, if any.
    time_since_spark_end: int = 0  # Time elapsed since the last discharge ended.

    # Electrical state
    voltage: float = 0.0  # Instantaneous gap voltage [V].
    current: float = 0.0  # Instantaneous discharge/circuit current [A].

    # Generator settings
    target_voltage: Optional[float] = None  # Requested generator voltage setpoint [V].
    current_mode: Optional[str] = None  # Active current mode label, e.g. "I4".
    OFF_time: Optional[float] = None  # Generator off-time command [us].
    ON_time: Optional[float] = None  # Generator on-time command [us].

    # Position and motion state
    workpiece_position: float = 0.0  # Current workpiece/gap-side position [um].
    wire_position: float = 0.0  # Current wire lateral position [um].
    wire_velocity: float = 0.0  # Current wire lateral velocity [um/s].
    wire_unwinding_velocity: float = 0.2  # Axial wire feed speed [um/us].

    # Wire thermal state
    wire_temperature: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.float32)
    )  # Per-segment wire temperature field [K].
    wire_damage: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.float32)
    )  # Per-segment accumulated wire damage [-].
    wire_max_damage: float = 0.0  # Maximum damage value across all wire segments [-].
    wire_average_temperature: float | None = None  # Reported cutting-zone mean temperature [K].
    wire_last_zone_mean: float | None = None  # Last cached zone-mean temperature used by the wire model [K].
    wire_head_idx: int = 0  # Diagnostic head index for wire-position views.
    wire_offset_mm: float = 0.0  # Axial offset applied to wire material positions [mm].
    wire_material_positions_mm: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.float64)
    )  # Per-segment axial material positions for logging/visualization [mm].

    # Spark/discharge state
    # Format: [state, y-location, duration]
    # state: 0=idle, 1=spark, -1=short, -2=rest
    spark_status: List[Optional[float]] = field(
        default_factory=lambda: [0, None, 0]
    )  # Discharge mode, location [mm], and duration [us].

    # Dielectric state
    dielectric_conductivity: float = 0.0  # Effective dielectric conductivity [S/m].
    dielectric_temperature: float = 0.0  # Dielectric temperature [K].
    debris_concentration: float = 0.0  # Legacy debris concentration observable.
    dielectric_flow_rate: float = 0.0  # Legacy dielectric flow-rate observable [m^3/s].
    ionized_channel: Optional[Tuple[float, int]] = None  # Active ionized channel: (location [mm], remaining duration [us]).

    # Enhanced debris tracking
    debris_volume: float = 0.0  # Total debris volume suspended in the gap [mm^3].
    debris_density: float = 0.0  # Debris fill ratio inside the cavity [-].
    cavity_volume: float = 0.0  # Available gap/cavity volume around the wire [mm^3].
    flow_rate: float = 0.0  # Dimensionless flow-condition indicator [-].
    last_crater_volume: float = 0.0  # Volume removed by the most recent crater event [mm^3].

    # Runtime memory needed to keep the simulator Markovian
    dielectric_last_gap_um: float = -1.0  # Last gap value used by dielectric cache invalidation [um].
    dielectric_last_debris_density: float = -1.0  # Last debris density used by dielectric cache invalidation [-].
    ignition_random_short_remaining_us: int = 0  # Remaining forced-random-short duration [us].
    ignition_debris_short_remaining_us: int = 0  # Remaining debris-induced short duration [us].
    mechanics_prev_accel: float = 0.0  # Previous mechanics acceleration for jerk limiting [um/s^2].
    wire_last_flow_condition: float | None = None  # Last flow condition used to refresh wire convection coefficients [-].
    wire_zone_mean_counter: int = 0  # Steps since the last wire zone-mean recomputation.

    # Process condition flags
    is_short_circuit: bool = False  # True when the process is in short-circuit regime.
    is_wire_broken: bool = False  # True once any wire segment reaches failure.
    is_wire_colliding: bool = False  # True when the wire physically contacts the workpiece.
    is_target_distance_reached: bool = False  # True when the cut target distance is achieved.

    # Servo control state
    target_delta: float = 0.0  # Requested servo change for the next control action [um].
    target_position: float = 500.0  # Target final workpiece position/distance [um].
