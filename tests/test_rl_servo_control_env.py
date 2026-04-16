import numpy as np
import pytest

from wedm.rl.envs import ServoControlEnv


@pytest.mark.parametrize("use_compiled", [False, True])
def test_servo_control_reset_returns_valid_empty_observation(use_compiled):
    env = ServoControlEnv(use_compiled=use_compiled)

    obs, info = env.reset(seed=123)

    assert obs == {}
    assert env.observation_space.contains(obs)
    assert info["sim_time_us"] == 0
    assert info["interval_microsteps"] == 0
    assert env.simulator.state.time == 0


@pytest.mark.parametrize("use_compiled", [False, True])
def test_servo_control_step_advances_exactly_one_control_interval(use_compiled):
    env = ServoControlEnv(use_compiled=use_compiled)
    env.reset(seed=123)

    obs, reward, terminated, truncated, info = env.step(np.array([0.25], dtype=np.float32))

    assert obs == {}
    assert reward == pytest.approx(0.0)
    assert terminated is False
    assert truncated is False
    assert env.simulator.state.time == env.control_interval_us
    assert info["interval_microsteps"] == env.control_interval_us
    assert info["sim_time_us"] == env.control_interval_us
    assert info["last_action"] == pytest.approx(0.25)
    assert env.simulator.state.target_delta == pytest.approx(0.25)


@pytest.mark.parametrize("use_compiled", [False, True])
def test_servo_control_uses_fixed_generator_defaults(use_compiled):
    env = ServoControlEnv(use_compiled=use_compiled)
    env.reset(seed=123)
    defaults = env.simulator.get_default_discharge_settings()

    env.step(np.array([0.4], dtype=np.float32))

    assert env.simulator.state.target_voltage == pytest.approx(float(defaults["target_voltage"]))
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
