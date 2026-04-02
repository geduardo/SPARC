from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np


_FLOAT_SENTINEL = math.nan
_MODE_NONE = 0


def _encode_optional_float(value: float | None) -> float:
    return _FLOAT_SENTINEL if value is None else float(value)


def _decode_optional_float(value: float) -> float | None:
    return None if math.isnan(value) else value


def _encode_current_mode(value: str | None) -> int:
    if value and value.startswith("I") and value[1:].isdigit():
        return int(value[1:])
    return _MODE_NONE


def _decode_current_mode(value: int) -> str | None:
    if value <= _MODE_NONE:
        return None
    return f"I{value}"


@dataclass(slots=True)
class HotStateBundle:
    """Numeric, scheduler-friendly mirror of env state and hot module internals."""

    time: int
    time_since_servo: int
    time_since_open_voltage: int
    time_since_spark_ignition: int
    time_since_spark_end: int
    voltage: float
    current: float
    target_voltage: float
    current_mode_code: int
    off_time_us: float
    on_time_us: float
    workpiece_position_um: float
    wire_position_um: float
    wire_velocity_um_s: float
    wire_unwinding_velocity_um_us: float
    wire_max_damage: float
    wire_average_temperature: float
    wire_head_idx: int
    wire_offset_mm: float
    spark_state: int
    spark_location_mm: float
    spark_duration: int
    dielectric_conductivity: float
    dielectric_temperature: float
    debris_concentration: float
    dielectric_flow_rate: float
    ionized_channel_location_mm: float
    ionized_channel_duration: int
    debris_volume: float
    debris_density: float
    cavity_volume: float
    flow_rate: float
    last_crater_volume: float
    is_short_circuit: int
    is_wire_broken: int
    is_wire_colliding: int
    is_target_distance_reached: int
    target_delta: float
    target_position: float
    ignition_random_short_remaining: int
    ignition_debris_short_remaining: int
    dielectric_cached_gap_um: float
    dielectric_cached_debris_density: float
    dielectric_cached_flow_condition: float
    mechanics_prev_accel: float
    wire_position_offset_mm: float
    wire_last_flow_condition: float
    wire_zone_mean_counter: int
    wire_last_zone_mean: float
    wire_temperature: np.ndarray
    wire_damage: np.ndarray
    wire_d_t_dt: np.ndarray
    wire_conv_loss_coeff: np.ndarray

    @classmethod
    def from_env(cls, env: Any, *, copy_arrays: bool = False) -> "HotStateBundle":
        """Build a bundle from a live environment.

        By default the bundle **aliases** the wire module's internal arrays
        (temperature, damage, dT_dt, conv_loss_coeff) for zero-copy speed on
        the same-env compiled path.  Pass ``copy_arrays=True`` when the bundle
        will be applied to a *different* env to avoid shared-buffer hazards.
        """
        state = env.state
        ignition = env.ignition
        dielectric = env.dielectric
        mechanics = env.mechanics
        wire = env.wire

        ionized_channel_location_mm = _FLOAT_SENTINEL
        ionized_channel_duration = 0
        if state.ionized_channel is not None:
            ionized_channel_location_mm = float(state.ionized_channel[0])
            ionized_channel_duration = int(state.ionized_channel[1])

        return cls(
            time=int(state.time),
            time_since_servo=int(state.time_since_servo),
            time_since_open_voltage=int(state.time_since_open_voltage),
            time_since_spark_ignition=int(state.time_since_spark_ignition),
            time_since_spark_end=int(state.time_since_spark_end),
            voltage=float(state.voltage),
            current=float(state.current),
            target_voltage=_encode_optional_float(state.target_voltage),
            current_mode_code=_encode_current_mode(state.current_mode),
            off_time_us=_encode_optional_float(state.OFF_time),
            on_time_us=_encode_optional_float(state.ON_time),
            workpiece_position_um=float(state.workpiece_position),
            wire_position_um=float(state.wire_position),
            wire_velocity_um_s=float(state.wire_velocity),
            wire_unwinding_velocity_um_us=float(state.wire_unwinding_velocity),
            wire_max_damage=float(state.wire_max_damage),
            wire_average_temperature=_encode_optional_float(
                state.wire_average_temperature
            ),
            wire_head_idx=int(state.wire_head_idx),
            wire_offset_mm=float(state.wire_offset_mm),
            spark_state=int(state.spark_status[0]),
            spark_location_mm=_encode_optional_float(state.spark_status[1]),
            spark_duration=int(state.spark_status[2]),
            dielectric_conductivity=float(state.dielectric_conductivity),
            dielectric_temperature=float(state.dielectric_temperature),
            debris_concentration=float(state.debris_concentration),
            dielectric_flow_rate=float(state.dielectric_flow_rate),
            ionized_channel_location_mm=ionized_channel_location_mm,
            ionized_channel_duration=ionized_channel_duration,
            debris_volume=float(state.debris_volume),
            debris_density=float(state.debris_density),
            cavity_volume=float(state.cavity_volume),
            flow_rate=float(state.flow_rate),
            last_crater_volume=float(state.last_crater_volume),
            is_short_circuit=int(state.is_short_circuit),
            is_wire_broken=int(state.is_wire_broken),
            is_wire_colliding=int(state.is_wire_colliding),
            is_target_distance_reached=int(state.is_target_distance_reached),
            target_delta=float(state.target_delta),
            target_position=float(state.target_position),
            ignition_random_short_remaining=int(ignition.random_short_remaining),
            ignition_debris_short_remaining=int(ignition.debris_short_remaining),
            dielectric_cached_gap_um=float(dielectric._last_gap_um),
            dielectric_cached_debris_density=float(dielectric._last_debris_density),
            dielectric_cached_flow_condition=float(dielectric._last_flow_condition),
            mechanics_prev_accel=float(mechanics.prev_accel),
            wire_position_offset_mm=float(wire._position_offset_mm),
            wire_last_flow_condition=_encode_optional_float(wire._last_flow_condition),
            wire_zone_mean_counter=int(wire.zone_mean_counter),
            wire_last_zone_mean=_encode_optional_float(wire._last_zone_mean),
            wire_temperature=wire._temperature.copy() if copy_arrays else wire._temperature,
            wire_damage=wire._damage.copy() if copy_arrays else wire._damage,
            wire_d_t_dt=wire.dT_dt.copy() if copy_arrays else wire.dT_dt,
            wire_conv_loss_coeff=wire.conv_loss_coeff.copy() if copy_arrays else wire.conv_loss_coeff,
        )

    def apply_to_env(self, env: Any) -> None:
        """Write bundle scalars and arrays back into *env*.

        Array fields are always **copied** into the target wire module's
        existing buffers (via ``np.copyto``) so that the bundle and the env
        never silently share the same underlying memory.
        """
        wire = env.wire
        if wire._temperature.shape != self.wire_temperature.shape:
            raise ValueError("HotStateBundle wire_temperature shape is incompatible")
        if wire._damage.shape != self.wire_damage.shape:
            raise ValueError("HotStateBundle wire_damage shape is incompatible")
        if wire.dT_dt.shape != self.wire_d_t_dt.shape:
            raise ValueError("HotStateBundle wire_d_t_dt shape is incompatible")
        if wire.conv_loss_coeff.shape != self.wire_conv_loss_coeff.shape:
            raise ValueError("HotStateBundle wire_conv_loss_coeff shape is incompatible")

        state = env.state
        ignition = env.ignition
        dielectric = env.dielectric
        mechanics = env.mechanics

        state.time = self.time
        state.time_since_servo = self.time_since_servo
        state.time_since_open_voltage = self.time_since_open_voltage
        state.time_since_spark_ignition = self.time_since_spark_ignition
        state.time_since_spark_end = self.time_since_spark_end
        state.voltage = self.voltage
        state.current = self.current
        state.target_voltage = _decode_optional_float(self.target_voltage)
        state.current_mode = _decode_current_mode(self.current_mode_code)
        state.OFF_time = _decode_optional_float(self.off_time_us)
        state.ON_time = _decode_optional_float(self.on_time_us)
        state.workpiece_position = self.workpiece_position_um
        state.wire_position = self.wire_position_um
        state.wire_velocity = self.wire_velocity_um_s
        state.wire_unwinding_velocity = self.wire_unwinding_velocity_um_us
        state.wire_max_damage = self.wire_max_damage
        state.wire_average_temperature = _decode_optional_float(
            self.wire_average_temperature
        )
        state.wire_head_idx = self.wire_head_idx
        state.wire_offset_mm = self.wire_offset_mm
        state.spark_status = [
            self.spark_state,
            _decode_optional_float(self.spark_location_mm),
            self.spark_duration,
        ]
        state.dielectric_conductivity = self.dielectric_conductivity
        state.dielectric_temperature = self.dielectric_temperature
        state.debris_concentration = self.debris_concentration
        state.dielectric_flow_rate = self.dielectric_flow_rate
        ionized_channel_location = _decode_optional_float(
            self.ionized_channel_location_mm
        )
        state.ionized_channel = (
            None
            if ionized_channel_location is None
            else (ionized_channel_location, self.ionized_channel_duration)
        )
        state.debris_volume = self.debris_volume
        state.debris_density = self.debris_density
        state.cavity_volume = self.cavity_volume
        state.flow_rate = self.flow_rate
        state.last_crater_volume = self.last_crater_volume
        state.is_short_circuit = bool(self.is_short_circuit)
        state.is_wire_broken = bool(self.is_wire_broken)
        state.is_wire_colliding = bool(self.is_wire_colliding)
        state.is_target_distance_reached = bool(self.is_target_distance_reached)
        state.target_delta = self.target_delta
        state.target_position = self.target_position

        ignition.random_short_remaining = self.ignition_random_short_remaining
        ignition.debris_short_remaining = self.ignition_debris_short_remaining

        dielectric.debris_volume = self.debris_volume
        dielectric.debris_density = self.debris_density
        dielectric.cavity_volume = self.cavity_volume
        dielectric.flow_condition = self.flow_rate
        dielectric.ion_channel = state.ionized_channel
        dielectric._last_gap_um = self.dielectric_cached_gap_um
        dielectric._last_debris_density = self.dielectric_cached_debris_density
        dielectric._last_flow_condition = self.dielectric_cached_flow_condition

        mechanics.prev_accel = self.mechanics_prev_accel

        wire._position_offset_mm = self.wire_position_offset_mm
        wire._last_flow_condition = _decode_optional_float(self.wire_last_flow_condition)
        wire.zone_mean_counter = self.wire_zone_mean_counter
        wire._last_zone_mean = _decode_optional_float(self.wire_last_zone_mean)
        np.copyto(wire._temperature, self.wire_temperature)
        np.copyto(wire._damage, self.wire_damage)
        np.copyto(wire.dT_dt, self.wire_d_t_dt)
        np.copyto(wire.conv_loss_coeff, self.wire_conv_loss_coeff)

        state.wire_temperature = wire._temperature
        state.wire_damage = wire._damage

