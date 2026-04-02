"""Lockstep fidelity tests for the compiled scheduler.

Runs both the modular reference implementation and the compiled scheduler
with the same seed and action sequence, then asserts exact or near-exact
parity on all fidelity-critical state fields.
"""
from dataclasses import replace
import math

import numpy as np
import pytest

from wedm import IgnitionModuleParameters, WireEDMEnv
from wedm.envs.wire_edm import build_scalar_action
from wedm.core.hot_state import HotStateBundle
from wedm.core.compiled_step import (
    SchedulerConstants,
    _compiled_update_convection,
    compiled_microstep,
)


SEED = 42
N_STEPS = 500  # enough to exercise ignition, sparks, shorts, and material removal


def _make_action():
    """Fixed action matching the default generator settings."""
    return build_scalar_action(
        servo=0.0,
        target_voltage=80.0,
        current_mode=5,
        ON_time=3.0,
        OFF_time=20.0,
    )


def _run_modular(n_steps: int, seed: int, action=None):
    """Run the modular reference path, return final state snapshot."""
    env = WireEDMEnv()
    env.reset(seed=seed)
    env.state.time_since_servo = env.servo_interval
    action = action or _make_action()

    for _ in range(n_steps):
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated:
            break

    return env


def _run_modular_fast(n_steps: int, seed: int, action=None):
    """Run the modular flag-only stepping API and return the final state."""
    env = WireEDMEnv()
    env.reset(seed=seed)
    env.state.time_since_servo = env.servo_interval
    action = action or _make_action()

    for _ in range(n_steps):
        terminated, truncated = env.step_fast(action)
        if terminated or truncated:
            break

    return env


def _run_compiled(n_steps: int, seed: int, action=None):
    """Run the compiled stepping API and return the final state."""
    env = WireEDMEnv()
    env.reset(seed=seed)
    env.state.time_since_servo = env.servo_interval
    action = action or _make_action()

    env.init_compiled_scheduler()

    for _ in range(n_steps):
        obs, reward, terminated, truncated, info = env.step_compiled(action)
        if terminated:
            break

    # Sync back to modular state for comparison
    env.sync_compiled_to_state()
    return env


def _run_compiled_fast(n_steps: int, seed: int, action=None):
    """Run the compiled flag-only stepping API and return the final state."""
    env = WireEDMEnv()
    env.reset(seed=seed)
    env.state.time_since_servo = env.servo_interval
    action = action or _make_action()

    env.init_compiled_scheduler()

    for _ in range(n_steps):
        terminated, truncated = env.step_compiled_fast(action)
        if terminated or truncated:
            break

    env.sync_compiled_to_state()
    return env


class TestCompiledStepParity:
    """Lockstep parity between the reference and compiled schedulers."""

    @pytest.fixture(scope="class")
    def envs(self):
        """Run both paths once for the whole test class."""
        mod = _run_modular(N_STEPS, SEED)
        comp = _run_compiled(N_STEPS, SEED)
        return mod, comp

    def test_time_matches(self, envs):
        mod, comp = envs
        assert mod.state.time == comp.state.time

    def test_workpiece_position_tracks_cumulative_crater_effect(self, envs):
        """Workpiece position should remain aligned as the cumulative crater effect."""
        mod, comp = envs
        assert mod.state.workpiece_position == pytest.approx(
            comp.state.workpiece_position, abs=0.1  # 0.1 µm absolute
        )

    def test_wire_position(self, envs):
        mod, comp = envs
        assert mod.state.wire_position == pytest.approx(
            comp.state.wire_position, abs=0.01
        )

    def test_wire_velocity(self, envs):
        mod, comp = envs
        assert mod.state.wire_velocity == pytest.approx(
            comp.state.wire_velocity, abs=0.01
        )

    def test_voltage(self, envs):
        mod, comp = envs
        assert mod.state.voltage == pytest.approx(comp.state.voltage, abs=0.01)

    def test_current(self, envs):
        mod, comp = envs
        assert mod.state.current == pytest.approx(comp.state.current, abs=0.01)

    def test_spark_state(self, envs):
        mod, comp = envs
        assert mod.state.spark_status[0] == comp.state.spark_status[0]

    def test_spark_duration(self, envs):
        mod, comp = envs
        assert mod.state.spark_status[2] == comp.state.spark_status[2]

    def test_debris_volume(self, envs):
        mod, comp = envs
        assert mod.state.debris_volume == pytest.approx(
            comp.state.debris_volume, abs=1e-12
        )

    def test_debris_density(self, envs):
        mod, comp = envs
        assert mod.state.debris_density == pytest.approx(
            comp.state.debris_density, abs=1e-6
        )

    def test_debris_concentration(self, envs):
        mod, comp = envs
        assert mod.state.debris_concentration == pytest.approx(
            comp.state.debris_concentration, abs=1e-6
        )

    def test_dielectric_flow_rate(self, envs):
        mod, comp = envs
        assert mod.state.dielectric_flow_rate == pytest.approx(
            comp.state.dielectric_flow_rate, abs=1e-12
        )

    def test_wire_max_damage(self, envs):
        mod, comp = envs
        assert mod.state.wire_max_damage == pytest.approx(
            comp.state.wire_max_damage, abs=1e-4
        )

    def test_wire_temperature_mean(self, envs):
        mod, comp = envs
        mod_mean = float(np.mean(mod.state.wire_temperature))
        comp_mean = float(np.mean(comp.state.wire_temperature))
        assert mod_mean == pytest.approx(comp_mean, abs=0.5)

    def test_wire_temperature_array_close(self, envs):
        mod, comp = envs
        np.testing.assert_allclose(
            comp.state.wire_temperature,
            mod.state.wire_temperature,
            atol=0.5, rtol=0.0,
        )

    def test_is_short_circuit_matches(self, envs):
        mod, comp = envs
        assert mod.state.is_short_circuit == comp.state.is_short_circuit

    def test_is_wire_broken_matches(self, envs):
        mod, comp = envs
        assert mod.state.is_wire_broken == comp.state.is_wire_broken


