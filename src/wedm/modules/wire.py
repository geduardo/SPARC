# src/wedm/modules/wire.py
from __future__ import annotations

import math
import numpy as np
from numba import njit
from dataclasses import dataclass

from ..core.module import EDMModule
from ..core.state import EDMState
from ..core.material_db import get_material_db


_UNIVERSAL_GAS_CONSTANT_J_PER_MOL_K = 8.314


# ──────────────────────────────────────────────────────────────────────────────
# Wire Module Parameters - Defined within module
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class WireModuleParameters:
    """Wire module specific parameters."""

    # ── Thermal Model Parameters ──
    buffer_len_bottom: float = 30.0  # [mm] Buffer length below workpiece
    buffer_len_top: float = 30.0  # [mm] Buffer length above workpiece
    segment_len: float = 0.2  # [mm] Length of each wire segment for thermal model
    spool_T: float = 293.15  # [K] Temperature of wire spool (boundary condition)

    # ── Electrical Contact Parameters ──
    contact_offset_bottom: float = (
        10.0  # [mm] Distance of lower contact below workpiece
    )
    contact_offset_top: float = 10.0  # [mm] Distance of upper contact above workpiece

    # ── Machine Settings ──
    wire_tension_force: float = 12.0  # [N] Wire tension force

    # ── Heat Transfer Parameters ──
    base_convection_coefficient: float = 10000  # [W/m²·K] Base convection coefficient
    plasma_efficiency: float = (
        0.25  # [dimensionless] Fraction of electrical power converted to heat in plasma
    )
    convection_velocity_factor: float = (
        0.5  # [dimensionless] Factor for velocity enhancement of convection
    )
    convection_flow_enhancement: float = (
        1.0  # [dimensionless] Flow enhancement factor for convection
    )

    # ── Computational Parameters ──
    compute_zone_mean: bool = False  # Whether to compute zone mean temperature
    zone_mean_interval: int = 100  # Compute zone mean every N steps for efficiency

    # ── Feature Flags ──
    moving_segments: bool = (
        True  # Use circular buffer movement model instead of advection
    )


@njit(cache=True, fastmath=True)
def accumulate_damage(
    damage: np.ndarray,
    temperature: np.ndarray,
    threshold_k: float,
    stress_term_dt: float,
    activation_scale: float,
) -> float:
    """Update accumulated damage in-place and return the new maximum damage."""
    max_damage = 0.0

    for i in range(temperature.shape[0]):
        current_damage = damage[i]
        temp = temperature[i]
        if temp > threshold_k:
            current_damage += stress_term_dt * np.exp(activation_scale / temp)
            damage[i] = current_damage

        if current_damage > max_damage:
            max_damage = current_damage

    return max_damage


@njit(cache=True, fastmath=True)
def apply_thermal_core_inplace(
    temperature: np.ndarray,
    dT_dt: np.ndarray,
    conv_loss_coeff: np.ndarray,
    k_cond_coeff: float,
    temp_update_factor: float,
    dielectric_temp: float,
    temp_ref: float,
    alpha_rho: float,
    bottom_start: int,
    bottom_end: int,
    bottom_joule_factor: float,
    top_start: int,
    top_end: int,
    top_joule_factor: float,
    plasma_idx: int,
    plasma_heat: float,
    spool_temp: float,
) -> None:
    """Apply one fused thermal update step in-place using preallocated buffers."""
    n_segments = temperature.shape[0]
    if n_segments == 0:
        return

    dT_dt[0] = 0.0

    if n_segments > 1:
        for i in range(1, n_segments - 1):
            temp = temperature[i]
            dT_dt[i] = (
                k_cond_coeff * (temperature[i - 1] - 2.0 * temp + temperature[i + 1])
                - conv_loss_coeff[i] * (temp - dielectric_temp)
            )

        temp_last = temperature[n_segments - 1]
        dT_dt[n_segments - 1] = (
            k_cond_coeff * (temperature[n_segments - 2] - temp_last)
            - conv_loss_coeff[n_segments - 1] * (temp_last - dielectric_temp)
        )

    if bottom_joule_factor != 0.0:
        for i in range(bottom_start, bottom_end):
            dT_dt[i] += bottom_joule_factor * (
                1.0 + alpha_rho * (temperature[i] - temp_ref)
            )

    if top_joule_factor != 0.0:
        for i in range(top_start, top_end):
            dT_dt[i] += top_joule_factor * (
                1.0 + alpha_rho * (temperature[i] - temp_ref)
            )

    if 0 <= plasma_idx < n_segments:
        dT_dt[plasma_idx] += plasma_heat

    for i in range(1, n_segments):
        temperature[i] += dT_dt[i] * temp_update_factor

    temperature[0] = spool_temp


