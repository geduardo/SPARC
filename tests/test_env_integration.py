"""Integration tests for Wire EDM Environment."""

import pytest
import numpy as np
from wedm import WireEDMEnv, EnvironmentConfig


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
        """Test environment step with random action."""
        env = WireEDMEnv()
        env.reset()

        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)

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
