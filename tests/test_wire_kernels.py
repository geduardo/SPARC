"""Low-level regression tests for optimized wire kernels."""

import numpy as np

from wedm.modules.wire import (
    advance_wire_step_inplace,
    accumulate_damage,
    apply_thermal_core_inplace,
    apply_thermal_damage_core_inplace,
    resolve_discharge_partition,
)


def _thermal_reference(
    temperature: np.ndarray,
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
) -> np.ndarray:
    expected = temperature.copy()
    dT_dt = np.zeros_like(expected)

    if expected.shape[0] > 1:
        dT_dt[1:-1] = k_cond_coeff * (
            expected[:-2] - 2.0 * expected[1:-1] + expected[2:]
        ) - conv_loss_coeff[1:-1] * (expected[1:-1] - dielectric_temp)
        dT_dt[-1] = k_cond_coeff * (expected[-2] - expected[-1]) - conv_loss_coeff[
            -1
        ] * (expected[-1] - dielectric_temp)

    if bottom_joule_factor != 0.0:
        dT_dt[bottom_start:bottom_end] += bottom_joule_factor * (
            1.0 + alpha_rho * (expected[bottom_start:bottom_end] - temp_ref)
        )

    if top_joule_factor != 0.0:
        dT_dt[top_start:top_end] += top_joule_factor * (
            1.0 + alpha_rho * (expected[top_start:top_end] - temp_ref)
        )

    if 0 <= plasma_idx < expected.shape[0]:
        dT_dt[plasma_idx] += plasma_heat

    expected[1:] += dT_dt[1:] * temp_update_factor
    expected[0] = spool_temp
    return expected


