# src/wedm/modules/wire_optimized.py
from __future__ import annotations

import numpy as np
from numba import njit, prange
from dataclasses import dataclass

from ..core.module import EDMModule
from ..core.state import EDMState
from ..core.material_db import get_material_db


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

    # ── Heat Transfer Parameters ──
    base_convection_coefficient: float = 14000  # [W/m²·K] Base convection coefficient
    plasma_efficiency: float = (
        0.1  # [dimensionless] Fraction of electrical power converted to heat in plasma
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

    # ── Critical Temperature Parameters ──
    critical_temp_threshold: float = (
        0.9  # [dimensionless] Fraction of melting point considered critical
    )
    wire_breaking_temp_factor: float = (
        1.1  # [dimensionless] Factor above melting point for wire breaking
    )


# Numba-compiled functions for performance-critical calculations
@njit(cache=False, fastmath=True)
def compute_thermal_update(
    T,
    dT_dt,
    n_segments,
    spool_T,
    k_cond_coeff,
    I_squared,
    joule_geom_factor,
    rho_elec,
    alpha_rho,
    temp_ref,
    plasma_idx,
    plasma_heat,
    h_eff_base,
    h_eff_zone,
    dielectric_temp,
    A,
    adv_coeff,
    temp_update_factor,
    contact_bottom_idx,
    contact_top_idx,
):
    """Optimized thermal update computation using Numba."""
    # Apply boundary condition
    T[0] = spool_T

    # Reset dT/dt
    dT_dt[:] = 0.0

    # 1) Conduction - optimized with single pass
    if n_segments > 1:
        # Interior points
        for i in prange(1, n_segments - 1):
            dT_dt[i] = k_cond_coeff * (T[i - 1] - 2 * T[i] + T[i + 1])

        # Neumann BC at last segment
        dT_dt[n_segments - 1] = k_cond_coeff * (T[n_segments - 2] - T[n_segments - 1])

    # 2) Joule heating - only between electrical contacts
    if I_squared > 1e-6:
        joule_factor = joule_geom_factor * I_squared * rho_elec
        for i in prange(contact_bottom_idx, contact_top_idx + 1):
            rho_T = 1.0 + alpha_rho * (T[i] - temp_ref)
            dT_dt[i] += joule_factor * rho_T

    # 3) Plasma heating
    if plasma_idx >= 0 and plasma_idx < n_segments:
        dT_dt[plasma_idx] += plasma_heat

    # 4) Convection - optimized with precomputed coefficients
    for i in prange(n_segments):
        conv_coeff = h_eff_zone[i] * A
        dT_dt[i] -= conv_coeff * (T[i] - dielectric_temp)

    # 5) Advection
    if abs(adv_coeff) > 1e-9:
        for i in prange(1, n_segments):
            dT_dt[i] += adv_coeff * (T[i - 1] - T[i])

    # 6) Temperature update
    for i in prange(n_segments):
        T[i] += dT_dt[i] * temp_update_factor

    # Re-apply boundary condition
    T[0] = spool_T


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

        # Time constants
        self.dt_sim = 1e-6  # [s]
        self.temp_ref = 293.15  # [K]

        # Pre-compute combined scaling factor
        self.temp_update_factor = self.dt_sim / self.denominator

        if self.denominator == 0:
            raise ValueError(
                "Denominator for dT/dt is zero. Check wire/segment properties."
            )

        # ── Pre-allocate Arrays ──
        self.dT_dt = np.zeros(self.n_segments, dtype=np.float32)
        self.h_eff_zone = np.zeros(self.n_segments, dtype=np.float32)

        # Zone boundaries
        self.actual_zone_start = min(self.zone_start, self.n_segments - 1)
        self.actual_zone_end = min(self.zone_end, self.n_segments)

        if self.actual_zone_end > self.actual_zone_start:
            self.zone_size = self.actual_zone_end - self.actual_zone_start
        else:
            self.zone_size = 1

        # ── Temperature Monitoring ──
        self.critical_temperature = (
            self.wire_material.melting_point * self.params.critical_temp_threshold
        )
        self.breaking_temperature = self.wire_material.breaking_temperature

        # Cache for last computed zone mean
        self._last_zone_mean = self.params.spool_T
        self._last_flow_condition = 0.0
        self.zone_mean_counter = 0

        # ── Calculate electrical contact positions ──
        # Contacts are positioned outside the workpiece zone
        contact_bottom_pos_mm = (
            self.params.buffer_len_bottom - self.params.contact_offset_bottom
        )
        contact_top_pos_mm = (
            self.params.buffer_len_bottom
            + env.config.workpiece_height
            + self.params.contact_offset_top
        )

        # Convert to segment indices
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

        print(
            f"[+] Electrical contacts: segments {self.contact_bottom_idx} to {self.contact_top_idx}"
        )
        print(f"   Workpiece zone: segments {self.zone_start} to {self.zone_end}")

    def update(self, state: EDMState) -> None:
        if state.is_wire_broken:
            return

        # Fast path: avoid array length checks
        T = state.wire_temperature
        if len(T) != self.n_segments:
            state.wire_temperature = np.full(
                self.n_segments, self.params.spool_T, dtype=np.float32
            )
            T = state.wire_temperature

        # Cache lookups for efficiency
        I = state.current or 0.0
        I_squared = I * I
        dielectric_temp = state.dielectric_temperature
        wire_unwind_vel = state.wire_unwinding_velocity

        # Update convection coefficients only when flow condition changes significantly
        flow_condition = state.flow_rate
        if abs(flow_condition - self._last_flow_condition) > 0.01:
            self._update_convection_coefficients(wire_unwind_vel, flow_condition)
            self._last_flow_condition = flow_condition

        # Prepare plasma heating
        plasma_idx = -1
        plasma_heat = 0.0
        if state.spark_status[0] == 1 and state.spark_status[1] is not None:
            y_spark = state.spark_status[1]
            plasma_idx = (
                self.zone_start + int(y_spark // self.params.segment_len)
                if self.params.segment_len != 0
                else self.zone_start
            )
            if 0 <= plasma_idx < self.n_segments:
                voltage = state.voltage if state.voltage is not None else 0.0
                plasma_heat = self.params.plasma_efficiency * voltage * I
                if not np.isfinite(plasma_heat):
                    plasma_heat = 0.0

        # Advection coefficient
        if abs(wire_unwind_vel) > 1e-6:
            v_wire = abs(wire_unwind_vel)  # Use absolute value - m s⁻¹
            adv_coeff = (
                self.wire_material.density
                * self.wire_material.specific_heat
                * v_wire
                * self.S
            )
        else:
            adv_coeff = 0.0

        # Call optimized Numba function
        compute_thermal_update(
            T,
            self.dT_dt,
            self.n_segments,
            self.params.spool_T,
            self.k_cond_coeff,
            I_squared,
            self.joule_geom_factor,
            self.rho_elec,
            self.alpha_rho,
            self.temp_ref,
            plasma_idx,
            plasma_heat,
            self.params.base_convection_coefficient,
            self.h_eff_zone,
            dielectric_temp,
            self.A,
            adv_coeff,
            self.temp_update_factor,
            self.contact_bottom_idx,
            self.contact_top_idx,
        )

        # ── Temperature Monitoring and Wire Breaking ──
        self._check_wire_breaking(state, T)

        # Compute zone mean only when needed
        if self.params.compute_zone_mean:
            self.zone_mean_counter += 1
            if self.zone_mean_counter >= self.params.zone_mean_interval:
                self._last_zone_mean = self._compute_zone_mean_fast(T)
                state.wire_average_temperature = self._last_zone_mean
                self.zone_mean_counter = 0
            else:
                # Use cached value
                state.wire_average_temperature = self._last_zone_mean

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

        # Fill array with appropriate values
        self.h_eff_zone.fill(h_eff_base)
        if self.actual_zone_start < self.actual_zone_end:
            self.h_eff_zone[self.actual_zone_start : self.actual_zone_end] = (
                h_eff_enhanced
            )

    def _check_wire_breaking(self, state: EDMState, T: np.ndarray) -> None:
        """Check if wire should break due to temperature."""
        max_temp = np.max(T)

        # Track time in critical temperature range
        if max_temp > self.critical_temperature:
            state.time_in_critical_temp += 1
        else:
            state.time_in_critical_temp = 0

        # Wire breaks if temperature exceeds breaking point
        if max_temp > self.breaking_temperature:
            state.is_wire_broken = True

    def _compute_zone_mean_fast(self, T: np.ndarray) -> float:
        """Fast zone mean computation."""
        if self.zone_size > 0 and self.actual_zone_end <= len(T):
            return float(np.mean(T[self.actual_zone_start : self.actual_zone_end]))
        return float(np.mean(T))

    def compute_zone_mean_temperature(self, temperature_field: np.ndarray) -> float:
        """Public method for on-demand zone mean calculation."""
        return self._compute_zone_mean_fast(temperature_field)
