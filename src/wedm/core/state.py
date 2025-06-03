# src/edm_env/core/state.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

# ──────────────────────────────────────────────────────────────────────────────
# Low-level types
# ──────────────────────────────────────────────────────────────────────────────
crater_dtype = np.dtype(
    [
        ("radius", "f4"),  # crater radius       [µm]
        ("y_position", "f4"),  # axial position      [mm]
        ("time_formed", "i4"),  # timestamp           [µs]
        ("depth", "f4"),  # crater depth        [µm]
    ]
)


# ──────────────────────────────────────────────────────────────────────────────
# EDM Process State - Only variables that change during simulation
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class EDMState:
    """
    EDM Process State Variables - Only contains state that changes during simulation.
    Configuration parameters and module parameters are handled elsewhere.
    """

    # ── Time Tracking (µs) ──
    time: int = 0  # Current time from start of simulation
    time_since_servo: int = 0  # Time since last servo action
    time_since_open_voltage: int = 0  # Time since last voltage was applied
    time_since_spark_ignition: int = 0  # Time since last spark was ignited
    time_since_spark_end: int = 0  # Time since last spark ended

    # ── Electrical State ──
    voltage: Optional[float] = None  # [V] Current voltage between wire and workpiece
    current: Optional[float] = None  # [A] Current flowing through the circuit

    # ── Generator Settings (can be changed by control actions) ──
    target_voltage: Optional[float] = None  # [V] Target voltage setting
    current_mode: Optional[str] = None  # Current mode like "I1", "I2", ..., "I19"
    OFF_time: Optional[float] = None  # [µs] OFF time setting
    ON_time: Optional[float] = None  # [µs] ON time setting

    # ── Position and Motion State ──
    workpiece_position: float = 0.0  # [µm] Current workpiece position
    wire_position: float = 0.0  # [µm] Current wire position
    wire_velocity: float = 0.0  # [µm s⁻¹] Current wire velocity
    wire_unwinding_velocity: float = 0.2  # [µm µs⁻¹] Wire unwinding speed

    # ── Wire Thermal State ──
    wire_temperature: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.float32)
    )
    time_in_critical_temp: int = 0  # Time wire has been at critical temperature
    wire_average_temperature: float | None = None  # Average temperature in cutting zone

    # ── Spark/Discharge State ──
    # Format: [state, y-location, duration]
    # state: 0=idle, 1=spark, -1=short, -2=rest
    spark_status: List[Optional[float]] = field(default_factory=lambda: [0, None, 0])

    # ── Dielectric State ──
    dielectric_conductivity: float = 0.0  # [S m⁻¹] Current dielectric conductivity
    dielectric_temperature: float = 0.0  # [K] Current dielectric temperature
    debris_concentration: float = 0.0  # [kg m⁻³] Legacy debris tracking
    dielectric_flow_rate: float = 0.0  # [m³ s⁻¹] Legacy flow rate
    ionized_channel: Optional[Tuple[float, int]] = (
        None  # (y-loc, duration) of ionized channel
    )

    # ── Enhanced Debris Tracking ──
    debris_volume: float = 0.0  # [mm³] Total volume of debris particles
    debris_density: float = 0.0  # [dimensionless] Debris density ratio (0-1)
    cavity_volume: float = 0.0  # [mm³] Total cavity volume between wire and workpiece
    flow_rate: float = 0.0  # [dimensionless] Flow condition (0-1, where 1=optimal flow)
    last_crater_volume: float = 0.0  # [mm³] Volume of last formed crater

    # ── Process Condition Flags ──
    is_short_circuit: bool = False  # True if gap is too small or debris causes short
    is_wire_broken: bool = False  # True if wire temperature exceeded breaking point
    is_wire_colliding: bool = False  # True if wire is physically touching workpiece
    is_target_distance_reached: bool = False  # True if target cutting distance reached

    # ── Servo Control State ──
    target_delta: float = 0.0  # [µm] Target position change for next servo action
    target_position: float = 500.0  # [µm] Target final position