class TestCompiledStepSingleStep:
    """Single-step lockstep comparison for debugging divergence."""

    def test_first_10_steps_identical(self):
        """Compare state after each of the first 10 steps."""
        env_mod = WireEDMEnv()
        env_mod.reset(seed=99)

        env_comp = WireEDMEnv()
        env_comp.reset(seed=99)
        env_comp.init_compiled_scheduler()

        action = _make_action()

        for step_i in range(10):
            env_mod.step(action)
            env_comp.step_compiled(action)
            env_comp.sync_compiled_to_state()

            ms = env_mod.state
            cs = env_comp.state

            assert ms.time == cs.time, f"Step {step_i}: time mismatch"
            assert ms.spark_status[0] == cs.spark_status[0], (
                f"Step {step_i}: spark_state mismatch "
                f"mod={ms.spark_status[0]} comp={cs.spark_status[0]}"
            )
            assert ms.voltage == pytest.approx(cs.voltage, abs=1e-9), (
                f"Step {step_i}: voltage mismatch"
            )
            assert ms.current == pytest.approx(cs.current, abs=1e-9), (
                f"Step {step_i}: current mismatch"
            )
            assert ms.workpiece_position == pytest.approx(
                cs.workpiece_position, abs=1e-12
            ), f"Step {step_i}: workpiece_position mismatch"
            assert ms.wire_position == pytest.approx(
                cs.wire_position, abs=1e-12
            ), f"Step {step_i}: wire_position mismatch"
            assert ms.is_short_circuit == cs.is_short_circuit, (
                f"Step {step_i}: is_short_circuit mismatch"
            )

    def test_nondefault_control_settings_sync_back_to_state(self):
        """Compiled control application must update the hot bundle state, not just caches."""
        action = build_scalar_action(
            servo=0.25,
            target_voltage=91.0,
            current_mode=17,
            ON_time=2.5,
            OFF_time=17.0,
        )

        env = WireEDMEnv()
        env.reset(seed=123)
        env.state.time_since_servo = env.servo_interval
        env.init_compiled_scheduler()

        env.step_compiled(action)
        env.sync_compiled_to_state()

        assert env.state.target_delta == pytest.approx(0.25)
        assert env.state.target_voltage == pytest.approx(91.0)
        assert env.state.current_mode == "I17"
        assert env.state.ON_time == pytest.approx(2.5)
        assert env.state.OFF_time == pytest.approx(17.0)

    def test_mode_change_keeps_material_geometry_in_lockstep(self):
        """Changing current mode must update crater geometry, not just crater volume stats."""
        action = build_scalar_action(
            servo=0.25,
            target_voltage=90.0,
            current_mode=17,
            ON_time=3.0,
            OFF_time=20.0,
        )

        mod = _run_modular(1000, 123, action)
        comp = _run_compiled(1000, 123, action)

        assert mod.state.current_mode == "I17"
        assert comp.state.current_mode == "I17"
        assert mod.state.workpiece_position == pytest.approx(
            comp.state.workpiece_position, abs=0.1
        )


