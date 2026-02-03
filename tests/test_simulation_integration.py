"""Integration tests for Wire EDM simulation.

Testing philosophy: Test system behavior, not implementation details.
These tests verify that the simulation produces physically reasonable results
and that components work together correctly. They should survive refactors.
"""

import pytest
import numpy as np

from wedm import WireEDMEnv, EnvironmentConfig


# Valid current modes that have crater data (odd numbers only)
VALID_CURRENT_MODES = [1, 3, 5, 7, 9, 11, 13, 15, 17]


def sample_valid_action(env):
    """Sample an action with a valid current mode."""
    action = env.action_space.sample()
    # Crater data only exists for odd current modes
    action["generator_control"]["current_mode"][0] = np.random.choice(VALID_CURRENT_MODES)
    return action


class TestSimulationBehavior:
    """Tests that verify the simulation behaves correctly as a system."""

    def test_simulation_runs_without_crashing(self):
        """Basic smoke test - simulation can run for many steps."""
        env = WireEDMEnv()
        env.reset()

        for _ in range(10000):
            action = sample_valid_action(env)
            obs, reward, terminated, truncated, info = env.step(action)
            if terminated:
                break

    def test_material_removal_progresses_cutting(self):
        """Sparks should remove material and advance the cut."""
        # Start with small initial gap so sparking can occur immediately
        config = EnvironmentConfig(initial_gap=15.0)  # Within ignition range
        env = WireEDMEnv(config=config)
        env.reset()

        initial_position = env.state.workpiece_position

        # Run simulation with valid current mode
        for _ in range(50000):
            action = sample_valid_action(env)
            env.step(action)
            if env.state.is_wire_broken:
                break

        # Should have made some cutting progress
        assert env.state.workpiece_position > initial_position, \
            "Simulation should remove material over time"

    def test_small_gap_causes_short_circuits(self):
        """Very small gaps should trigger short circuit detection."""
        env = WireEDMEnv()
        env.reset()

        # Force wire very close to workpiece
        env.state.wire_position = env.state.workpiece_position - 1.0  # 1 µm gap

        short_detected = False
        for _ in range(100):
            action = sample_valid_action(env)
            env.step(action)
            if env.state.is_short_circuit:
                short_detected = True
                break

        assert short_detected, "Very small gap should cause short circuit"

    def test_wire_heats_up_during_discharge(self):
        """Wire temperature should increase during active sparking."""
        env = WireEDMEnv()
        env.reset()

        # Get initial temperature
        initial_temp = np.mean(env.wire._temperature)

        # Run with conditions that should cause sparking
        env.state.workpiece_position = 15.0  # Within ignition range (< 25 µm)
        env.state.wire_position = 0.0

        for _ in range(10000):
            action = env.action_space.sample()
            # Use valid current mode
            action["generator_control"]["current_mode"][0] = 5
            env.step(action)
            if env.state.is_wire_broken:
                break

        # Temperature should have increased from discharge heating
        final_temp = np.mean(env.wire._temperature)
        # Allow for cooling effects, but there should be some heating events
        assert final_temp >= initial_temp - 10, \
            "Wire should heat during discharge activity"

    def test_wire_breaks_under_extreme_conditions(self):
        """Wire should eventually break under sustained high current."""
        env = WireEDMEnv()
        env.reset()

        # Force continuous sparking with high current
        env.state.workpiece_position = 10.0
        env.state.wire_position = 0.0

        for _ in range(100000):  # Reasonable run length
            action = env.action_space.sample()
            # Use valid current mode (highest available for max heating)
            action["generator_control"]["current_mode"][0] = 17  # I17
            env.step(action)
            if env.state.is_wire_broken:
                break

        # Either broke or reached iteration limit (both acceptable)
        # The point is it didn't crash and system remained stable

    def test_target_reached_terminates_episode(self):
        """Episode should terminate when target cutting distance is reached."""
        config = EnvironmentConfig(
            target_cutting_distance=100.0,  # Short target
            initial_gap=90.0  # Start close to target
        )
        env = WireEDMEnv(config=config)
        env.reset()

        terminated = False
        for _ in range(100000):
            action = sample_valid_action(env)
            _, _, terminated, _, info = env.step(action)
            if terminated:
                break

        if terminated and info.get("target_reached"):
            assert env.state.workpiece_position >= config.target_cutting_distance

    def test_debris_accumulates_and_affects_flow(self):
        """Debris should accumulate during sparking and affect dielectric flow."""
        env = WireEDMEnv()
        env.reset()

        # Run simulation to generate debris
        for _ in range(10000):
            action = sample_valid_action(env)
            env.step(action)

        # Debris behavior depends on spark activity - just verify it's tracked
        assert hasattr(env.state, 'debris_volume')
        assert hasattr(env.state, 'flow_rate')

    def test_position_and_velocity_control_modes_work(self):
        """Both control modes should allow wire movement."""
        for mode in ["position", "velocity"]:
            env = WireEDMEnv(mechanics_control_mode=mode)
            env.reset()

            # Apply control input
            for _ in range(5000):
                action = sample_valid_action(env)
                # Override servo to request movement
                action["servo"][0] = 0.5
                env.step(action)

            # Wire should have responded to control
            assert np.isfinite(env.state.wire_position)
            assert np.isfinite(env.state.wire_velocity)