@njit(cache=True, fastmath=True)
def apply_thermal_damage_core_inplace(
    temperature: np.ndarray,
    damage: np.ndarray,
    dT_dt: np.ndarray,
    conv_loss_coeff: np.ndarray,
    k_cond_coeff: float,
    temp_update_factor: float,
    dielectric_temp: float,
    temp_ref: float,
    alpha_rho: float,
    bottom_start: int,
    bottom_end: int,
    bottom_joule_factor: float,
    top_start: int,
    top_end: int,
    top_joule_factor: float,
    plasma_idx: int,
    plasma_heat: float,
    spool_temp: float,
    threshold_k: float,
    stress_term_dt: float,
    activation_scale: float,
) -> float:
    """Apply one fused thermal update and damage accumulation step in-place."""
    n_segments = temperature.shape[0]
    if n_segments == 0:
        return 0.0

    dT_dt[0] = 0.0

    if n_segments > 1:
        for i in range(1, n_segments - 1):
            temp = temperature[i]
            dT_dt[i] = (
                k_cond_coeff * (temperature[i - 1] - 2.0 * temp + temperature[i + 1])
                - conv_loss_coeff[i] * (temp - dielectric_temp)
            )

        temp_last = temperature[n_segments - 1]
        dT_dt[n_segments - 1] = (
            k_cond_coeff * (temperature[n_segments - 2] - temp_last)
            - conv_loss_coeff[n_segments - 1] * (temp_last - dielectric_temp)
        )

    if bottom_joule_factor != 0.0:
        for i in range(bottom_start, bottom_end):
            dT_dt[i] += bottom_joule_factor * (
                1.0 + alpha_rho * (temperature[i] - temp_ref)
            )

    if top_joule_factor != 0.0:
        for i in range(top_start, top_end):
            dT_dt[i] += top_joule_factor * (
                1.0 + alpha_rho * (temperature[i] - temp_ref)
            )

    if 0 <= plasma_idx < n_segments:
        dT_dt[plasma_idx] += plasma_heat

    max_damage = 0.0
    for i in range(1, n_segments):
        temperature[i] += dT_dt[i] * temp_update_factor

        current_damage = damage[i]
        temp = temperature[i]
        if temp > threshold_k:
            current_damage += stress_term_dt * np.exp(activation_scale / temp)
            damage[i] = current_damage

        if current_damage > max_damage:
            max_damage = current_damage

    temperature[0] = spool_temp
    current_damage = damage[0]
    if spool_temp > threshold_k:
        current_damage += stress_term_dt * np.exp(activation_scale / spool_temp)
        damage[0] = current_damage
    if current_damage > max_damage:
        max_damage = current_damage

    return max_damage


