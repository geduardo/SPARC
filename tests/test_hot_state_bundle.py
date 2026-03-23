import math

import numpy as np
import pytest

from wedm import HotStateBundle, WireEDMEnv, WireModuleParameters


def test_hot_state_bundle_encodes_optional_fields_and_aliases_wire_arrays():
    env = WireEDMEnv()
    env.reset(seed=123)

    env.state.target_voltage = None
    env.state.current_mode = None
    env.state.ON_time = None
    env.state.OFF_time = None
    env.state.spark_status = [1, None, 3]
    env.state.wire_average_temperature = None
    env.ignition.random_short_remaining = 7
    env.ignition.debris_short_remaining = 5
    env.dielectric._last_gap_um = 11.5
    env.dielectric._last_debris_density = 0.25
    env.dielectric._last_flow_condition = 0.75
    env.mechanics.prev_accel = 1.25
    env.wire._last_flow_condition = None
    env.wire.zone_mean_counter = 9
    env.wire._last_zone_mean = None

    bundle = env.build_hot_state_bundle()

    assert math.isnan(bundle.target_voltage)
    assert bundle.current_mode_code == 0
    assert math.isnan(bundle.on_time_us)
    assert math.isnan(bundle.off_time_us)
    assert bundle.spark_state == 1
    assert math.isnan(bundle.spark_location_mm)
    assert bundle.spark_duration == 3
    assert math.isnan(bundle.wire_average_temperature)
    assert bundle.ignition_random_short_remaining == 7
    assert bundle.ignition_debris_short_remaining == 5
    assert bundle.dielectric_cached_gap_um == pytest.approx(11.5)
    assert bundle.dielectric_cached_debris_density == pytest.approx(0.25)
    assert bundle.dielectric_cached_flow_condition == pytest.approx(0.75)
    assert bundle.mechanics_prev_accel == pytest.approx(1.25)
    assert math.isnan(bundle.wire_last_flow_condition)
    assert bundle.wire_zone_mean_counter == 9
    assert math.isnan(bundle.wire_last_zone_mean)
    assert bundle.wire_temperature is env.wire._temperature
    assert bundle.wire_damage is env.wire._damage
    assert bundle.wire_d_t_dt is env.wire.dT_dt
    assert bundle.wire_conv_loss_coeff is env.wire.conv_loss_coeff