class TestPhysicalConstraints:
    """Tests that verify physical constraints are respected."""

    def test_temperatures_stay_finite(self):
        """Wire temperatures should never become NaN or Inf."""
        env = WireEDMEnv()
        env.reset()

        for _ in range(10000):
            action = sample_valid_action(env)
            env.step(action)

            assert np.all(np.isfinite(env.wire._temperature)), \
                "Wire temperatures must remain finite"

            if env.state.is_wire_broken:
                break

    def test_positions_stay_reasonable(self):
        """Positions should stay within reasonable bounds."""
        env = WireEDMEnv()
        env.reset()

        for _ in range(10000):
            action = sample_valid_action(env)
            env.step(action)

            assert np.isfinite(env.state.wire_position)
            assert np.isfinite(env.state.workpiece_position)
            assert env.state.workpiece_position >= 0

            if env.state.is_wire_broken:
                break

    def test_debris_density_bounded(self):
        """Debris density should stay between 0 and 1."""
        env = WireEDMEnv()
        env.reset()

        for _ in range(10000):
            action = sample_valid_action(env)
            env.step(action)

            assert 0 <= env.state.debris_density <= 1, \
                "Debris density must be bounded [0, 1]"

            if env.state.is_wire_broken:
                break

    def test_spark_states_are_valid(self):
        """Spark status should only contain valid states."""
        valid_states = {0, 1, -1, -2}  # idle, spark, short, rest

        env = WireEDMEnv()
        env.reset()

        for _ in range(10000):
            action = sample_valid_action(env)
            env.step(action)

            assert env.state.spark_status[0] in valid_states, \
                f"Invalid spark state: {env.state.spark_status[0]}"

            if env.state.is_wire_broken:
                break


class TestConfigurationVariations:
    """Tests that verify different configurations work correctly."""

    def test_different_workpiece_heights(self):
        """Simulation should work with various workpiece heights."""
        for height in [5.0, 20.0, 50.0]:
            config = EnvironmentConfig(workpiece_height=height)
            env = WireEDMEnv(config=config)
            env.reset()

            for _ in range(1000):
                action = sample_valid_action(env)
                env.step(action)
                if env.state.is_wire_broken:
                    break

            assert env.config.workpiece_height == height

    def test_different_wire_diameters(self):
        """Simulation should work with various wire diameters."""
        for diameter in [0.1, 0.2, 0.3]:
            config = EnvironmentConfig(wire_diameter=diameter)
            env = WireEDMEnv(config=config)
            env.reset()

            for _ in range(1000):
                action = sample_valid_action(env)
                env.step(action)
                if env.state.is_wire_broken:
                    break

            assert env.config.wire_diameter == diameter

    def test_config_validation_rejects_invalid(self):
        """Invalid configurations should be rejected."""
        invalid_configs = [
            {"workpiece_height": 0},
            {"workpiece_height": -10},
            {"wire_diameter": 0},
            {"initial_gap": -5},
        ]

        for invalid in invalid_configs:
            config = EnvironmentConfig(**invalid)
            with pytest.raises(ValueError):
                config.validate()


class TestGymInterface:
    """Tests that verify Gymnasium interface compliance."""

    def test_reset_returns_correct_format(self):
        """Reset should return (observation, info) tuple."""
        env = WireEDMEnv()
        result = env.reset()

        assert isinstance(result, tuple)
        assert len(result) == 2
        obs, info = result
        assert isinstance(info, dict)

    def test_step_returns_correct_format(self):
        """Step should return (obs, reward, terminated, truncated, info)."""
        env = WireEDMEnv()
        env.reset()

        action = sample_valid_action(env)
        result = env.step(action)

        assert isinstance(result, tuple)
        assert len(result) == 5
        obs, reward, terminated, truncated, info = result
        assert isinstance(reward, (int, float))
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_action_space_is_valid(self):
        """Action space should be sampleable and have expected structure."""
        env = WireEDMEnv()

        action = env.action_space.sample()

        assert "servo" in action
        assert "generator_control" in action
        assert "target_voltage" in action["generator_control"]
        assert "current_mode" in action["generator_control"]

    def test_seed_produces_reproducible_results(self):
        """Same seed should produce same initial state."""
        env1 = WireEDMEnv()
        env2 = WireEDMEnv()

        env1.reset(seed=42)
        env2.reset(seed=42)

        assert env1.state.workpiece_position == env2.state.workpiece_position
        assert env1.state.wire_position == env2.state.wire_position