@njit(cache=True, fastmath=True)
def resolve_discharge_partition(
    spark_state: int,
    has_spark_location: bool,
    spark_location_mm: float,
    voltage: float,
    current: float,
    current_squared: float,
    segment_len_mm: float,
    zone_start: int,
    zone_end: int,
    n_segments: int,
    contact_bottom_idx: int,
    contact_top_idx: int,
    plasma_efficiency: float,
    joule_factor_base: float,
) -> tuple[int, float, int, int, float, int, int, float]:
    """Resolve spark index, plasma heating, and contact-current partitioning."""
    plasma_idx = -1
    plasma_heat = 0.0
    bottom_start = 0
    bottom_end = 0
    bottom_joule_factor = 0.0
    top_start = 0
    top_end = 0
    top_joule_factor = 0.0

    is_active_discharge = spark_state == 1 or spark_state == -1
    if is_active_discharge and has_spark_location:
        if segment_len_mm > 0.0 and zone_end > zone_start:
            rel_idx_float = spark_location_mm / segment_len_mm
            zone_len = zone_end - zone_start
            rel_idx = int(min(max(0.0, rel_idx_float), float(zone_len - 1)))
            plasma_idx = zone_start + rel_idx

        if 0 <= plasma_idx < n_segments:
            plasma_heat = plasma_efficiency * voltage * current
            if not np.isfinite(plasma_heat):
                plasma_heat = 0.0

    if (
        not is_active_discharge
        or current_squared <= 1e-6
        or contact_top_idx < contact_bottom_idx
    ):
        return (
            plasma_idx,
            plasma_heat,
            bottom_start,
            bottom_end,
            bottom_joule_factor,
            top_start,
            top_end,
            top_joule_factor,
        )

    spark_idx = plasma_idx
    if spark_idx < 0 and has_spark_location:
        spark_idx = int(
            min(max(spark_location_mm / segment_len_mm, 0.0), float(n_segments - 1))
        )

    spark_idx = min(max(int(spark_idx), contact_bottom_idx), contact_top_idx)

    L_bottom = max(0, spark_idx - contact_bottom_idx)
    L_top = max(0, contact_top_idx - spark_idx)
    total_length = L_bottom + L_top
    if total_length > 0:
        if L_bottom == 0:
            i_bottom = 0.0
            i_top = current
        elif L_top == 0:
            i_bottom = current
            i_top = 0.0
        else:
            i_bottom = current * (L_top / total_length)
            i_top = current * (L_bottom / total_length)
    else:
        i_bottom = current * 0.5
        i_top = current * 0.5

    if L_bottom > 0 and spark_idx > contact_bottom_idx:
        bottom_start = contact_bottom_idx
        bottom_end = spark_idx
        bottom_joule_factor = joule_factor_base * (i_bottom * i_bottom)

    if L_top > 0 and spark_idx < contact_top_idx:
        top_start = spark_idx + 1
        top_end = contact_top_idx + 1
        top_joule_factor = joule_factor_base * (i_top * i_top)

    return (
        plasma_idx,
        plasma_heat,
        bottom_start,
        bottom_end,
        bottom_joule_factor,
        top_start,
        top_end,
        top_joule_factor,
    )


@njit(cache=True, fastmath=True)
def advance_wire_step_inplace(
    temperature: np.ndarray,
    damage: np.ndarray,
    dT_dt: np.ndarray,
    conv_loss_coeff: np.ndarray,
    position_offset_mm: float,
    position_wrap_threshold_mm: float,
    delta_mm: float,
    spool_temp: float,
    k_cond_coeff: float,
    temp_update_factor: float,
    dielectric_temp: float,
    temp_ref: float,
    alpha_rho: float,
    spark_state: int,
    has_spark_location: bool,
    spark_location_mm: float,
    voltage: float,
    current: float,
    current_squared: float,
    segment_len_mm: float,
    zone_start: int,
    zone_end: int,
    contact_bottom_idx: int,
    contact_top_idx: int,
    plasma_efficiency: float,
    joule_factor_base: float,
    threshold_k: float,
    stress_term_dt: float,
    activation_scale: float,
) -> tuple[float, float]:
    """Advance transport and apply the full discharge thermal-damage step."""
    n_segments = temperature.shape[0]
    if n_segments == 0:
        return position_offset_mm, 0.0

    if delta_mm != 0.0:
        if position_wrap_threshold_mm <= 0.0:
            raise ValueError("position_wrap_threshold_mm must be positive")
        position_offset_mm += delta_mm
        rollover_count = 0
        while position_offset_mm > position_wrap_threshold_mm:
            position_offset_mm -= position_wrap_threshold_mm
            rollover_count += 1

        if rollover_count >= n_segments:
            for i in range(n_segments):
                temperature[i] = spool_temp
                damage[i] = 0.0
        elif rollover_count > 0:
            for i in range(n_segments - 1, rollover_count - 1, -1):
                temperature[i] = temperature[i - rollover_count]
                damage[i] = damage[i - rollover_count]

            for i in range(rollover_count):
                temperature[i] = spool_temp
                damage[i] = 0.0

    (
        plasma_idx,
        plasma_heat,
        bottom_start,
        bottom_end,
        bottom_joule_factor,
        top_start,
        top_end,
        top_joule_factor,
    ) = resolve_discharge_partition(
        spark_state,
        has_spark_location,
        spark_location_mm,
        voltage,
        current,
        current_squared,
        segment_len_mm,
        zone_start,
        zone_end,
        n_segments,
        contact_bottom_idx,
        contact_top_idx,
        plasma_efficiency,
        joule_factor_base,
    )

    max_damage = apply_thermal_damage_core_inplace(
        temperature,
        damage,
        dT_dt,
        conv_loss_coeff,
        k_cond_coeff,
        temp_update_factor,
        dielectric_temp,
        temp_ref,
        alpha_rho,
        bottom_start,
        bottom_end,
        bottom_joule_factor,
        top_start,
        top_end,
        top_joule_factor,
        plasma_idx,
        plasma_heat,
        spool_temp,
        threshold_k,
        stress_term_dt,
        activation_scale,
    )

    return position_offset_mm, max_damage


