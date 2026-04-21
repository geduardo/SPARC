import numpy as np
import pytest

from wedm.core.env_config import EnvironmentConfig
from wedm.rl.envs import ServoControlEnv


@pytest.mark.parametrize("use_compiled", [False, True])
def test_servo_control_reset_returns_valid_scalar_observation(use_compiled):
    env = ServoControlEnv(use_compiled=use_compiled)

    obs, info = env.reset(seed=123)

    assert env.observation_space.contains(obs)
    assert set(obs) == {
        "gap_um",
        "wire_position_um",
        "workpiece_position_um",
        "wire_velocity_um_s",
        "interval_mean_voltage_v",
        "interval_mean_current_a",
        "previous_action",
    }
    assert obs["previous_action"][0] == pytest.approx(0.0)
    assert obs["interval_mean_voltage_v"][0] == pytest.approx(0.0)
    assert obs["interval_mean_current_a"][0] == pytest.approx(0.0)
    assert info["sim_time_us"] == 0
    assert info["interval_microsteps"] == 0
    assert info["interval_charge"] == pytest.approx(0.0)
    assert info["interval_spark_count"] == 0
    assert info["interval_short_count"] == 0
    assert env.simulator.state.time == 0


@pytest.mark.parametrize("use_compiled", [False, True])
def test_servo_control_step_advances_exactly_one_control_interval(use_compiled):
    env = ServoControlEnv(use_compiled=use_compiled)
    env.reset(seed=123)

    obs, reward, terminated, truncated, info = env.step(
        np.array([0.25], dtype=np.float32)
    )

    assert env.observation_space.contains(obs)
    assert reward == pytest.approx(0.0)
    assert terminated is False
    assert truncated is False
    assert env.simulator.state.time == env.control_interval_us
    assert info["interval_microsteps"] == env.control_interval_us
    assert info["interval_duration_us"] == env.control_interval_us
    assert info["sim_time_us"] == env.control_interval_us
    assert info["last_action"] == pytest.approx(0.25)
    assert reward == pytest.approx(info["interval_charge"])
    assert obs["previous_action"][0] == pytest.approx(0.25)
    assert obs["interval_mean_voltage_v"][0] == pytest.approx(
        info["interval_mean_voltage"]
    )
    assert obs["interval_mean_current_a"][0] == pytest.approx(
        info["interval_mean_current"]
    )
    assert info["gap_um"] == pytest.approx(
        info["workpiece_position_um"] - info["wire_position_um"]
    )
    assert env.simulator.state.target_delta == pytest.approx(0.25)


@pytest.mark.parametrize("use_compiled", [False, True])
def test_servo_control_uses_fixed_generator_defaults(use_compiled):
    env = ServoControlEnv(use_compiled=use_compiled)
    env.reset(seed=123)
    defaults = env.simulator.get_default_discharge_settings()

    env.step(np.array([0.4], dtype=np.float32))

    assert env.simulator.state.target_voltage == pytest.approx(
        float(defaults["target_voltage"])
    )
    assert env.simulator.state.current_mode == defaults["current_mode"]
    assert env.simulator.state.ON_time == pytest.approx(float(defaults["ON_time"]))
    assert env.simulator.state.OFF_time == pytest.approx(float(defaults["OFF_time"]))


@pytest.mark.parametrize("use_compiled", [False, True])
def test_servo_control_propagates_simulator_termination(use_compiled):
    env = ServoControlEnv(use_compiled=use_compiled)
    env.reset(seed=123)
    env.simulator.state.target_position = env.simulator.state.workpiece_position

    _, _, terminated, truncated, info = env.step(np.array([0.0], dtype=np.float32))

    assert terminated is True
    assert truncated is False
    assert info["target_reached"] is True


@pytest.mark.parametrize("use_compiled", [False, True])
def test_servo_control_uses_dynamic_default_episode_limit(use_compiled):
    env = ServoControlEnv(
        use_compiled=use_compiled,
        config=EnvironmentConfig(servo_interval=500),
        episode_horizon_us=1_500,
    )
    env.reset(seed=123)

    for step_index in range(3):
        _, _, terminated, truncated, info = env.step(np.array([0.0], dtype=np.float32))
        assert terminated is False
        assert info["elapsed_episode_steps"] == step_index + 1

    assert env.max_episode_steps == 3
    assert truncated is True
    assert info["sim_time_us"] == 1_500
    assert info["control_interval_us"] == 500


@pytest.mark.parametrize("use_compiled", [False, True])
def test_servo_control_advance_interval_exposes_microstep_callbacks(use_compiled):
    env = ServoControlEnv(
        use_compiled=use_compiled,
        config=EnvironmentConfig(servo_interval=4),
        episode_horizon_us=16,
    )
    env.reset(seed=123)
    callbacks = []

    def collect(state, info):
        callbacks.append((int(state.time), bool(info["control_step"])))

    _, _, terminated, truncated, info = env.advance_interval(
        np.array([0.0], dtype=np.float32),
        microstep_callback=collect,
    )

    assert terminated is False
    assert truncated is False
    assert info["interval_microsteps"] == 4
    assert callbacks == [
        (1, True),
        (2, False),
        (3, False),
        (4, False),
    ]