class TestFastPathParity:
    """Fast-step helpers must preserve the public-step semantics."""

    def test_step_fast_matches_public_api(self):
        action = _make_action()

        full = _run_modular(250, 77, action)
        fast = _run_modular_fast(250, 77, action)

        assert full.state.time == fast.state.time
        assert full.state.current_mode == fast.state.current_mode
        assert full.state.workpiece_position == pytest.approx(
            fast.state.workpiece_position, abs=0.1
        )
        assert full.state.wire_position == pytest.approx(
            fast.state.wire_position, abs=0.01
        )
        assert full.state.wire_max_damage == pytest.approx(
            fast.state.wire_max_damage, abs=1e-4
        )

    def test_step_compiled_fast_matches_public_api(self):
        action = _make_action()

        full = _run_compiled(250, 77, action)
        fast = _run_compiled_fast(250, 77, action)

        assert full.state.time == fast.state.time
        assert full.state.current_mode == fast.state.current_mode
        assert full.state.workpiece_position == pytest.approx(
            fast.state.workpiece_position, abs=0.1
        )
        assert full.state.wire_position == pytest.approx(
            fast.state.wire_position, abs=0.01
        )
        assert full.state.wire_max_damage == pytest.approx(
            fast.state.wire_max_damage, abs=1e-4
        )

    def test_step_fast_reports_wire_break_contract(self):
        env = WireEDMEnv()
        env.reset(seed=11)
        env.state.is_wire_broken = True

        assert env.step_fast(_make_action()) == (True, False)

    def test_step_fast_reports_target_reached_contract(self):
        env = WireEDMEnv()
        env.reset(seed=11)
        env.state.time_since_servo = env.servo_interval
        env.state.workpiece_position = env.state.target_position

        assert env.step_fast(_make_action()) == (True, False)

    def test_step_compiled_fast_reports_wire_break_contract(self):
        env = WireEDMEnv()
        env.reset(seed=11)
        env.state.time_since_servo = env.servo_interval
        env.init_compiled_scheduler()
        env._hot_state.wire_damage[0] = 1.0

        assert env.step_compiled_fast(_make_action()) == (True, False)

    def test_step_compiled_fast_reports_target_reached_contract(self):
        env = WireEDMEnv()
        env.reset(seed=11)
        env.state.time_since_servo = env.servo_interval
        env.init_compiled_scheduler()
        env._hot_state.workpiece_position_um = env._hot_state.target_position

        assert env.step_compiled_fast(_make_action()) == (True, False)

    def test_step_compiled_uses_overridden_public_hooks(self):
        class HookedEnv(WireEDMEnv):
            def _get_obs(self):
                return {"hooked": True}

            def _calc_reward(self):
                return 7.0

        env = HookedEnv()
        env.reset(seed=11)
        env.state.time_since_servo = env.servo_interval
        env.init_compiled_scheduler()

        obs, reward, terminated, truncated, info = env.step_compiled(_make_action())

        assert obs == {"hooked": True}
        assert reward == 7.0
        assert isinstance(terminated, bool)
        assert truncated is False
        assert isinstance(info, dict)

    def test_precompiled_action_packet_matches_scalar_action_path(self):
        action = _make_action()

        scalar = WireEDMEnv()
        scalar.reset(seed=77)
        scalar.state.time_since_servo = scalar.servo_interval
        scalar.init_compiled_scheduler()

        packet_env = WireEDMEnv()
        packet_env.reset(seed=77)
        packet_env.state.time_since_servo = packet_env.servo_interval
        packet_env.init_compiled_scheduler()
        packet = packet_env.compile_action(action)

        for _ in range(250):
            scalar.step_compiled_fast(action)
            packet_env.step_compiled_fast(packet)

        scalar.sync_compiled_to_state()
        packet_env.sync_compiled_to_state()

        assert scalar.state.time == packet_env.state.time
        assert scalar.state.current_mode == packet_env.state.current_mode
        assert scalar.state.workpiece_position == pytest.approx(
            packet_env.state.workpiece_position, abs=0.1
        )
        assert scalar.state.wire_position == pytest.approx(
            packet_env.state.wire_position, abs=0.01
        )
        assert scalar.state.wire_max_damage == pytest.approx(
            packet_env.state.wire_max_damage, abs=1e-4
        )

    def test_precompiled_action_packet_skips_decode(self):
        env = WireEDMEnv()
        env.reset(seed=123)
        env.state.time_since_servo = env.servo_interval
        env.init_compiled_scheduler()

        packet = env.compile_action(_make_action())

        def fail_decode(_action):
            raise AssertionError("decode should not run for a compiled action packet")

        env._decode_action = fail_decode

        for _ in range(5):
            env._hot_state.time_since_servo = env._scheduler_constants.servo_interval
            terminated, truncated = env.step_compiled_fast(packet)
            assert (terminated, truncated) == (False, False)

    def test_compiled_mode_cache_skips_redundant_peak_current_resolution(self):
        env = WireEDMEnv()
        env.reset(seed=123)
        env.state.time_since_servo = env.servo_interval
        env.init_compiled_scheduler()

        calls = {"count": 0}
        original = env._update_compiled_mode_cache

        def counted(mode_int):
            if mode_int != env._compiled_cached_mode_int:
                calls["count"] += 1
            return original(mode_int)

        env._update_compiled_mode_cache = counted

        same_mode = _make_action()
        for _ in range(5):
            env._hot_state.time_since_servo = env._scheduler_constants.servo_interval
            env.step_compiled_fast(same_mode)

        changed_mode = build_scalar_action(
            servo=0.0,
            target_voltage=80.0,
            current_mode=17,
            ON_time=3.0,
            OFF_time=20.0,
        )
        env._hot_state.time_since_servo = env._scheduler_constants.servo_interval
        env.step_compiled_fast(changed_mode)
        env._hot_state.time_since_servo = env._scheduler_constants.servo_interval
        env.step_compiled_fast(changed_mode)

        assert calls["count"] == 1


