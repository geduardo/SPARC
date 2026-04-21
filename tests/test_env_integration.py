"""Integration tests for Wire EDM Environment."""

import pytest
import numpy as np
from wedm import (
    WireEDMEnv,
    EnvironmentConfig,
    IgnitionModuleParameters,
    MaterialModuleParameters,
    WireModuleParameters,
)
from wedm.core.state import EDMState
from wedm.envs.wire_edm import ScalarAction, build_scalar_action


def _valid_action(env):
    """Sample an action constrained to modes with crater data."""
    action = env.action_space.sample()
    modes = sorted(int(m[1:]) for m in env.valid_current_modes)
    action["generator_control"]["current_mode"][0] = np.random.choice(modes)
    return action


class TestWireEDMEnv:
    """Test Wire EDM Environment basic functionality."""

    def test_env_creation(self):
        """Test environment can be created with default config."""
        env = WireEDMEnv()
        assert env is not None
        assert env.config is not None

    def test_env_reset(self):
        """Test environment reset."""
        env = WireEDMEnv()
        obs, info = env.reset()

        assert obs is not None
        assert isinstance(info, dict)
        assert env.state.time == 0
        assert env.state.workpiece_position == env.config.initial_gap

    def test_edm_state_defaults_use_scalar_electrical_values(self):
        """Fresh state objects should start with non-optional electrical scalars."""
        state = EDMState()

        assert state.voltage == 0.0
        assert state.current == 0.0
        assert state.ignition_random_short_remaining_us == 0
        assert state.ignition_debris_short_remaining_us == 0
        assert state.mechanics_prev_accel == 0.0
        assert state.dielectric_last_gap_um == -1.0
        assert state.dielectric_last_debris_density == -1.0
        assert state.wire_last_flow_condition is None
        assert state.wire_zone_mean_counter == 0

    def test_env_reset_applies_explicit_episode_defaults(self):
        """Reset should populate generator, electrical, and thermal defaults."""
        env = WireEDMEnv()
        env.reset()

        assert env.state.workpiece_position == env.config.initial_gap
        assert env.state.target_position == env.config.target_cutting_distance
        assert env.state.spark_status == [0, None, 0]

        assert env.state.target_voltage == env.ignition.params.default_target_voltage
        assert env.state.current_mode == env.ignition.params.default_current_mode
        assert env.state.ON_time == env.ignition.params.default_on_time
        assert env.state.OFF_time == env.ignition.params.default_off_time

        assert env.state.voltage == env.ignition.params.default_target_voltage
        assert env.state.current == 0.0
        assert (
            env.state.dielectric_temperature
            == env.dielectric.params.dielectric_temperature
        )

    def test_env_reset_clears_module_internal_state(self):
        """Reset should clear module-owned episode state, not just EDMState."""
        env = WireEDMEnv()
        env.reset()

        env.ignition.random_short_remaining = 17
        env.ignition.debris_short_remaining = 23
        env.ignition._cached_current_mode = "I7"

        env.material._cached_current_mode = "I9"
        env.material._cached_crater_info = env.material.crater_data["I9"]
        env.material.crater_volumes_um3 = [1.0, 2.0]

        env.dielectric.debris_volume = 3.5
        env.dielectric.debris_density = 0.7
        env.dielectric.cavity_volume = 5.0
        env.dielectric.flow_condition = 0.2
        env.dielectric.ion_channel = (1.0, 4)

        env.mechanics.prev_accel = 42.0

        env.wire._temperature.fill(500.0)
        env.wire._damage.fill(0.5)
        env.wire._y_start_mm += 1.0
        env.wire._last_flow_condition = 0.5
        env.wire.zone_mean_counter = 9

        env.reset()

        assert env.ignition.random_short_remaining == 0
        assert env.ignition.debris_short_remaining == 0
        assert env.ignition._cached_current_mode is None
        assert env.state.ignition_random_short_remaining_us == 0
        assert env.state.ignition_debris_short_remaining_us == 0

        assert env.material._cached_current_mode is None
        assert (
            env.material._cached_crater_info
            == env.material.crater_data[env.default_current_mode]
        )
        assert env.material.crater_volumes_um3 == []

        assert env.dielectric.debris_volume == 0.0
        assert env.dielectric.debris_density == 0.0
        assert env.dielectric.cavity_volume == 0.0
        assert env.dielectric.flow_condition == 0.0
        assert env.dielectric.ion_channel is None
        assert env.state.dielectric_last_gap_um == -1.0
        assert env.state.dielectric_last_debris_density == -1.0

        assert env.mechanics.prev_accel == 0.0
        assert env.state.mechanics_prev_accel == 0.0

        expected_positions = np.arange(
            env.wire.n_segments, dtype=np.float32
        ) * np.float32(env.wire.segment_len_mm)
        np.testing.assert_allclose(env.wire._y_start_mm, expected_positions)
        np.testing.assert_allclose(
            env.wire._temperature,
            np.full(env.wire.n_segments, env.wire.params.spool_T, dtype=np.float32),
        )
        np.testing.assert_allclose(
            env.wire._damage, np.zeros(env.wire.n_segments, dtype=np.float32)
        )
        np.testing.assert_allclose(env.state.wire_temperature, env.wire._temperature)
        np.testing.assert_allclose(env.state.wire_damage, env.wire._damage)
        assert env.state.wire_max_damage == 0.0
        assert env.state.wire_offset_mm == pytest.approx(0.0)
        assert env.state.wire_zone_mean_counter == 0

    def test_markov_runtime_state_is_canonical_in_edm_state(self):
        """Module runtime memory should round-trip through EDMState, not hidden fields."""
        env = WireEDMEnv()
        env.reset()

        env.ignition.random_short_remaining = 17
        env.ignition.debris_short_remaining = 23
        env.mechanics.prev_accel = 42.0
        env.dielectric._last_gap_um = 12.5
        env.dielectric._last_debris_density = 0.33
        env.wire._position_offset_mm = 0.075
        env.wire._last_flow_condition = 0.4
        env.wire.zone_mean_counter = 9

        assert env.state.ignition_random_short_remaining_us == 17
        assert env.state.ignition_debris_short_remaining_us == 23
        assert env.state.mechanics_prev_accel == pytest.approx(42.0)
        assert env.state.dielectric_last_gap_um == pytest.approx(12.5)
        assert env.state.dielectric_last_debris_density == pytest.approx(0.33)
        assert env.state.wire_offset_mm == pytest.approx(0.075)
        assert env.state.wire_last_flow_condition == pytest.approx(0.4)
        assert env.state.wire_zone_mean_counter == 9

    def test_material_analysis_tracking_is_opt_in_and_reset_safe(self):
        """Crater-history tracking should be explicit and reset cleanly."""
        env_default = WireEDMEnv()
        env_default.reset()

        env_default.material._sample_crater_volume(env_default.state)

        assert env_default.material.crater_volumes_um3 == []
        assert env_default.material.get_crater_statistics()["tracking_enabled"] is False

        env_tracked = WireEDMEnv(
            material_params=MaterialModuleParameters(enable_analysis_tracking=True)
        )
        env_tracked.reset()

        env_tracked.material._sample_crater_volume(env_tracked.state)
        env_tracked.material._sample_crater_volume(env_tracked.state)

        stats_before_reset = env_tracked.material.get_crater_statistics()
        assert stats_before_reset["tracking_enabled"] is True
        assert stats_before_reset["total_craters"] == 2
        assert len(env_tracked.material.crater_volumes_um3) == 2

        env_tracked.reset()

        stats_after_reset = env_tracked.material.get_crater_statistics()
        assert env_tracked.material.crater_volumes_um3 == []
        assert stats_after_reset["tracking_enabled"] is True
        assert stats_after_reset["total_craters"] == 0

    def test_wire_segments_snapshot_reflects_internal_arrays(self):
        """Compatibility segment views should be materialized from the live arrays."""
        env = WireEDMEnv()
        env.reset()

        env.wire._y_start_mm[0] = np.float32(1.25)
        env.wire._temperature[0] = np.float32(410.0)
        env.wire._damage[0] = np.float32(0.35)

        first_segment = env.wire.segments[0]

        assert first_segment.y_start_mm == pytest.approx(1.25)
        assert first_segment.temperature == pytest.approx(410.0)
        assert first_segment.damage == pytest.approx(0.35)

    def test_wire_segments_snapshot_is_not_a_live_mutation_surface(self):
        """Editing a compatibility snapshot should not mutate the live simulation arrays."""
        env = WireEDMEnv()
        env.reset()

        first_segment = env.wire.segments[0]
        first_segment.y_start_mm = -99.0
        first_segment.temperature = -1.0
        first_segment.damage = 1.0

        assert env.wire._y_start_mm[0] == pytest.approx(0.0)
        assert env.wire._temperature[0] == pytest.approx(env.wire.params.spool_T)
        assert env.wire._damage[0] == pytest.approx(0.0)

    def test_wire_transport_rollover_uses_offset_and_rolls_fresh_segments(self):
        """Wire transport should advance positions via offset and preserve roll-in semantics."""
        env = WireEDMEnv()
        env.reset()

        env.wire._temperature[:] = np.arange(env.wire.n_segments, dtype=np.float32) + 100.0
        env.wire._damage[:] = np.arange(env.wire.n_segments, dtype=np.float32) / 10.0

        remainder_mm = 0.05
        delta_mm = env.wire._position_wrap_threshold_mm + remainder_mm
        wire_unwind_vel = delta_mm * 1e3 / env.config.dt

        env.wire._advance_transport(wire_unwind_vel)

        expected_positions = np.arange(
            env.wire.n_segments, dtype=np.float32
        ) * np.float32(env.wire.segment_len_mm) + np.float32(remainder_mm)

        assert env.wire._position_offset_mm == pytest.approx(remainder_mm)
        np.testing.assert_allclose(
            env.wire._ensure_position_buffer(),
            expected_positions,
        )
        assert env.wire._temperature[0] == pytest.approx(env.wire.params.spool_T)
        np.testing.assert_allclose(
            env.wire._temperature[1:],
            np.arange(env.wire.n_segments - 1, dtype=np.float32) + 100.0,
        )
        assert env.wire._damage[0] == pytest.approx(0.0)
        np.testing.assert_allclose(
            env.wire._damage[1:],
            np.arange(env.wire.n_segments - 1, dtype=np.float32) / 10.0,
        )

    def test_wire_state_views_alias_live_buffers(self):
        """State wire arrays should point at the live wire buffers, not per-step copies."""
        env = WireEDMEnv()
        env.reset()

        assert env.state.wire_temperature is env.wire._temperature
        assert env.state.wire_damage is env.wire._damage
        assert env.state.wire_material_positions_mm is env.wire._y_start_mm

        env.state.wire_unwinding_velocity = 250.0
        env.wire.update(env.state)

        assert env.state.wire_temperature is env.wire._temperature
        assert env.state.wire_damage is env.wire._damage
        assert env.state.wire_material_positions_mm is env.wire._y_start_mm

    def test_module_reset_hooks_sync_dirty_existing_state(self):
        """Module reset hooks should clean mirrored state, not just private caches."""
        env = WireEDMEnv()
        env.reset()

        env.state.current = 99.0
        env.state.is_short_circuit = True
        env.state.spark_status = [-1, 12.0, 4]

        env.state.last_crater_volume = 0.5

        env.state.dielectric_temperature = 999.0
        env.state.debris_volume = 3.5
        env.state.debris_density = 0.7
        env.state.cavity_volume = 5.0
        env.state.flow_rate = 0.2
        env.state.debris_concentration = 0.7
        env.state.dielectric_flow_rate = 1.3
        env.state.ionized_channel = (1.0, 4)

        env.state.target_delta = 17.0
        env.state.wire_velocity = 42.0

        env.state.is_wire_broken = True

        env.ignition.reset(env.state)
        env.material.reset(env.state)
        env.dielectric.reset(env.state)
        env.mechanics.reset(env.state)
        env.wire.reset(env.state)

        assert env.state.current == 0.0
        assert env.state.is_short_circuit is False
        assert env.state.spark_status == [0, None, 0]
        assert env.state.last_crater_volume == 0.0

        assert (
            env.state.dielectric_temperature
            == env.dielectric.params.dielectric_temperature
        )
        assert env.state.debris_volume == 0.0
        assert env.state.debris_density == 0.0
        assert env.state.cavity_volume == 0.0
        assert env.state.flow_rate == 0.0
        assert env.state.debris_concentration == 0.0
        assert env.state.dielectric_flow_rate == 0.0
        assert env.state.ionized_channel is None

        assert env.state.target_delta == 0.0
        assert env.state.wire_velocity == 0.0
        assert env.state.is_wire_broken is False

    def test_env_step(self):
        """Test environment step with valid action."""
        env = WireEDMEnv()
        env.reset()
        initial_time = env.state.time

        action = _valid_action(env)
        obs, reward, terminated, truncated, info = env.step(action)
        assert env.state.time > initial_time

        assert isinstance(reward, (int, float))
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_env_step_respects_overridden_step_hooks(self):
        """Subclass overrides should be honored by the public step API."""

        class HookedEnv(WireEDMEnv):
            def __init__(self):
                super().__init__()
                self.apply_called = False
                self.check_called = False
                self.obs_called = False
                self.reward_called = False

            def _apply_action(self, action):
                self.apply_called = True
                return super()._apply_action(action)

            def _check_termination(self) -> bool:
                self.check_called = True
                return super()._check_termination()

            def _get_obs(self):
                self.obs_called = True
                return {"hooked": True}

            def _calc_reward(self):
                self.reward_called = True
                return 7.0

        env = HookedEnv()
        env.reset()
        env.state.time_since_servo = env.servo_interval

        action = _valid_action(env)
        obs, reward, terminated, truncated, info = env.step(action)

        assert env.apply_called is True
        assert env.check_called is True
        assert env.obs_called is True
        assert env.reward_called is True
        assert obs == {"hooked": True}
        assert reward == 7.0
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_env_step_accepts_scalar_action_fast_path(self):
        """The env should accept normalized scalar actions without changing behavior."""
        env = WireEDMEnv()
        env.reset()
        env.state.time_since_servo = env.servo_interval

        action = build_scalar_action(
            servo=0.25,
            target_voltage=90.0,
            current_mode=1,
            ON_time=3.0,
            OFF_time=20.0,
        )
        assert isinstance(action, ScalarAction)

        obs, reward, terminated, truncated, info = env.step(action)

        assert env.state.target_delta == pytest.approx(0.25)
        assert env.state.target_voltage == pytest.approx(90.0)
        assert env.state.current_mode == "I1"
        assert env.state.ON_time == pytest.approx(3.0)
        assert env.state.OFF_time == pytest.approx(20.0)
        assert isinstance(reward, (int, float))
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_custom_config(self):
        """Test environment with custom configuration."""
        config = EnvironmentConfig(
            workpiece_height=20.0, wire_diameter=0.3, target_cutting_distance=1000.0
        )

        env = WireEDMEnv(config=config)
        assert env.config.workpiece_height == 20.0
        assert env.config.wire_diameter == 0.3
        assert env.config.target_cutting_distance == 1000.0

    def test_invalid_wire_segment_length_is_rejected(self):
        """Wire transport parameters should fail fast on invalid segment geometry."""
        with pytest.raises(ValueError, match="segment_len must be positive"):
            WireEDMEnv(wire_params=WireModuleParameters(segment_len=0.0))

    def test_control_modes(self):
        """Test different control modes."""
        # Position control
        env_pos = WireEDMEnv(mechanics_control_mode="position")
        assert env_pos.mechanics_control_mode == "position"

        # Velocity control
        env_vel = WireEDMEnv(mechanics_control_mode="velocity")
        assert env_vel.mechanics_control_mode == "velocity"

        # Invalid mode
        with pytest.raises(ValueError):
            WireEDMEnv(mechanics_control_mode="invalid")

    def test_invalid_default_current_mode_rejected(self):
        """Default startup current mode must be backed by crater data."""
        with pytest.raises(ValueError, match="default_current_mode"):
            WireEDMEnv(
                ignition_params=IgnitionModuleParameters(default_current_mode="I2")
            )

    def test_ignition_generator_fallbacks_distinguish_none_from_zero(self):
        """None should fall back to defaults, while explicit zeroes stay zero."""
        env = WireEDMEnv()
        env.reset()

        env.state.target_voltage = None
        env.state.ON_time = None
        env.state.OFF_time = None
        assert (
            env.ignition._get_target_voltage(env.state)
            == env.ignition.params.default_target_voltage
        )
        assert (
            env.ignition._get_on_time(env.state) == env.ignition.params.default_on_time
        )
        assert (
            env.ignition._get_off_time(env.state)
            == env.ignition.params.default_off_time
        )

        env.state.target_voltage = 0.0
        env.state.ON_time = 0.0
        env.state.OFF_time = 0.0
        assert env.ignition._get_target_voltage(env.state) == 0.0
        assert env.ignition._get_on_time(env.state) == 0.0
        assert env.ignition._get_off_time(env.state) == 0.0

    def test_missing_current_mode_uses_shared_default_discharge_mode(self):
        """Ignition and crater sampling should share the same fallback mode."""
        env = WireEDMEnv(
            ignition_params=IgnitionModuleParameters(default_current_mode="I17")
        )
        env.reset()
        env.state.current_mode = None

        assert (
            env.ignition._get_peak_current(env.state)
            == env.ignition.currents_data["I17"]["Current"]
        )

        env.material._sample_crater_volume(env.state)

        assert env.material._cached_current_mode == "I17"
        assert env.material._cached_crater_info == env.material.crater_data["I17"]

    def test_unsupported_current_mode_falls_back_to_shared_default(self):
        """Module internals should stay aligned if state.current_mode is unsupported."""
        env = WireEDMEnv(
            ignition_params=IgnitionModuleParameters(default_current_mode="I17")
        )
        env.reset()
        env.state.current_mode = "I2"

        assert (
            env.ignition._get_peak_current(env.state)
            == env.ignition.currents_data["I17"]["Current"]
        )

        env.material._sample_crater_volume(env.state)

        assert env.material._cached_current_mode == "I17"
        assert env.material._cached_crater_info == env.material.crater_data["I17"]

    def test_ignition_generator_settings_cache_uses_mode_lut_and_refreshes(self):
        """Ignition should resolve control settings once and reuse crater-backed current LUTs."""
        env = WireEDMEnv(
            ignition_params=IgnitionModuleParameters(default_current_mode="I17")
        )
        env.reset()

        env.state.target_voltage = None
        env.state.current_mode = None
        env.state.ON_time = None
        env.state.OFF_time = None

        default_settings = env.ignition._resolve_generator_settings(env.state)
        assert default_settings == (
            env.ignition.params.default_target_voltage,
            env.ignition.currents_data["I17"]["Current"],
            env.ignition.params.default_on_time,
            env.ignition.params.default_off_time,
        )
        assert env.ignition._cached_current_mode == "I17"

        valid_mode = sorted(env.valid_current_modes, key=lambda m: int(m[1:]))[0]
        env.state.target_voltage = 47.0
        env.state.current_mode = valid_mode
        env.state.ON_time = 2.5
        env.state.OFF_time = 17.0

        updated_settings = env.ignition._resolve_generator_settings(env.state)
        assert updated_settings == (
            47.0,
            env.ignition.currents_data[valid_mode]["Current"],
            2.5,
            17.0,
        )
        assert env.ignition._cached_current_mode == valid_mode