class WireModule(EDMModule):
    """Optimized 1-D transient heat model of the travelling wire with automatic material loading."""

    def __init__(
        self,
        env,
        parameters: WireModuleParameters = None,
    ):
        super().__init__(env)

        # ── Module Parameters ──
        self.params = parameters or WireModuleParameters()
        if self.params.segment_len <= 0.0:
            raise ValueError("WireModuleParameters.segment_len must be positive")
        if self.params.buffer_len_bottom < 0.0 or self.params.buffer_len_top < 0.0:
            raise ValueError("Wire buffer lengths must be non-negative")

        # ── Automatic Material Loading ──
        material_db = get_material_db()
        self.wire_material = material_db.get_wire_material(env.config.wire_material)

        # ── Geometry Setup ──
        self.total_L = (
            self.params.buffer_len_bottom
            + env.config.workpiece_height
            + self.params.buffer_len_top
        )
        self.n_segments = max(1, int(self.total_L / self.params.segment_len))

        self.zone_start = int(self.params.buffer_len_bottom // self.params.segment_len)
        self.zone_end = self.zone_start + int(
            env.config.workpiece_height // self.params.segment_len
        )
        self.zone_end = min(self.zone_end, self.n_segments)
        self.zone_start = min(self.zone_start, self.zone_end)

        self.r_wire = env.config.wire_diameter / 2.0  # [mm]

        # Initialize wire temperature field
        if (
            not hasattr(env.state, "wire_temperature")
            or not isinstance(env.state.wire_temperature, np.ndarray)
            or len(env.state.wire_temperature) != self.n_segments
        ):
            env.state.wire_temperature = np.full(
                self.n_segments, self.params.spool_T, dtype=np.float32
            )

        # ── Lagrangian segments (clarity-first) ──
        @dataclass
        class Segment:
            y_start_mm: float
            temperature: float
            damage: float

        self._Segment = Segment
        self.segment_len_mm = float(self.params.segment_len)

        # Keep the dataclass type for compatibility snapshots, but do not mirror it
        # on every microstep. The NumPy arrays below are the live state.

        # ── Internal NumPy arrays for the live wire state ──
        # Keep segment data in arrays to avoid rebuilding compatibility objects.
        self._base_positions_mm = self._build_initial_positions()
        self._y_start_mm = self._base_positions_mm.copy()
        self._position_offset_mm = 0.0
        self._position_wrap_threshold_mm = self._compute_position_wrap_threshold()
        self._positions_dirty = False
        self._temperature = np.full(
            self.n_segments, self.params.spool_T, dtype=np.float32
        )
        self._damage = np.zeros(self.n_segments, dtype=np.float32)

        # ── Pre-compute Material Constants ──
        self.delta_y = self.params.segment_len * 1e-3  # [m]
        self.S = np.pi * (self.r_wire * 1e-3) ** 2  # [m²]
        self.A = 2 * np.pi * (self.r_wire * 1e-3) * self.delta_y  # [m²]

        # Thermal properties from material database
        self.k_cond_coeff = (
            self.wire_material.thermal_conductivity * self.S / self.delta_y
        )
        self.denominator = (
            self.wire_material.density
            * self.wire_material.specific_heat
            * self.S
            * self.delta_y
        )
        self.joule_geom_factor = self.delta_y / self.S if self.S != 0 else 0.0

        # Electrical properties from material database
        self.rho_elec = self.wire_material.electrical_resistivity
        self.alpha_rho = self.wire_material.temperature_coefficient
        self.joule_factor_base = self.joule_geom_factor * self.rho_elec

        # Time constants
        self.dt_sim = 1e-6  # [s]
        self.temp_ref = 293.15  # [K]

        if self.denominator == 0:
            raise ValueError(
                "Denominator for dT/dt is zero. Check wire/segment properties."
            )

        # Pre-compute combined scaling factor
        self.temp_update_factor = self.dt_sim / self.denominator

        # ── Pre-allocate Arrays ──
        self.dT_dt = np.zeros(self.n_segments, dtype=np.float32)
        # Convection coefficients per PHYSICAL index (0..N-1)
        self.h_eff_zone = np.zeros(self.n_segments, dtype=np.float32)
        self.conv_loss_coeff = np.zeros(self.n_segments, dtype=np.float32)

        # Zone boundaries
        self.actual_zone_start = min(self.zone_start, self.n_segments - 1)
        self.actual_zone_end = min(self.zone_end, self.n_segments)

        if self.actual_zone_end > self.actual_zone_start:
            self.zone_size = self.actual_zone_end - self.actual_zone_start
        else:
            self.zone_size = 1

        # ── Damage Model - material-specific wire break coefficients ──
        # sigma = F / A where A = pi * r^2 (already computed as self.S in m²)
        self.wire_stress_mpa = (
            self.params.wire_tension_force / self.S
        ) / 1e6  # Convert Pa to MPa
        self.damage_temperature_threshold_k = (
            self.wire_material.damage_temperature_threshold
        )
        self.damage_stress_term_dt = (
            self.wire_material.damage_rate_constant
            * (self.wire_stress_mpa ** self.wire_material.damage_stress_exponent)
            * self.dt_sim
        )
        self.damage_activation_scale = (
            -self.wire_material.damage_activation_energy
            / _UNIVERSAL_GAS_CONSTANT_J_PER_MOL_K
        )

        # Cache for last computed zone mean
        self._last_zone_mean = self.params.spool_T
        # Force first-time convection coefficient update on first call to update()
        self._last_flow_condition = None  # type: ignore[assignment]
        self.zone_mean_counter = 0

        # ── Calculate electrical contact positions (physical) ──
        # Contacts are positioned outside the workpiece zone
        contact_bottom_pos_mm = (
            self.params.buffer_len_bottom - self.params.contact_offset_bottom
        )
        contact_top_pos_mm = (
            self.params.buffer_len_bottom
            + env.config.workpiece_height
            + self.params.contact_offset_top
        )

        # Convert to PHYSICAL segment indices
        self.contact_bottom_idx = max(
            0, int(contact_bottom_pos_mm / self.params.segment_len)
        )
        self.contact_top_idx = min(
            self.n_segments - 1, int(contact_top_pos_mm / self.params.segment_len)
        )

        # Ensure contacts are outside the workpiece zone but within wire bounds
        self.contact_bottom_idx = max(
            0, min(self.contact_bottom_idx, self.zone_start - 1)
        )
        self.contact_top_idx = min(
            self.n_segments - 1, max(self.contact_top_idx, self.zone_end)
        )

    def _build_initial_positions(self) -> np.ndarray:
        """Return the default segment start positions for a fresh episode."""
        return np.arange(self.n_segments, dtype=np.float32) * np.float32(
            self.segment_len_mm
        )

    def _compute_position_wrap_threshold(self) -> float:
        """Return the distance advanced before the leading segment rolls over."""
        if self.segment_len_mm <= 0.0:
            raise ValueError("segment_len_mm must be positive")
        threshold = float(
            self.total_L - (self.segment_len_mm * float(max(self.n_segments - 1, 0)))
        )
        if threshold <= 0.0:
            raise ValueError("position_wrap_threshold_mm must be positive")
        return threshold

    def _ensure_position_buffer(self) -> np.ndarray:
        """Refresh the compatibility position snapshot only when transport moved."""
        if self._positions_dirty and self._y_start_mm.size > 0:
            np.add(
                self._base_positions_mm,
                self._position_offset_mm,
                out=self._y_start_mm,
                casting="unsafe",
            )
            self._positions_dirty = False
        return self._y_start_mm

    def _roll_in_fresh_segments(self, count: int) -> None:
        """Insert fresh spool segments after one or more wraparound events."""
        if count <= 0:
            return

        if count >= self.n_segments:
            self._temperature.fill(np.float32(self.params.spool_T))
            self._damage.fill(0.0)
            return

        self._temperature[count:] = self._temperature[:-count]
        self._damage[count:] = self._damage[:-count]
        self._temperature[:count] = np.float32(self.params.spool_T)
        self._damage[:count] = 0.0

    @property
    def segments(self) -> list:
        """Return a point-in-time snapshot of segment data for compatibility."""
        y_start_mm = self._ensure_position_buffer()
        return [
            self._Segment(
                float(y_start_mm[i]),
                float(self._temperature[i]),
                float(self._damage[i]),
            )
            for i in range(self.n_segments)
        ]

    def reset(self, state: EDMState) -> None:
        """Restore wire thermal, damage, and transport state for a new episode."""
        self._position_offset_mm = 0.0
        self._positions_dirty = False
        self._y_start_mm = self._base_positions_mm.copy()
        self._temperature.fill(np.float32(self.params.spool_T))
        self._damage.fill(0.0)
        self.dT_dt.fill(0.0)
        self.h_eff_zone.fill(0.0)
        self.conv_loss_coeff.fill(0.0)
        self._last_zone_mean = self.params.spool_T
        self._last_flow_condition = None
        self.zone_mean_counter = 0

        state.wire_temperature = self._temperature
        state.wire_damage = self._damage
        state.wire_max_damage = 0.0
        state.is_wire_broken = False
        state.wire_average_temperature = (
            self._last_zone_mean if self.params.compute_zone_mean else None
        )
        state.wire_head_idx = 0
        state.wire_offset_mm = 0.0
        state.wire_material_positions_mm = self._y_start_mm

    def update(self, state: EDMState) -> None:
        if state.is_wire_broken:
            return

        # Cache lookups for efficiency
        I = state.current
        I_squared = I * I
        dielectric_temp = state.dielectric_temperature
        wire_unwind_vel = state.wire_unwinding_velocity

        # Update convection coefficients only when flow condition changes significantly
        flow_condition = state.flow_rate
        if (self._last_flow_condition is None) or (
            abs(flow_condition - self._last_flow_condition) > 0.01
        ):
            self._update_convection_coefficients(wire_unwind_vel, flow_condition)
            self._last_flow_condition = flow_condition

        T_vec = self._temperature
        delta_mm = 0.0
        if self.params.moving_segments:
            dt_us = self.env.config.dt
            delta_mm = wire_unwind_vel * 1e-3 * dt_us
            if delta_mm != 0.0:
                self._positions_dirty = True

        has_spark_location = state.spark_status[1] is not None
        spark_location_mm = state.spark_status[1] if has_spark_location else 0.0

        self._position_offset_mm, max_damage = advance_wire_step_inplace(
            T_vec,
            self._damage,
            self.dT_dt,
            self.conv_loss_coeff,
            self._position_offset_mm,
            self._position_wrap_threshold_mm,
            delta_mm,
            self.params.spool_T,
            self.k_cond_coeff,
            self.temp_update_factor,
            dielectric_temp,
            self.temp_ref,
            self.alpha_rho,
            int(state.spark_status[0]),
            bool(has_spark_location),
            spark_location_mm,
            state.voltage,
            I,
            I_squared,
            self.segment_len_mm,
            int(self.zone_start),
            int(self.zone_end),
            int(self.contact_bottom_idx),
            int(self.contact_top_idx),
            self.params.plasma_efficiency,
            self.joule_factor_base,
            self.damage_temperature_threshold_k,
            self.damage_stress_term_dt,
            self.damage_activation_scale,
        )
        state.wire_max_damage = max_damage
        if max_damage >= 1.0:
            state.is_wire_broken = True
        self._sync_state_views(state, T_vec)

        # Compute zone mean only when needed
        if self.params.compute_zone_mean:
            self.zone_mean_counter += 1
            if self.zone_mean_counter >= self.params.zone_mean_interval:
                self._last_zone_mean = self._compute_zone_mean_fast(T_vec)
                state.wire_average_temperature = self._last_zone_mean
                self.zone_mean_counter = 0
            else:
                # Use cached value
                state.wire_average_temperature = self._last_zone_mean

    def _advance_transport(self, wire_unwind_vel: float) -> None:
        """Advance the moving-wire transport model and roll in fresh segments."""
        if not self.params.moving_segments:
            return

        dt_us = self.env.config.dt
        v_mm_per_us = wire_unwind_vel * 1e-3
        delta_mm = v_mm_per_us * dt_us
        if delta_mm == 0.0:
            return
        if self._position_wrap_threshold_mm <= 0.0:
            raise ValueError("position_wrap_threshold_mm must be positive")

        self._positions_dirty = True
        self._position_offset_mm += delta_mm
        rollover_count = 0
        while self._position_offset_mm > self._position_wrap_threshold_mm:
            self._position_offset_mm -= self._position_wrap_threshold_mm
            rollover_count += 1
        if rollover_count:
            self._roll_in_fresh_segments(int(rollover_count))

    def _sync_state_views(self, state: EDMState, T_vec: np.ndarray) -> None:
        """Sync wire diagnostics back into the shared state buffers."""
        state.wire_head_idx = 0
        if self._base_positions_mm.size > 0:
            state.wire_offset_mm = float(self._position_offset_mm)
            positions = self._ensure_position_buffer()
            if state.wire_material_positions_mm is not positions:
                state.wire_material_positions_mm = positions
        else:
            state.wire_offset_mm = 0.0
            state.wire_material_positions_mm = np.array([], dtype=np.float64)

        if state.wire_temperature is not T_vec:
            state.wire_temperature = T_vec

        if state.wire_damage is not self._damage:
            state.wire_damage = self._damage

    def _update_convection_coefficients(
        self, wire_unwind_vel: float, flow_condition: float
    ):
        """Update zone-specific convection coefficients."""
        # Ensure convection enhancement factor doesn't make coefficient negative
        velocity_enhancement = max(
            -0.9, self.params.convection_velocity_factor * wire_unwind_vel
        )

        h_eff_base = self.params.base_convection_coefficient * (
            1.0 + velocity_enhancement
        )

        # Ensure minimum positive convection coefficient
        h_eff_base = max(h_eff_base, 0.1 * self.params.base_convection_coefficient)

        h_eff_enhanced = h_eff_base * (
            1.0 + self.params.convection_flow_enhancement * flow_condition
        )

        # Fill array (per PHYSICAL index order)
        self.h_eff_zone.fill(h_eff_base)
        self.conv_loss_coeff.fill(h_eff_base * self.A)
        if self.actual_zone_start < self.actual_zone_end:
            self.h_eff_zone[self.actual_zone_start : self.actual_zone_end] = (
                h_eff_enhanced
            )
            self.conv_loss_coeff[self.actual_zone_start : self.actual_zone_end] = (
                h_eff_enhanced * self.A
            )

    def _compute_zone_mean_fast(self, T: np.ndarray) -> float:
        """Zone mean over contiguous zone indices (simple)."""
        if self.zone_size > 0 and self.actual_zone_end <= len(T):
            return float(np.mean(T[self.actual_zone_start : self.actual_zone_end]))
        return float(np.mean(T))

    def compute_zone_mean_temperature(self, temperature_field: np.ndarray) -> float:
        """Public method for on-demand zone mean calculation."""
        return self._compute_zone_mean_fast(temperature_field)