class TrackingRNG:
    """Count scalar RNG draws while delegating to a deterministic Generator."""

    def __init__(self, seed: int):
        self._rng = np.random.default_rng(seed)
        self.random_calls = 0
        self.normal_calls = 0

    def random(self, size=None):
        if size is None:
            self.random_calls += 1
        else:
            self.random_calls += int(np.prod(size))
        return self._rng.random(size)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if size is None:
            self.normal_calls += 1
        else:
            self.normal_calls += int(np.prod(size))
        return self._rng.normal(loc, scale, size)


class SequenceRNG:
    """Return predetermined scalar RNG values."""

    def __init__(self, random_values, normal_values):
        self._random_values = list(random_values)
        self._normal_values = list(normal_values)

    def random(self, size=None):
        if size is not None:
            raise AssertionError("SequenceRNG only supports scalar draws")
        if not self._random_values:
            raise AssertionError("No random() values left in SequenceRNG")
        return self._random_values.pop(0)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if size is not None:
            raise AssertionError("SequenceRNG only supports scalar draws")
        if not self._normal_values:
            raise AssertionError("No normal() values left in SequenceRNG")
        return self._normal_values.pop(0)


class TestCompiledStepRNGParity:
    """Compiled staging must preserve the modular RNG branch pattern."""

    def test_compiled_path_consumes_same_rng_draw_pattern(self):
        action = build_scalar_action(
            servo=0.25,
            target_voltage=90.0,
            current_mode=17,
            ON_time=2.5,
            OFF_time=17.0,
        )

        modular = WireEDMEnv()
        modular.reset(seed=321)
        modular.state.time_since_servo = modular.servo_interval
        modular_rng = TrackingRNG(999)
        modular.np_random = modular_rng

        compiled = WireEDMEnv()
        compiled.reset(seed=321)
        compiled.state.time_since_servo = compiled.servo_interval
        compiled_rng = TrackingRNG(999)
        compiled.np_random = compiled_rng
        compiled.init_compiled_scheduler()

        for _ in range(1000):
            _, _, mod_terminated, mod_truncated, _ = modular.step(action)
            _, _, comp_terminated, comp_truncated, _ = compiled.step_compiled(action)
            if mod_terminated or mod_truncated or comp_terminated or comp_truncated:
                break

        compiled.sync_compiled_to_state()

        assert modular_rng.random_calls == compiled_rng.random_calls
        assert modular_rng.normal_calls == compiled_rng.normal_calls
        assert modular.state.workpiece_position == pytest.approx(
            compiled.state.workpiece_position, abs=0.1
        )
        assert modular.state.wire_max_damage == pytest.approx(
            compiled.state.wire_max_damage, abs=1e-4
        )

    def test_random_short_disabled_preserves_rng_draw_pattern(self):
        params = IgnitionModuleParameters(random_short_max_probability=0.0)
        action = _make_action()

        modular = WireEDMEnv(ignition_params=params)
        modular.reset(seed=321)
        modular.state.time_since_servo = modular.servo_interval
        modular_rng = TrackingRNG(999)
        modular.np_random = modular_rng

        compiled = WireEDMEnv(ignition_params=params)
        compiled.reset(seed=321)
        compiled.state.time_since_servo = compiled.servo_interval
        compiled_rng = TrackingRNG(999)
        compiled.np_random = compiled_rng
        compiled.init_compiled_scheduler()

        for _ in range(1000):
            _, _, mod_terminated, mod_truncated, _ = modular.step(action)
            _, _, comp_terminated, comp_truncated, _ = compiled.step_compiled(action)
            if mod_terminated or mod_truncated or comp_terminated or comp_truncated:
                break

        compiled.sync_compiled_to_state()

        assert modular_rng.random_calls == compiled_rng.random_calls
        assert modular_rng.normal_calls == compiled_rng.normal_calls
        assert modular.state.workpiece_position == pytest.approx(
            compiled.state.workpiece_position, abs=0.1
        )
        assert modular.state.wire_max_damage == pytest.approx(
            compiled.state.wire_max_damage, abs=1e-4
        )