class TestCurrentModeValidation:
    """Tests that invalid current_mode values are rejected at action intake."""

    def test_valid_current_modes_exposed(self):
        """Env exposes valid_current_modes derived from crater data."""
        env = WireEDMEnv()
        assert isinstance(env.valid_current_modes, set)
        assert len(env.valid_current_modes) > 0
        # All entries should be I-mode strings
        for m in env.valid_current_modes:
            assert m.startswith("I")
            assert int(m[1:]) >= 1

    def test_valid_modes_accepted(self):
        """All modes with crater data are accepted without error."""
        env = WireEDMEnv()
        env.reset()
        for mode_str in env.valid_current_modes:
            mode_int = int(mode_str[1:])
            action = env.action_space.sample()
            action["generator_control"]["current_mode"][0] = mode_int
            # Should not raise
            env.step(action)

    def test_invalid_even_modes_rejected(self):
        """Even modes without crater data raise ValueError at action intake."""
        env = WireEDMEnv()
        env.reset()
        invalid_modes = [
            m for m in range(1, 20) if f"I{m}" not in env.valid_current_modes
        ]
        assert len(invalid_modes) > 0, "Test expects at least one invalid mode"
        for mode_int in invalid_modes:
            # Force a control step so _apply_action fires
            env.state.time_since_servo = env.servo_interval
            action = env.action_space.sample()
            action["generator_control"]["current_mode"][0] = mode_int
            with pytest.raises(ValueError, match=f"current_mode {mode_int}"):
                env.step(action)
            # Reset state so next iteration starts clean
            env.reset()

    def test_invalid_mode_error_lists_valid_options(self):
        """Error message includes the list of valid modes for agent parsers."""
        env = WireEDMEnv()
        env.reset()
        # Force a control step so _apply_action fires
        env.state.time_since_servo = env.servo_interval
        action = env.action_space.sample()
        action["generator_control"]["current_mode"][0] = 2  # Even → invalid
        with pytest.raises(ValueError, match="Valid modes:") as exc_info:
            env.step(action)
        # Check that at least some valid modes appear in the message
        msg = str(exc_info.value)
        assert "I1" in msg
        assert "I3" in msg
