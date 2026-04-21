import gymnasium as gym
import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from wedm.core.env_config import EnvironmentConfig
from wedm.core.constants import WIRE_BREAK_POSITION_MARGIN_UM
from wedm.rl import (
    DEFAULT_MAX_EPISODE_STEPS,
    SERVO_CONTROL_ENV_ID,
    ServoControlEnv,
    register_envs,
)


def test_register_envs_is_idempotent():
    register_envs()
    register_envs()

    assert SERVO_CONTROL_ENV_ID in gym.registry


def test_gym_make_creates_servo_control_env():
    env = gym.make(SERVO_CONTROL_ENV_ID, disable_env_checker=True)
    try:
        assert env.unwrapped.__class__ is ServoControlEnv
        assert env.spec is not None
        assert env.spec.id == SERVO_CONTROL_ENV_ID
        assert env.spec.max_episode_steps is None
        assert env.unwrapped.max_episode_steps == DEFAULT_MAX_EPISODE_STEPS
    finally:
        env.close()


def test_servo_control_passes_check_env():
    env = ServoControlEnv()
    check_env(env, skip_render_check=True)


@pytest.mark.parametrize("use_compiled", [False, True])
def test_servo_control_reset_and_step_are_deterministic_for_fixed_seed(use_compiled):
    env_a = ServoControlEnv(use_compiled=use_compiled)
    env_b = ServoControlEnv(use_compiled=use_compiled)
    action = np.array([0.25], dtype=np.float32)

    obs_a, info_a = env_a.reset(seed=321)
    obs_b, info_b = env_b.reset(seed=321)
    assert obs_a.keys() == obs_b.keys()
    for key in obs_a:
        np.testing.assert_allclose(obs_a[key], obs_b[key])
    assert info_a == info_b

    step_a = env_a.step(action)
    step_b = env_b.step(action)

    obs_step_a, reward_a, terminated_a, truncated_a, info_step_a = step_a
    obs_step_b, reward_b, terminated_b, truncated_b, info_step_b = step_b

    for key in obs_step_a:
        np.testing.assert_allclose(obs_step_a[key], obs_step_b[key])
    assert reward_a == pytest.approx(reward_b)
    assert terminated_a is terminated_b
    assert truncated_a is truncated_b
    assert info_step_a == info_step_b


def test_gym_make_time_limit_truncates_episode():
    env = gym.make(
        SERVO_CONTROL_ENV_ID,
        max_episode_steps=3,
        disable_env_checker=True,
    )
    try:
        env.reset(seed=123)
        terminated = False
        truncated = False
        info = {}

        for _ in range(3):
            _, _, terminated, truncated, info = env.step(
                np.array([0.0], dtype=np.float32)
            )

        assert terminated is False
        assert truncated is True
        assert info["sim_time_us"] == 3 * env.unwrapped.control_interval_us
    finally:
        env.close()


def test_gym_make_uses_dynamic_default_horizon_for_custom_control_interval():
    env = gym.make(
        SERVO_CONTROL_ENV_ID,
        config=EnvironmentConfig(servo_interval=500),
        episode_horizon_us=1_500,
        disable_env_checker=True,
    )
    try:
        env.reset(seed=123)
        terminated = False
        truncated = False
        info = {}

        for _ in range(3):
            _, _, terminated, truncated, info = env.step(
                np.array([0.0], dtype=np.float32)
            )

        assert env.unwrapped.max_episode_steps == 3
        assert terminated is False
        assert truncated is True
        assert info["sim_time_us"] == 1_500
        assert info["control_interval_us"] == 500
    finally:
        env.close()


@pytest.mark.parametrize("use_compiled", [False, True])
def test_servo_control_reports_wire_break_termination(use_compiled):
    env = ServoControlEnv(use_compiled=use_compiled)
    env.reset(seed=123)
    env.simulator.state.wire_position = (
        env.simulator.state.workpiece_position + WIRE_BREAK_POSITION_MARGIN_UM + 1.0
    )

    _, _, terminated, truncated, info = env.step(np.array([0.0], dtype=np.float32))

    assert terminated is True
    assert truncated is False
    assert info["wire_broken"] is True
