"""Integration tests for Wire EDM Environment."""

import pytest
import numpy as np
from wedm import WireEDMEnv, EnvironmentConfig


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
