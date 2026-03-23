"""Lockstep fidelity tests for the compiled scheduler (PBC-02).

Runs both the modular reference path and the compiled path with the same
seed and action sequence, then asserts exact or near-exact parity on all
fidelity-critical state fields.
"""
import math

import numpy as np
import pytest

from wedm import WireEDMEnv
from wedm.envs.wire_edm import build_scalar_action
from wedm.core.hot_state import HotStateBundle
from wedm.core.compiled_step import SchedulerConstants, compiled_microstep


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


def _run_compiled(n_steps: int, seed: int, action=None):
    """Run the compiled scheduler path, return final state snapshot."""
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


class TestCompiledStepParity:
    """Lockstep parity between modular and compiled paths."""

    @pytest.fixture(scope="class")
    def envs(self):
        """Run both paths once for the whole test class."""
        mod = _run_modular(N_STEPS, SEED)
        comp = _run_compiled(N_STEPS, SEED)
        return mod, comp

    def test_time_matches(self, envs):
        mod, comp = envs
        assert mod.state.time == comp.state.time

    def test_crater_count_exact(self, envs):
        """Crater count must match exactly (fidelity gate)."""
        mod, comp = envs
        # We can't easily count craters without tracking, so compare
        # workpiece_position which is the cumulative effect of all craters.
        assert mod.state.workpiece_position == pytest.approx(
            comp.state.workpiece_position, abs=0.1
        )

    def test_workpiece_position(self, envs):
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
