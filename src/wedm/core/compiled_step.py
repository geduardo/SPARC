"""Compiled scheduler over module-owned Numba kernels.

Keeps the microstep physics in compiled code and returns to Python only
for branch-dependent RNG draws and env-level orchestration.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from numba import njit

from ..modules.ignition import (
    _advance_discharge_state,
    _get_debris_short_probability_scalar,
    _get_ignition_probability_scalar,
)
from ..modules.wire import advance_wire_step_inplace
if TYPE_CHECKING:
    from ..envs.wire_edm import WireEDMEnv


# ── Constants bundle ─────────────────────────────────────────────────────────
# Module parameters are captured once at init time and passed to Numba
# kernels as plain tuples.

@dataclass(frozen=True, slots=True)
class SchedulerConstants:
    """Frozen parameter snapshot consumed by the compiled scheduler."""

    # timing
    dt_int: int  # 1 for 1 µs
    servo_interval: int

    # ignition – short circuit
    hard_short_gap: float
    base_critical_density: float
    gap_coefficient: float
    max_critical_density: float
    sigmoid_steepness: float
    debris_short_duration: int
    random_short_duration: int
    random_short_min_gap: float
    random_short_max_gap: float
    random_short_max_probability: float
    random_short_enabled: bool

    # ignition – discharge
    ignition_a_coeff: float
    ignition_b_coeff: float
    ignition_c_coeff: float
    log2_value: float
    spark_voltage_factor: float
    workpiece_height: float

    # material – crater geometry (for position increment)
    kerf_width_mm: float  # base_overcut + wire_diameter + crater_depth_mm
    workpiece_height_for_material: float  # mm, same as workpiece_height above but kept separate for clarity

    # dielectric
    dielectric_temperature: float
    cavity_volume_coeff: float
    reference_gap: float
    debris_obstruction_coeff: float
    debris_removal_per_us: float
    ion_channel_duration: int

    # wire
    spool_temp: float
    k_cond_coeff: float
    temp_update_factor: float
    temp_ref: float
    alpha_rho: float
    segment_len_mm: float
    zone_start: int
    zone_end: int
    contact_bottom_idx: int
    contact_top_idx: int
    plasma_efficiency: float
    joule_factor_base: float
    damage_threshold_k: float
    damage_stress_term_dt: float
    damage_activation_scale: float
    position_wrap_threshold_mm: float
    moving_segments: bool
    compute_zone_mean: bool
    zone_mean_interval: int
    convection_velocity_factor: float
    base_convection_coefficient: float
    convection_flow_enhancement: float
    actual_zone_start: int
    actual_zone_end: int
    wire_A: float  # surface area per segment for convection

    # mechanics
    mechanics_mode_is_position: bool
    damping_coeff: float
    stiffness_coeff: float
    omega_n: float
    max_acceleration: float
    max_jerk_dt: float
    max_speed: float
    mechanics_dt: float  # dt in seconds (1e-6)

    def as_tuple(self) -> tuple:
        """Return all fields as a flat tuple for Numba consumption."""
        return (
            self.dt_int,
            self.servo_interval,
            self.hard_short_gap,
            self.base_critical_density,
            self.gap_coefficient,
            self.max_critical_density,
            self.sigmoid_steepness,
            self.debris_short_duration,
            self.random_short_duration,
            self.random_short_min_gap,
            self.random_short_max_gap,
            self.random_short_max_probability,
            self.random_short_enabled,
            self.ignition_a_coeff,
            self.ignition_b_coeff,
            self.ignition_c_coeff,
            self.log2_value,
            self.spark_voltage_factor,
            self.workpiece_height,
            self.kerf_width_mm,
            self.workpiece_height_for_material,
            self.dielectric_temperature,
            self.cavity_volume_coeff,
            self.reference_gap,
            self.debris_obstruction_coeff,
            self.debris_removal_per_us,
            self.ion_channel_duration,
            self.spool_temp,
            self.k_cond_coeff,
            self.temp_update_factor,
            self.temp_ref,
            self.alpha_rho,
            self.segment_len_mm,
            self.zone_start,
            self.zone_end,
            self.contact_bottom_idx,
            self.contact_top_idx,
            self.plasma_efficiency,
            self.joule_factor_base,
            self.damage_threshold_k,
            self.damage_stress_term_dt,
            self.damage_activation_scale,
            self.position_wrap_threshold_mm,
            self.moving_segments,
            self.compute_zone_mean,
            self.zone_mean_interval,
            self.convection_velocity_factor,
            self.base_convection_coefficient,
            self.convection_flow_enhancement,
            self.actual_zone_start,
            self.actual_zone_end,
            self.wire_A,
            self.mechanics_mode_is_position,
            self.damping_coeff,
            self.stiffness_coeff,
            self.omega_n,
            self.max_acceleration,
            self.max_jerk_dt,
            self.max_speed,
            self.mechanics_dt,
        )

    @classmethod
    def from_env(cls, env: "WireEDMEnv") -> "SchedulerConstants":
        ign = env.ignition
        wire = env.wire
        diel = env.dielectric
        mech = env.mechanics
        mat = env.material

        # Material crater depth drives the effective kerf width.
        crater_depth_mm = mat._cached_crater_info["depth_um"] / 1000.0
        kerf_width_mm = mat.params.base_overcut + env.config.wire_diameter + crater_depth_mm

        return cls(
            dt_int=int(env.dt),
            servo_interval=int(env.servo_interval),
            hard_short_gap=ign.params.hard_short_gap,
            base_critical_density=ign.params.base_critical_density,
            gap_coefficient=ign.params.gap_coefficient,
            max_critical_density=ign.params.max_critical_density,
            sigmoid_steepness=ign.params.sigmoid_steepness,
            debris_short_duration=ign.params.debris_short_duration,
            random_short_duration=ign.params.random_short_duration,
            random_short_min_gap=ign.params.random_short_min_gap,
            random_short_max_gap=ign.params.random_short_max_gap,
            random_short_max_probability=ign.params.random_short_max_probability,
            random_short_enabled=ign._random_short_enabled,
            ignition_a_coeff=ign.params.ignition_a_coeff,
            ignition_b_coeff=ign.params.ignition_b_coeff,
            ignition_c_coeff=ign.params.ignition_c_coeff,
            log2_value=ign._log2,
            spark_voltage_factor=ign.params.spark_voltage_factor,
            workpiece_height=env.config.workpiece_height,
            kerf_width_mm=kerf_width_mm,
            workpiece_height_for_material=env.config.workpiece_height,
            dielectric_temperature=diel.params.dielectric_temperature,
            cavity_volume_coeff=diel.cavity_volume_coeff,
            reference_gap=diel.params.reference_gap,
            debris_obstruction_coeff=diel.params.debris_obstruction_coeff,
            debris_removal_per_us=diel.debris_removal_per_us,
            ion_channel_duration=diel.params.ion_channel_duration,
            spool_temp=wire.params.spool_T,
            k_cond_coeff=wire.k_cond_coeff,
            temp_update_factor=wire.temp_update_factor,
            temp_ref=wire.temp_ref,
            alpha_rho=wire.alpha_rho,
            segment_len_mm=wire.segment_len_mm,
            zone_start=int(wire.zone_start),
            zone_end=int(wire.zone_end),
            contact_bottom_idx=int(wire.contact_bottom_idx),
            contact_top_idx=int(wire.contact_top_idx),
            plasma_efficiency=wire.params.plasma_efficiency,
            joule_factor_base=wire.joule_factor_base,
            damage_threshold_k=wire.damage_temperature_threshold_k,
            damage_stress_term_dt=wire.damage_stress_term_dt,
            damage_activation_scale=wire.damage_activation_scale,
            position_wrap_threshold_mm=wire._position_wrap_threshold_mm,
            moving_segments=wire.params.moving_segments,
            compute_zone_mean=wire.params.compute_zone_mean,
            zone_mean_interval=wire.params.zone_mean_interval,
            convection_velocity_factor=wire.params.convection_velocity_factor,
            base_convection_coefficient=wire.params.base_convection_coefficient,
            convection_flow_enhancement=wire.params.convection_flow_enhancement,
            actual_zone_start=int(wire.actual_zone_start),
            actual_zone_end=int(wire.actual_zone_end),
            wire_A=wire.A,
            mechanics_mode_is_position=(mech.control_mode == "position"),
            damping_coeff=getattr(mech, "damping_coeff", 0.0),
            stiffness_coeff=getattr(mech, "stiffness_coeff", 0.0),
            omega_n=mech.params.omega_n,
            max_acceleration=mech.params.max_acceleration,
            max_jerk_dt=mech.max_jerk_dt,
            max_speed=mech.params.max_speed,
            mechanics_dt=mech.dt,
        )


# ── Compiled kernels ─────────────────────────────────────────────────────────
# Short-circuit stage.

@njit(cache=False)
def _compiled_short_circuit(
    gap: float,
    dt_int: int,
    debris_density: float,
    random_short_remaining: int,
    debris_short_remaining: int,
    debris_roll: float,
    random_roll: float,
    # ignition params
    hard_short_gap: float,
    base_critical_density: float,
    gap_coefficient: float,
    max_critical_density: float,
    sigmoid_steepness: float,
    debris_short_duration: int,
    random_short_duration: int,
    random_short_min_gap: float,
    random_short_max_gap: float,
    random_short_max_probability: float,
    random_short_enabled: bool,
) -> tuple:
    """Advance short-circuit timers. Returns (rand_rem, debris_rem, is_short)."""
    # Active random short?
    if random_short_remaining > 0:
        next_random = random_short_remaining - dt_int
        if next_random < 0:
            next_random = 0
        return next_random, debris_short_remaining, True

    # Active debris short?
    if debris_short_remaining > 0:
        next_debris = debris_short_remaining - dt_int
        if next_debris < 0:
            next_debris = 0
        return random_short_remaining, next_debris, True

    # Roll new short events
    base_debris_prob = _get_debris_short_probability_scalar(
        gap, debris_density,
        hard_short_gap, base_critical_density, gap_coefficient,
        max_critical_density, sigmoid_steepness,
    )
    if base_debris_prob >= 1.0 or dt_int == 1:
        debris_short_prob = base_debris_prob
    else:
        debris_short_prob = 1.0 - math.pow(1.0 - base_debris_prob, dt_int)

    if debris_roll < debris_short_prob:
        return random_short_remaining, debris_short_duration, True

    if random_short_enabled:
        if gap >= random_short_max_gap:
            random_short_rate = 0.0
        elif gap <= random_short_min_gap:
            random_short_rate = random_short_max_probability
        else:
            gap_factor = 1.0 - (gap - random_short_min_gap) / (
                random_short_max_gap - random_short_min_gap
            )
            random_short_rate = gap_factor * random_short_max_probability

        random_short_prob = 1.0 - math.exp(-random_short_rate * dt_int)
        if random_roll < random_short_prob:
            return random_short_duration, debris_short_remaining, True

    return random_short_remaining, debris_short_remaining, False


# Dielectric stage.

@njit(cache=False, fastmath=True)
def _compiled_dielectric(
    workpiece_position_um: float,
    wire_position_um: float,
    spark_state: int,
    spark_duration: int,
    spark_location_mm: float,
    last_crater_volume: float,
    # mutable state
    debris_volume: float,
    cached_gap_um: float,
    cached_debris_density: float,
    cached_flow_condition: float,
    ionized_channel_location_mm: float,
    ionized_channel_duration: int,
    # constants
    cavity_volume_coeff: float,
    reference_gap: float,
    debris_obstruction_coeff: float,
    debris_removal_per_us: float,
    ion_channel_duration_param: int,
) -> tuple:
    """Returns (debris_volume, debris_density, cavity_volume, flow_condition,
               cached_gap_um, cached_debris_density, cached_flow_condition,
               ion_loc_mm, ion_dur)."""
    gap_um = workpiece_position_um - wire_position_um
    if gap_um < 0.001:
        gap_um = 0.001

    gap_mm = gap_um * 0.001
    cavity_volume = cavity_volume_coeff * gap_mm

    # Fresh discharge?
    is_fresh = (spark_state == 1 or spark_state == -1) and spark_duration == 0
    if is_fresh:
        if last_crater_volume > 0.0:
            debris_volume += last_crater_volume
            ionized_channel_location_mm = spark_location_mm
            ionized_channel_duration = ion_channel_duration_param

    # Debris density
    if cavity_volume > 0.0:
        debris_density = debris_volume / cavity_volume
        if debris_density > 1.0:
            debris_density = 1.0
    else:
        debris_density = 0.0

    # Flow condition (with caching)
    if (
        abs(gap_um - cached_gap_um) > 0.01
        or abs(debris_density - cached_debris_density) > 0.001
    ):
        # Gap factor (Poiseuille)
        ratio = gap_um / reference_gap
        gap_factor = ratio * ratio * ratio
        if gap_factor > 1.0:
            gap_factor = 1.0

        # Debris obstruction
        arg = debris_obstruction_coeff * debris_density
        if arg < 2.0:
            # Padé approximation for small exponents.
            if arg < 0.5:
                debris_factor = (1.0 - 0.5 * arg) / (1.0 + 0.5 * arg)
            else:
                debris_factor = math.exp(-arg)
        else:
            debris_factor = math.exp(-arg)

        flow_condition = gap_factor * debris_factor
        cached_gap_um = gap_um
        cached_debris_density = debris_density
        cached_flow_condition = flow_condition
    else:
        flow_condition = cached_flow_condition

    # Debris removal
    if flow_condition > 0.001 and debris_volume > 0.001:
        debris_removed = debris_removal_per_us * flow_condition
        debris_volume -= debris_removed
        if debris_volume < 0.0:
            debris_volume = 0.0

    # Ionized channel decay
    if ionized_channel_duration > 0:
        ionized_channel_duration -= 1

    return (
        debris_volume, debris_density, cavity_volume, flow_condition,
        cached_gap_um, cached_debris_density, cached_flow_condition,
        ionized_channel_location_mm, ionized_channel_duration,
    )


# Mechanics stage.

@njit(cache=False, fastmath=True)
def _compiled_mechanics(
    wire_position: float,
    wire_velocity: float,
    target_delta: float,
    prev_accel: float,
    # constants
    mode_is_position: bool,
    damping_coeff: float,
    stiffness_coeff: float,
    omega_n: float,
    max_acceleration: float,
    max_jerk_dt: float,
    max_speed: float,
    dt: float,
) -> tuple:
    """Returns (wire_position, wire_velocity, prev_accel)."""
    x = wire_position
    v = wire_velocity

    if mode_is_position:
        x_error = -target_delta  # x - (x + target_delta)
        a_nom = damping_coeff * v + stiffness_coeff * x_error
    else:
        v_error = v - target_delta
        a_nom = -omega_n * v_error

    if a_nom > max_acceleration:
        a_nom = max_acceleration
    elif a_nom < -max_acceleration:
        a_nom = -max_acceleration

    da = a_nom - prev_accel
    if da > max_jerk_dt:
        da = max_jerk_dt
    elif da < -max_jerk_dt:
        da = -max_jerk_dt

    a = prev_accel + da
    v += a * dt
    if v > max_speed:
        v = max_speed
    elif v < -max_speed:
        v = -max_speed

    x += v * dt
    return x, v, a


# Wire convection update.

@njit(cache=False, fastmath=True)
def _compiled_update_convection(
    conv_loss_coeff: np.ndarray,
    wire_unwind_vel: float,
    flow_condition: float,
    convection_velocity_factor: float,
    base_convection_coefficient: float,
    convection_flow_enhancement: float,
    actual_zone_start: int,
    actual_zone_end: int,
    wire_A: float,
) -> None:
    """Update zone-specific convection coefficients in-place."""
    velocity_enhancement = convection_velocity_factor * wire_unwind_vel
    if velocity_enhancement < -0.9:
        velocity_enhancement = -0.9

    h_eff_base = base_convection_coefficient * (1.0 + velocity_enhancement)
    min_h = 0.1 * base_convection_coefficient
    if h_eff_base < min_h:
        h_eff_base = min_h

    h_eff_enhanced = h_eff_base * (1.0 + convection_flow_enhancement * flow_condition)

    base_coeff = h_eff_base * wire_A
    enhanced_coeff = h_eff_enhanced * wire_A

    n = conv_loss_coeff.shape[0]
    for i in range(n):
        if actual_zone_start <= i < actual_zone_end:
            conv_loss_coeff[i] = enhanced_coeff
        else:
            conv_loss_coeff[i] = base_coeff


# Zone mean sampling.

@njit(cache=False, fastmath=True)
def _compiled_zone_mean(
    temperature: np.ndarray,
    zone_start: int,
    zone_end: int,
) -> float:
    """Compute mean temperature over the workpiece zone."""
    if zone_end <= zone_start:
        return 0.0
    total = 0.0
    for i in range(zone_start, zone_end):
        total += temperature[i]
    return total / (zone_end - zone_start)


# ── Python orchestrator ──────────────────────────────────────────────────────

def _run_compiled_microstep(
    hs,  # HotStateBundle
    np_random,
    sc: SchedulerConstants,
    # pre-resolved generator settings (resolved once per control step)
    target_voltage: float,
    peak_current: float,
    on_time: float,
    off_time: float,
    # crater sampling params (resolved once per control step)
    crater_mean_um3: float,
    crater_std_um3: float,
    kerf_width_mm: float,
) -> int:
    """Execute one compiled microstep.

    Returns:
        0: continue
        1: terminated due to wire break
        2: terminated due to target reached

    RNG draws stay in Python so branch-dependent consumption remains
    aligned with the modular reference path.
    """
    dt_int = sc.dt_int

    # Short-circuit detection always consumes two RNG draws.
    gap = hs.workpiece_position_um - hs.wire_position_um
    if gap < 0.0:
        gap = 0.0

    debris_roll = np_random.random()
    random_roll = np_random.random()

    rand_rem, debris_rem, is_short = _compiled_short_circuit(
        gap, dt_int, hs.debris_density,
        hs.ignition_random_short_remaining,
        hs.ignition_debris_short_remaining,
        debris_roll, random_roll,
        sc.hard_short_gap, sc.base_critical_density, sc.gap_coefficient,
        sc.max_critical_density, sc.sigmoid_steepness,
        sc.debris_short_duration, sc.random_short_duration,
        sc.random_short_min_gap, sc.random_short_max_gap,
        sc.random_short_max_probability, sc.random_short_enabled,
    )
    hs.ignition_random_short_remaining = rand_rem
    hs.ignition_debris_short_remaining = debris_rem
    hs.is_short_circuit = int(is_short)

    # Ignition and discharge state.
    current_voltage = hs.voltage
    if is_short:
        current_voltage = 0.0

    spark_state = hs.spark_state
    spark_location = hs.spark_location_mm
    spark_duration = hs.spark_duration

    ignition_probability = 0.0
    ignition_roll = 1.0
    spark_location_roll = 0.0

    if spark_state == 0 and not is_short:
        rounded_gap = round(gap, 2)
        ignition_probability = _get_ignition_probability_scalar(
            gap, rounded_gap, dt_int,
            sc.log2_value, sc.ignition_a_coeff,
            sc.ignition_b_coeff, sc.ignition_c_coeff,
        )
        ignition_roll = np_random.random()
        if ignition_roll < ignition_probability:
            spark_location_roll = np_random.random()

    (
        next_spark_state, next_spark_location, next_spark_duration,
        next_voltage, next_current,
    ) = _advance_discharge_state(
        spark_state, spark_location, spark_duration,
        is_short, current_voltage,
        target_voltage, peak_current, on_time, off_time,
        sc.spark_voltage_factor, sc.workpiece_height,
        ignition_probability, ignition_roll, spark_location_roll,
    )

    hs.spark_state = next_spark_state
    hs.spark_location_mm = next_spark_location
    hs.spark_duration = next_spark_duration
    hs.voltage = next_voltage
    hs.current = next_current

    # Material removal consumes one normal draw on a fresh discharge.
    is_fresh_discharge = (
        (next_spark_state == 1 or next_spark_state == -1)
        and next_spark_duration == 0
    )
    if is_fresh_discharge:
        sampled_um3 = np_random.normal(crater_mean_um3, crater_std_um3)
        if sampled_um3 < 0.0:
            sampled_um3 = 0.0
        crater_volume_mm3 = sampled_um3 / 1e9

        hs.last_crater_volume = crater_volume_mm3
        if crater_volume_mm3 > 0.0 and kerf_width_mm > 0.0 and sc.workpiece_height_for_material > 0.0:
            delta_x_mm = crater_volume_mm3 / (kerf_width_mm * sc.workpiece_height_for_material)
            hs.workpiece_position_um += delta_x_mm * 1000.0
    else:
        hs.last_crater_volume = 0.0

    # Dielectric update.
    (
        hs.debris_volume, hs.debris_density, hs.cavity_volume, flow_condition,
        hs.dielectric_cached_gap_um, hs.dielectric_cached_debris_density,
        hs.dielectric_cached_flow_condition,
        hs.ionized_channel_location_mm, hs.ionized_channel_duration,
    ) = _compiled_dielectric(
        hs.workpiece_position_um, hs.wire_position_um,
        next_spark_state, next_spark_duration, next_spark_location,
        hs.last_crater_volume,
        hs.debris_volume,
        hs.dielectric_cached_gap_um, hs.dielectric_cached_debris_density,
        hs.dielectric_cached_flow_condition,
        hs.ionized_channel_location_mm, hs.ionized_channel_duration,
        sc.cavity_volume_coeff, sc.reference_gap,
        sc.debris_obstruction_coeff, sc.debris_removal_per_us,
        sc.ion_channel_duration,
    )
    hs.flow_rate = flow_condition

    # Wire thermal update.
    if (
        math.isnan(hs.wire_last_flow_condition)
        or abs(flow_condition - hs.wire_last_flow_condition) > 0.01
    ):
        _compiled_update_convection(
            hs.wire_conv_loss_coeff,
            hs.wire_unwinding_velocity_um_us,
            flow_condition,
            sc.convection_velocity_factor,
            sc.base_convection_coefficient,
            sc.convection_flow_enhancement,
            sc.actual_zone_start, sc.actual_zone_end,
            sc.wire_A,
        )
        hs.wire_last_flow_condition = flow_condition

    I = next_current
    I_squared = I * I

    delta_mm = 0.0
    if sc.moving_segments:
        delta_mm = hs.wire_unwinding_velocity_um_us * 1e-3 * sc.dt_int

    has_spark_loc = not math.isnan(next_spark_location)

    hs.wire_position_offset_mm, max_damage = advance_wire_step_inplace(
        hs.wire_temperature, hs.wire_damage, hs.wire_d_t_dt,
        hs.wire_conv_loss_coeff,
        hs.wire_position_offset_mm, sc.position_wrap_threshold_mm,
        delta_mm, sc.spool_temp,
        sc.k_cond_coeff, sc.temp_update_factor,
        sc.dielectric_temperature, sc.temp_ref, sc.alpha_rho,
        next_spark_state, has_spark_loc,
        next_spark_location if has_spark_loc else 0.0,
        next_voltage, I, I_squared,
        sc.segment_len_mm, sc.zone_start, sc.zone_end,
        sc.contact_bottom_idx, sc.contact_top_idx,
        sc.plasma_efficiency, sc.joule_factor_base,
        sc.damage_threshold_k, sc.damage_stress_term_dt,
        sc.damage_activation_scale,
    )

    hs.wire_max_damage = max_damage
    if max_damage >= 1.0:
        hs.is_wire_broken = 1
        return 1

    # Periodic zone-mean sampling.
    if sc.compute_zone_mean:
        hs.wire_zone_mean_counter += 1
        if hs.wire_zone_mean_counter >= sc.zone_mean_interval:
            hs.wire_last_zone_mean = _compiled_zone_mean(
                hs.wire_temperature, sc.zone_start, sc.zone_end,
            )
            hs.wire_zone_mean_counter = 0

    # Mechanics update.
    hs.wire_position_um, hs.wire_velocity_um_s, hs.mechanics_prev_accel = (
        _compiled_mechanics(
            hs.wire_position_um, hs.wire_velocity_um_s,
            hs.target_delta, hs.mechanics_prev_accel,
            sc.mechanics_mode_is_position,
            sc.damping_coeff, sc.stiffness_coeff, sc.omega_n,
            sc.max_acceleration, sc.max_jerk_dt,
            sc.max_speed, sc.mechanics_dt,
        )
    )

    # Time bookkeeping.
    hs.time += dt_int
    hs.time_since_servo += dt_int
    hs.time_since_open_voltage += dt_int

    if next_spark_state == 1:
        hs.time_since_spark_ignition += dt_int
        hs.time_since_spark_end = 0
    else:
        hs.time_since_spark_end += dt_int
        hs.time_since_spark_ignition = 0

    if hs.wire_position_um > hs.workpiece_position_um + 100.0:
        hs.is_wire_broken = 1
        return 1

    if hs.workpiece_position_um >= hs.target_position:
        hs.is_target_distance_reached = 1
        return 2

    return 0
def compiled_microstep(
    hs,  # HotStateBundle
    np_random,
    sc: SchedulerConstants,
    # pre-resolved generator settings (resolved once per control step)
    target_voltage: float,
    peak_current: float,
    on_time: float,
    off_time: float,
    # crater sampling params (resolved once per control step)
    crater_mean_um3: float,
    crater_std_um3: float,
    kerf_width_mm: float,
) -> int:
    """Execute one compiled microstep."""
    return _run_compiled_microstep(
        hs,
        np_random,
        sc,
        target_voltage,
        peak_current,
        on_time,
        off_time,
        crater_mean_um3,
        crater_std_um3,
        kerf_width_mm,
    )
