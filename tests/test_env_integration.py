"""Integration tests for Wire EDM Environment."""

import pytest
import numpy as np
from wedm import WireEDMEnv, EnvironmentConfig, IgnitionModuleParameters


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
        assert env.state.dielectric_temperature == env.dielectric.params.dielectric_temperature

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

        assert env.material._cached_current_mode is None
        assert env.material._cached_crater_info == env.material.crater_data[env.default_current_mode]
        assert env.material.crater_volumes_um3 == []

        assert env.dielectric.debris_volume == 0.0
        assert env.dielectric.debris_density == 0.0
        assert env.dielectric.cavity_volume == 0.0
        assert env.dielectric.flow_condition == 0.0
        assert env.dielectric.ion_channel is None

        assert env.mechanics.prev_accel == 0.0

        expected_positions = (
            np.arange(env.wire.n_segments, dtype=np.float32)
            * np.float32(env.wire.segment_len_mm)
        )
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

        assert env.state.dielectric_temperature == env.dielectric.params.dielectric_temperature
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

    def test_custom_config(self):
        """Test environment with custom configuration."""
        config = EnvironmentConfig(
            workpiece_height=20.0, wire_diameter=0.3, target_cutting_distance=1000.0
        )

        env = WireEDMEnv(config=config)
        assert env.config.workpiece_height == 20.0
        assert env.config.wire_diameter == 0.3
        assert env.config.target_cutting_distance == 1000.0

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

    def test_missing_current_mode_uses_shared_default_discharge_mode(self):
        """Ignition and crater sampling should share the same fallback mode."""
        env = WireEDMEnv(
            ignition_params=IgnitionModuleParameters(default_current_mode="I17")
        )
        env.reset()
        env.state.current_mode = None

        assert env.ignition._get_peak_current(env.state) == env.ignition.currents_data["I17"]["Current"]

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

        assert env.ignition._get_peak_current(env.state) == env.ignition.currents_data["I17"]["Current"]

        env.material._sample_crater_volume(env.state)

        assert env.material._cached_current_mode == "I17"
        assert env.material._cached_crater_info == env.material.crater_data["I17"]


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
        invalid_modes = [m for m in range(1, 20) if f"I{m}" not in env.valid_current_modes]
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
