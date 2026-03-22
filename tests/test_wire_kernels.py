"""Low-level regression tests for optimized wire kernels."""

import numpy as np

from wedm.modules.wire import (
    accumulate_damage,
    apply_thermal_core_inplace,
    apply_thermal_damage_core_inplace,
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
