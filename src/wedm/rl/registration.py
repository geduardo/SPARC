from __future__ import annotations

import math

import gymnasium as gym


SERVO_CONTROL_ENV_ID = "wedm/ServoControl-v0"
DEFAULT_EPISODE_HORIZON_US = 3_000_000
DEFAULT_CONTROL_INTERVAL_US = 1_000


def resolve_episode_step_limit(
    *,
    control_interval_us: int,
    episode_horizon_us: int = DEFAULT_EPISODE_HORIZON_US,
) -> int:
    """Return the public-step budget needed to cover the requested horizon."""
    if control_interval_us <= 0:
        raise ValueError("control_interval_us must be positive")
    if episode_horizon_us <= 0:
        raise ValueError("episode_horizon_us must be positive")
    return max(1, int(math.ceil(episode_horizon_us / control_interval_us)))


DEFAULT_MAX_EPISODE_STEPS = resolve_episode_step_limit(
    control_interval_us=DEFAULT_CONTROL_INTERVAL_US
)


def register_envs() -> None:
    """Register SPARC training-facing Gymnasium envs exactly once."""
    if SERVO_CONTROL_ENV_ID in gym.registry:
        return

    gym.register(
        id=SERVO_CONTROL_ENV_ID,
        entry_point="wedm.rl.envs:ServoControlEnv",
    )