class TestCompiledStepHelpers:
    """Direct helper parity and edge-case coverage."""

    def test_compiled_convection_matches_modular_update(self):
        env = WireEDMEnv()
        env.reset(seed=7)

        wire = env.wire
        wire._update_convection_coefficients(250.0, 0.35)
        expected = wire.conv_loss_coeff.copy()
        actual = np.zeros_like(expected)

        _compiled_update_convection(
            actual,
            250.0,
            0.35,
            wire.params.convection_velocity_factor,
            wire.params.base_convection_coefficient,
            wire.params.convection_flow_enhancement,
            wire.actual_zone_start,
            wire.actual_zone_end,
            wire.A,
        )

        np.testing.assert_allclose(actual, expected, atol=0.0, rtol=0.0)

    @pytest.mark.parametrize(
        ("kerf_width_mm", "workpiece_height_for_material"),
        [
            (0.0, 20.0),
            (0.2, 0.0),
        ],
    )
    def test_compiled_microstep_skips_material_increment_for_zero_geometry(
        self,
        kerf_width_mm,
        workpiece_height_for_material,
    ):
        env = WireEDMEnv()
        env.reset(seed=5)
        env.state.time_since_servo = env.servo_interval
        env.init_compiled_scheduler()

        hot_state = HotStateBundle.from_env(env)
        constants = replace(
            env._scheduler_constants,
            workpiece_height_for_material=workpiece_height_for_material,
        )
        rng = SequenceRNG(
            random_values=[1.0, 1.0, 0.0, 0.0],
            normal_values=[1000.0],
        )

        start_position = hot_state.workpiece_position_um
        termination_code = compiled_microstep(
            hot_state,
            rng,
            constants,
            env._compiled_target_voltage,
            env._compiled_peak_current,
            env._compiled_on_time,
            env._compiled_off_time,
            1000.0,
            0.0,
            kerf_width_mm,
        )

        assert termination_code == 0
        assert hot_state.workpiece_position_um == pytest.approx(start_position)


class TestSchedulerConstants:
    """Test SchedulerConstants construction."""

    def test_from_env_does_not_raise(self):
        env = WireEDMEnv()
        env.reset(seed=1)
        sc = SchedulerConstants.from_env(env)
        assert sc.dt_int == 1
        assert sc.workpiece_height > 0
        assert sc.segment_len_mm > 0

    def test_as_tuple_length(self):
        env = WireEDMEnv()
        env.reset(seed=1)
        sc = SchedulerConstants.from_env(env)
        t = sc.as_tuple()
        # Should have exactly as many fields as the dataclass
        import dataclasses
        n_fields = len(dataclasses.fields(SchedulerConstants))
        assert len(t) == n_fields