def test_hot_state_bundle_round_trips_state_and_module_scalars():
    env = WireEDMEnv()
    env.reset(seed=123)

    env.state.time = 99
    env.state.time_since_servo = 4
    env.state.time_since_open_voltage = 8
    env.state.time_since_spark_ignition = 2
    env.state.time_since_spark_end = 11
    env.state.voltage = 17.5
    env.state.current = 6.25
    env.state.target_voltage = 88.0
    env.state.current_mode = "I2"
    env.state.ON_time = 2.5
    env.state.OFF_time = 17.0
    env.state.workpiece_position = 13.5
    env.state.wire_position = 4.25
    env.state.wire_velocity = 6.5
    env.state.wire_unwinding_velocity = 0.3
    env.state.wire_max_damage = 0.12
    env.state.wire_average_temperature = 321.0
    env.state.wire_head_idx = 3
    env.state.wire_offset_mm = 0.45
    env.state.spark_status = [-1, 12.5, 4]
    env.state.dielectric_conductivity = 0.75
    env.state.dielectric_temperature = 303.0
    env.state.debris_concentration = 0.2
    env.state.dielectric_flow_rate = 1.5e-7
    env.state.ionized_channel = (3.2, 4)
    env.state.debris_volume = 0.012
    env.state.debris_density = 0.34
    env.state.cavity_volume = 0.056
    env.state.flow_rate = 0.78
    env.state.last_crater_volume = 1.2e-6
    env.state.is_short_circuit = True
    env.state.is_wire_broken = True
    env.state.is_wire_colliding = True
    env.state.is_target_distance_reached = True
    env.state.target_delta = -0.5
    env.state.target_position = 250.0
    env.ignition.random_short_remaining = 13
    env.ignition.debris_short_remaining = 17
    env.dielectric._last_gap_um = 9.0
    env.dielectric._last_debris_density = 0.31
    env.dielectric._last_flow_condition = 0.8
    env.mechanics.prev_accel = -2.5
    env.wire._position_offset_mm = 0.22
    env.wire._last_flow_condition = 0.42
    env.wire.zone_mean_counter = 7
    env.wire._last_zone_mean = 318.0
    env.wire._temperature.fill(305.0)
    env.wire._damage.fill(0.01)
    env.wire.dT_dt.fill(0.5)
    env.wire.conv_loss_coeff.fill(2.0)

    bundle = HotStateBundle.from_env(env)

    restored_env = WireEDMEnv()
    restored_env.reset(seed=999)
    restored_env.apply_hot_state_bundle(bundle)

    assert restored_env.state.time == 99
    assert restored_env.state.time_since_servo == 4
    assert restored_env.state.time_since_open_voltage == 8
    assert restored_env.state.time_since_spark_ignition == 2
    assert restored_env.state.time_since_spark_end == 11
    assert restored_env.state.voltage == pytest.approx(17.5)
    assert restored_env.state.current == pytest.approx(6.25)
    assert restored_env.state.target_voltage == pytest.approx(88.0)
    assert restored_env.state.current_mode == "I2"
    assert restored_env.state.ON_time == pytest.approx(2.5)
    assert restored_env.state.OFF_time == pytest.approx(17.0)
    assert restored_env.state.workpiece_position == pytest.approx(13.5)
    assert restored_env.state.wire_position == pytest.approx(4.25)
    assert restored_env.state.wire_velocity == pytest.approx(6.5)
    assert restored_env.state.wire_unwinding_velocity == pytest.approx(0.3)
    assert restored_env.state.wire_max_damage == pytest.approx(0.12)
    assert restored_env.state.wire_average_temperature == pytest.approx(321.0)
    assert restored_env.state.wire_head_idx == 3
    assert restored_env.state.wire_offset_mm == pytest.approx(0.45)
    assert restored_env.state.spark_status == [-1, 12.5, 4]
    assert restored_env.state.dielectric_conductivity == pytest.approx(0.75)
    assert restored_env.state.dielectric_temperature == pytest.approx(303.0)
    assert restored_env.state.debris_concentration == pytest.approx(0.2)
    assert restored_env.state.dielectric_flow_rate == pytest.approx(1.5e-7)
    assert restored_env.state.ionized_channel == (3.2, 4)
    assert restored_env.state.debris_volume == pytest.approx(0.012)
    assert restored_env.state.debris_density == pytest.approx(0.34)
    assert restored_env.state.cavity_volume == pytest.approx(0.056)
    assert restored_env.state.flow_rate == pytest.approx(0.78)
    assert restored_env.state.last_crater_volume == pytest.approx(1.2e-6)
    assert restored_env.state.is_short_circuit is True
    assert restored_env.state.is_wire_broken is True
    assert restored_env.state.is_wire_colliding is True
    assert restored_env.state.is_target_distance_reached is True
    assert restored_env.state.target_delta == pytest.approx(-0.5)
    assert restored_env.state.target_position == pytest.approx(250.0)
    assert restored_env.ignition.random_short_remaining == 13
    assert restored_env.ignition.debris_short_remaining == 17
    assert restored_env.dielectric._last_gap_um == pytest.approx(9.0)
    assert restored_env.dielectric._last_debris_density == pytest.approx(0.31)
    assert restored_env.dielectric._last_flow_condition == pytest.approx(0.8)
    assert restored_env.mechanics.prev_accel == pytest.approx(-2.5)
    assert restored_env.wire._position_offset_mm == pytest.approx(0.22)
    assert restored_env.wire._last_flow_condition == pytest.approx(0.42)
    assert restored_env.wire.zone_mean_counter == 7
    assert restored_env.wire._last_zone_mean == pytest.approx(318.0)
    assert restored_env.state.wire_temperature is bundle.wire_temperature
    assert restored_env.state.wire_damage is bundle.wire_damage
    np.testing.assert_allclose(restored_env.wire._temperature, 305.0)
    np.testing.assert_allclose(restored_env.wire._damage, 0.01)
    np.testing.assert_allclose(restored_env.wire.dT_dt, 0.5)
    np.testing.assert_allclose(restored_env.wire.conv_loss_coeff, 2.0)


def test_hot_state_bundle_rejects_incompatible_wire_shapes():
    env = WireEDMEnv()
    env.reset(seed=123)
    bundle = env.build_hot_state_bundle()

    other_env = WireEDMEnv(wire_params=WireModuleParameters(segment_len=0.05))
    other_env.reset(seed=123)

    with pytest.raises(ValueError, match="shape is incompatible"):
        other_env.apply_hot_state_bundle(bundle)