def _resolve_partition_reference(
    spark_state: int,
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
    plasma_idx = -1
    plasma_heat = 0.0
    bottom_start = 0
    bottom_end = 0
    bottom_joule_factor = 0.0
    top_start = 0
    top_end = 0
    top_joule_factor = 0.0
    is_active_discharge = spark_state == 1 or spark_state == -1

    if is_active_discharge and not np.isnan(spark_location_mm):
        if segment_len_mm > 0.0 and zone_end > zone_start:
            rel_idx_float = spark_location_mm / segment_len_mm
            zone_len = zone_end - zone_start
            rel_idx = int(min(max(0.0, rel_idx_float), zone_len - 1))
            plasma_idx = zone_start + rel_idx

        if 0 <= plasma_idx < n_segments:
            plasma_heat = plasma_efficiency * voltage * current
            if not np.isfinite(plasma_heat):
                plasma_heat = 0.0

    if (
        is_active_discharge
        and current_squared > 1e-6
        and contact_top_idx >= contact_bottom_idx
    ):
        spark_idx = plasma_idx
        if spark_idx < 0 and not np.isnan(spark_location_mm):
            spark_idx = int(
                min(max(spark_location_mm / segment_len_mm, 0.0), n_segments - 1)
            )

        spark_idx = min(max(int(spark_idx), contact_bottom_idx), contact_top_idx)

        l_bottom = max(0, spark_idx - contact_bottom_idx)
        l_top = max(0, contact_top_idx - spark_idx)
        total_length = l_bottom + l_top
        if total_length > 0:
            if l_bottom == 0:
                i_bottom = 0.0
                i_top = current
            elif l_top == 0:
                i_bottom = current
                i_top = 0.0
            else:
                i_bottom = current * (l_top / total_length)
                i_top = current * (l_bottom / total_length)
        else:
            i_bottom = current * 0.5
            i_top = current * 0.5

        if l_bottom > 0 and spark_idx > contact_bottom_idx:
            bottom_start = contact_bottom_idx
            bottom_end = spark_idx
            bottom_joule_factor = joule_factor_base * (i_bottom * i_bottom)

        if l_top > 0 and spark_idx < contact_top_idx:
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


def _advance_wire_reference_step(
    temperature: np.ndarray,
    damage: np.ndarray,
    conv_loss_coeff: np.ndarray,
    position_offset_mm: float,
    wrap_threshold_mm: float,
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
) -> tuple[np.ndarray, np.ndarray, float, float]:
    expected_temperature = temperature.copy()
    expected_damage = damage.copy()
    expected_position_offset = position_offset_mm + delta_mm
    rollover_count = 0

    while expected_position_offset > wrap_threshold_mm:
        expected_position_offset -= wrap_threshold_mm
        rollover_count += 1

    if rollover_count >= expected_temperature.shape[0]:
        expected_temperature.fill(spool_temp)
        expected_damage.fill(0.0)
    elif rollover_count > 0:
        expected_temperature[rollover_count:] = expected_temperature[:-rollover_count]
        expected_damage[rollover_count:] = expected_damage[:-rollover_count]
        expected_temperature[:rollover_count] = spool_temp
        expected_damage[:rollover_count] = 0.0

    partition = _resolve_partition_reference(
        spark_state=spark_state,
        spark_location_mm=spark_location_mm if has_spark_location else np.nan,
        voltage=voltage,
        current=current,
        current_squared=current_squared,
        segment_len_mm=segment_len_mm,
        zone_start=zone_start,
        zone_end=zone_end,
        n_segments=expected_temperature.shape[0],
        contact_bottom_idx=contact_bottom_idx,
        contact_top_idx=contact_top_idx,
        plasma_efficiency=plasma_efficiency,
        joule_factor_base=joule_factor_base,
    )
    expected_temperature = _thermal_reference(
        expected_temperature,
        conv_loss_coeff,
        k_cond_coeff=k_cond_coeff,
        temp_update_factor=temp_update_factor,
        dielectric_temp=dielectric_temp,
        temp_ref=temp_ref,
        alpha_rho=alpha_rho,
        bottom_start=partition[2],
        bottom_end=partition[3],
        bottom_joule_factor=partition[4],
        top_start=partition[5],
        top_end=partition[6],
        top_joule_factor=partition[7],
        plasma_idx=partition[0],
        plasma_heat=partition[1],
        spool_temp=spool_temp,
    )
    expected_max_damage = accumulate_damage(
        expected_damage,
        expected_temperature,
        threshold_k,
        stress_term_dt,
        activation_scale,
    )
    return (
        expected_temperature,
        expected_damage,
        expected_position_offset,
        expected_max_damage,
    )


def test_apply_thermal_core_inplace_matches_reference():
    temperature = np.array(
        [293.15, 305.0, 318.5, 330.0, 341.0, 352.5], dtype=np.float32
    )
    dT_dt = np.zeros_like(temperature)
    conv_loss_coeff = np.array([0.0, 0.7, 0.8, 0.9, 1.0, 1.1], dtype=np.float32)

    params = {
        "k_cond_coeff": 2.4,
        "temp_update_factor": 1.5e-4,
        "dielectric_temp": 298.0,
        "temp_ref": 293.15,
        "alpha_rho": 0.0034,
        "bottom_start": 1,
        "bottom_end": 3,
        "bottom_joule_factor": 0.85,
        "top_start": 4,
        "top_end": 6,
        "top_joule_factor": 0.55,
        "plasma_idx": 3,
        "plasma_heat": 12.0,
        "spool_temp": 293.15,
    }

    expected = _thermal_reference(
        temperature,
        conv_loss_coeff,
        **params,
    )

    apply_thermal_core_inplace(
        temperature,
        dT_dt,
        conv_loss_coeff,
        params["k_cond_coeff"],
        params["temp_update_factor"],
        params["dielectric_temp"],
        params["temp_ref"],
        params["alpha_rho"],
        params["bottom_start"],
        params["bottom_end"],
        params["bottom_joule_factor"],
        params["top_start"],
        params["top_end"],
        params["top_joule_factor"],
        params["plasma_idx"],
        params["plasma_heat"],
        params["spool_temp"],
    )

    np.testing.assert_allclose(temperature, expected, rtol=1e-6, atol=1e-6)


def test_apply_thermal_damage_core_inplace_matches_legacy_composition():
    temperature = np.array(
        [293.15, 305.0, 318.5, 330.0, 341.0, 352.5], dtype=np.float32
    )
    damage = np.array([0.0, 0.2, 0.0, 0.1, 0.4, 0.0], dtype=np.float32)
    dT_dt = np.zeros_like(temperature)
    conv_loss_coeff = np.array([0.0, 0.7, 0.8, 0.9, 1.0, 1.1], dtype=np.float32)

    params = {
        "k_cond_coeff": 2.4,
        "temp_update_factor": 1.5e-4,
        "dielectric_temp": 298.0,
        "temp_ref": 293.15,
        "alpha_rho": 0.0034,
        "bottom_start": 1,
        "bottom_end": 3,
        "bottom_joule_factor": 0.85,
        "top_start": 4,
        "top_end": 6,
        "top_joule_factor": 0.55,
        "plasma_idx": 3,
        "plasma_heat": 12.0,
        "spool_temp": 293.15,
    }
    damage_params = {
        "threshold_k": 320.0,
        "stress_term_dt": 1.3e-4,
        "activation_scale": -175.0,
    }

    expected_temperature = _thermal_reference(
        temperature,
        conv_loss_coeff,
        **params,
    )
    expected_damage = damage.copy()
    expected_max_damage = accumulate_damage(
        expected_damage,
        expected_temperature,
        damage_params["threshold_k"],
        damage_params["stress_term_dt"],
        damage_params["activation_scale"],
    )

    max_damage = apply_thermal_damage_core_inplace(
        temperature,
        damage,
        dT_dt,
        conv_loss_coeff,
        params["k_cond_coeff"],
        params["temp_update_factor"],
        params["dielectric_temp"],
        params["temp_ref"],
        params["alpha_rho"],
        params["bottom_start"],
        params["bottom_end"],
        params["bottom_joule_factor"],
        params["top_start"],
        params["top_end"],
        params["top_joule_factor"],
        params["plasma_idx"],
        params["plasma_heat"],
        params["spool_temp"],
        damage_params["threshold_k"],
        damage_params["stress_term_dt"],
        damage_params["activation_scale"],
    )

    np.testing.assert_allclose(temperature, expected_temperature, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(damage, expected_damage, rtol=1e-6, atol=1e-6)
    assert max_damage == expected_max_damage

def test_resolve_discharge_partition_matches_reference():
    expected = _resolve_partition_reference(
        spark_state=1,
        spark_location_mm=4.6,
        voltage=90.0,
        current=30.0,
        current_squared=900.0,
        segment_len_mm=0.2,
        zone_start=150,
        zone_end=250,
        n_segments=400,
        contact_bottom_idx=100,
        contact_top_idx=300,
        plasma_efficiency=0.25,
        joule_factor_base=0.015,
    )

    actual = resolve_discharge_partition(
        spark_state=1,
        has_spark_location=True,
        spark_location_mm=4.6,
        voltage=90.0,
        current=30.0,
        current_squared=900.0,
        segment_len_mm=0.2,
        zone_start=150,
        zone_end=250,
        n_segments=400,
        contact_bottom_idx=100,
        contact_top_idx=300,
        plasma_efficiency=0.25,
        joule_factor_base=0.015,
    )

    np.testing.assert_allclose(
        np.array(actual, dtype=np.float64),
        np.array(expected, dtype=np.float64),
        rtol=1e-6,
        atol=1e-6,
    )


def test_advance_wire_step_inplace_matches_reference():
    temperature = np.array(
        [293.15, 305.0, 318.5, 330.0, 341.0, 352.5], dtype=np.float32
    )
    damage = np.array([0.0, 0.2, 0.0, 0.1, 0.4, 0.0], dtype=np.float32)
    dT_dt = np.zeros_like(temperature)
    conv_loss_coeff = np.array([0.0, 0.7, 0.8, 0.9, 1.0, 1.1], dtype=np.float32)

    position_offset_mm = 0.03
    wrap_threshold_mm = 0.05
    delta_mm = 0.08
    spool_temp = 293.15

    (
        expected_temperature,
        expected_damage,
        expected_position_offset,
        expected_max_damage,
    ) = _advance_wire_reference_step(
        temperature,
        damage,
        conv_loss_coeff,
        position_offset_mm=position_offset_mm,
        wrap_threshold_mm=wrap_threshold_mm,
        delta_mm=delta_mm,
        spool_temp=spool_temp,
        k_cond_coeff=2.4,
        temp_update_factor=1.5e-4,
        dielectric_temp=298.0,
        temp_ref=293.15,
        alpha_rho=0.0034,
        spark_state=1,
        has_spark_location=True,
        spark_location_mm=0.55,
        voltage=90.0,
        current=30.0,
        current_squared=900.0,
        segment_len_mm=0.2,
        zone_start=1,
        zone_end=5,
        contact_bottom_idx=0,
        contact_top_idx=5,
        plasma_efficiency=0.25,
        joule_factor_base=0.015,
        threshold_k=320.0,
        stress_term_dt=1.3e-4,
        activation_scale=-175.0,
    )

    actual_position_offset, actual_max_damage = advance_wire_step_inplace(
        temperature,
        damage,
        dT_dt,
        conv_loss_coeff,
        position_offset_mm,
        wrap_threshold_mm,
        delta_mm,
        spool_temp,
        2.4,
        1.5e-4,
        298.0,
        293.15,
        0.0034,
        1,
        True,
        0.55,
        90.0,
        30.0,
        900.0,
        0.2,
        1,
        5,
        0,
        5,
        0.25,
        0.015,
        320.0,
        1.3e-4,
        -175.0,
    )

    assert actual_position_offset == expected_position_offset
    np.testing.assert_allclose(temperature, expected_temperature, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(damage, expected_damage, rtol=1e-6, atol=1e-6)
    assert actual_max_damage == expected_max_damage


def test_advance_wire_step_inplace_matches_resolved_partition_composition():
    temperature = np.array(
        [293.15, 305.0, 318.5, 330.0, 341.0, 352.5], dtype=np.float32
    )
    damage = np.array([0.0, 0.2, 0.0, 0.1, 0.4, 0.0], dtype=np.float32)
    dT_dt = np.zeros_like(temperature)
    conv_loss_coeff = np.array([0.0, 0.7, 0.8, 0.9, 1.0, 1.1], dtype=np.float32)

    expected_temperature = temperature.copy()
    expected_damage = damage.copy()
    expected_dT_dt = np.zeros_like(dT_dt)
    expected_position_offset = 0.03
    wrap_threshold_mm = 0.05
    delta_mm = 0.08
    spool_temp = 293.15

    expected_position_offset += delta_mm
    rollover_count = 0
    while expected_position_offset > wrap_threshold_mm:
        expected_position_offset -= wrap_threshold_mm
        rollover_count += 1

    if rollover_count >= expected_temperature.shape[0]:
        expected_temperature.fill(spool_temp)
        expected_damage.fill(0.0)
    elif rollover_count > 0:
        expected_temperature[rollover_count:] = expected_temperature[:-rollover_count]
        expected_damage[rollover_count:] = expected_damage[:-rollover_count]
        expected_temperature[:rollover_count] = spool_temp
        expected_damage[:rollover_count] = 0.0

    partition = resolve_discharge_partition(
        spark_state=1,
        has_spark_location=True,
        spark_location_mm=0.55,
        voltage=90.0,
        current=30.0,
        current_squared=900.0,
        segment_len_mm=0.2,
        zone_start=1,
        zone_end=5,
        n_segments=expected_temperature.shape[0],
        contact_bottom_idx=0,
        contact_top_idx=5,
        plasma_efficiency=0.25,
        joule_factor_base=0.015,
    )
    expected_max_damage = apply_thermal_damage_core_inplace(
        expected_temperature,
        expected_damage,
        expected_dT_dt,
        conv_loss_coeff,
        2.4,
        1.5e-4,
        298.0,
        293.15,
        0.0034,
        partition[2],
        partition[3],
        partition[4],
        partition[5],
        partition[6],
        partition[7],
        partition[0],
        partition[1],
        spool_temp,
        320.0,
        1.3e-4,
        -175.0,
    )

    actual_temperature = temperature.copy()
    actual_damage = damage.copy()
    actual_position_offset, actual_max_damage = advance_wire_step_inplace(
        actual_temperature,
        actual_damage,
        dT_dt,
        conv_loss_coeff,
        0.03,
        wrap_threshold_mm,
        delta_mm,
        spool_temp,
        2.4,
        1.5e-4,
        298.0,
        293.15,
        0.0034,
        1,
        True,
        0.55,
        90.0,
        30.0,
        900.0,
        0.2,
        1,
        5,
        0,
        5,
        0.25,
        0.015,
        320.0,
        1.3e-4,
        -175.0,
    )

    np.testing.assert_allclose(actual_temperature, expected_temperature, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(actual_damage, expected_damage, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(actual_position_offset, expected_position_offset)
    np.testing.assert_allclose(actual_max_damage, expected_max_damage)


def test_advance_wire_step_inplace_matches_reference_across_multiple_steps():
    temperature = np.array(
        [293.15, 305.0, 318.5, 452.0, 341.0, 470.0, 352.5, 293.15],
        dtype=np.float32,
    )
    damage = np.array([0.0, 0.2, 0.0, 0.1, 0.4, 0.3, 0.0, 0.0], dtype=np.float32)
    dT_dt = np.zeros_like(temperature)
    conv_loss_coeff = np.array([0.0, 0.7, 0.8, 0.9, 1.0, 1.1, 1.15, 1.2], dtype=np.float32)

    expected_temperature = temperature.copy()
    expected_damage = damage.copy()
    actual_temperature = temperature.copy()
    actual_damage = damage.copy()
    expected_position_offset = 0.02
    actual_position_offset = 0.02

    steps = [
        {
            "delta_mm": 0.0,
            "spark_state": 1,
            "has_spark_location": True,
            "spark_location_mm": 0.55,
            "voltage": 90.0,
            "current": 30.0,
            "current_squared": 900.0,
        },
        {
            "delta_mm": 0.07,
            "spark_state": 1,
            "has_spark_location": True,
            "spark_location_mm": 0.35,
            "voltage": 90.0,
            "current": 30.0,
            "current_squared": 900.0,
        },
        {
            "delta_mm": 0.02,
            "spark_state": 0,
            "has_spark_location": False,
            "spark_location_mm": 0.0,
            "voltage": 80.0,
            "current": 0.0,
            "current_squared": 0.0,
        },
        {
            "delta_mm": 0.0,
            "spark_state": -1,
            "has_spark_location": True,
            "spark_location_mm": 0.95,
            "voltage": 90.0,
            "current": 24.0,
            "current_squared": 576.0,
        },
    ]

    for step in steps:
        (
            expected_temperature,
            expected_damage,
            expected_position_offset,
            expected_max_damage,
        ) = _advance_wire_reference_step(
            expected_temperature,
            expected_damage,
            conv_loss_coeff,
            position_offset_mm=expected_position_offset,
            wrap_threshold_mm=0.05,
            delta_mm=step["delta_mm"],
            spool_temp=293.15,
            k_cond_coeff=2.4,
            temp_update_factor=1.5e-4,
            dielectric_temp=298.0,
            temp_ref=293.15,
            alpha_rho=0.0034,
            spark_state=step["spark_state"],
            has_spark_location=step["has_spark_location"],
            spark_location_mm=step["spark_location_mm"],
            voltage=step["voltage"],
            current=step["current"],
            current_squared=step["current_squared"],
            segment_len_mm=0.2,
            zone_start=1,
            zone_end=6,
            contact_bottom_idx=0,
            contact_top_idx=7,
            plasma_efficiency=0.25,
            joule_factor_base=0.015,
            threshold_k=320.0,
            stress_term_dt=1.3e-4,
            activation_scale=-175.0,
        )

        actual_position_offset, actual_max_damage = advance_wire_step_inplace(
            actual_temperature,
            actual_damage,
            dT_dt,
            conv_loss_coeff,
            actual_position_offset,
            0.05,
            step["delta_mm"],
            293.15,
            2.4,
            1.5e-4,
            298.0,
            293.15,
            0.0034,
            step["spark_state"],
            step["has_spark_location"],
            step["spark_location_mm"],
            step["voltage"],
            step["current"],
            step["current_squared"],
            0.2,
            1,
            6,
            0,
            7,
            0.25,
            0.015,
            320.0,
            1.3e-4,
            -175.0,
        )

        np.testing.assert_allclose(
            actual_temperature,
            expected_temperature,
            rtol=1e-6,
            atol=1e-6,
        )
        np.testing.assert_allclose(
            actual_damage,
            expected_damage,
            rtol=1e-6,
            atol=1e-6,
        )
        np.testing.assert_allclose(actual_position_offset, expected_position_offset)
        np.testing.assert_allclose(actual_max_damage, expected_max_damage)
