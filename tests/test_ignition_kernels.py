"""Low-level regression tests for compiled ignition helpers."""

import math

import pytest

from wedm.modules.ignition import (
    _advance_discharge_state,
    _advance_short_circuit_state,
    _get_ignition_probability_scalar,
    _roll_new_debris_short_state,
    _roll_new_short_circuit_state,
)


def test_advance_short_circuit_state_counts_down_active_random_short():
    random_remaining, debris_remaining, is_short = _advance_short_circuit_state(
        gap=10.0,
        dt=3,
        debris_density=0.0,
        random_short_remaining=7,
        debris_short_remaining=0,
        debris_roll=1.0,
        random_roll=1.0,
        hard_short_gap=2.0,
        base_critical_density=0.3,
        gap_coefficient=0.02,
        max_critical_density=0.95,
        sigmoid_steepness=500.0,
        debris_short_duration=50,
        random_short_duration=100,
        random_short_min_gap=2.0,
        random_short_max_gap=50.0,
        random_short_max_probability=0.001,
    )

    assert random_remaining == 4
    assert debris_remaining == 0
    assert is_short is True


def test_advance_discharge_state_ignites_from_idle():
    spark_state, spark_location, spark_duration, voltage, current = (
        _advance_discharge_state(
            spark_state=0,
            spark_location_mm=math.nan,
            spark_duration=0,
            is_short_circuit=False,
            current_voltage=80.0,
            target_voltage=80.0,
            peak_current=18.0,
            on_time=3.0,
            off_time=20.0,
            spark_voltage_factor=0.3,
            workpiece_height=20.0,
            ignition_probability=0.5,
            ignition_roll=0.1,
            spark_location_roll=0.25,
        )
    )

    assert spark_state == 1
    assert spark_location == pytest.approx(5.0)
    assert spark_duration == 0
    assert voltage == pytest.approx(24.0)
    assert current == pytest.approx(18.0)


def test_get_ignition_probability_scalar_uses_rounded_gap_formula():
    probability = _get_ignition_probability_scalar(
        gap=12.3456,
        rounded_gap=12.35,
        dt=1,
        log2_value=math.log(2.0),
        ignition_a_coeff=0.48,
        ignition_b_coeff=-3.69,
        ignition_c_coeff=14.05,
    )

    denominator = 0.48 * (12.35**2) - 3.69 * 12.35 + 14.05
    expected = 1.0 - math.exp(-(math.log(2.0) / denominator))
    assert probability == pytest.approx(expected)


def test_roll_new_debris_short_state_matches_legacy_helper_for_unit_dt():
    is_short = _roll_new_debris_short_state(
        gap=12.0,
        dt=1,
        debris_density=0.6,
        debris_roll=0.25,
        hard_short_gap=2.0,
        base_critical_density=0.3,
        gap_coefficient=0.02,
        max_critical_density=0.95,
        sigmoid_steepness=500.0,
    )

    _, debris_remaining, legacy_is_short = _advance_short_circuit_state(
        gap=12.0,
        dt=1,
        debris_density=0.6,
        random_short_remaining=0,
        debris_short_remaining=0,
        debris_roll=0.25,
        random_roll=1.0,
        hard_short_gap=2.0,
        base_critical_density=0.3,
        gap_coefficient=0.02,
        max_critical_density=0.95,
        sigmoid_steepness=500.0,
        debris_short_duration=50,
        random_short_duration=100,
        random_short_min_gap=2.0,
        random_short_max_gap=50.0,
        random_short_max_probability=0.0,
    )

    assert is_short is legacy_is_short
    assert debris_remaining == (50 if is_short else 0)


def test_roll_new_short_circuit_state_can_trigger_random_short():
    outcome = _roll_new_short_circuit_state(
        gap=2.5,
        dt=1,
        debris_density=0.0,
        debris_roll=1.0,
        random_roll=0.0,
        hard_short_gap=2.0,
        base_critical_density=0.3,
        gap_coefficient=0.02,
        max_critical_density=0.95,
        sigmoid_steepness=500.0,
        random_short_min_gap=2.0,
        random_short_max_gap=50.0,
        random_short_max_probability=0.5,
    )

    assert outcome == 2
