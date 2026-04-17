from __future__ import annotations

import gymnasium as gym


SERVO_CONTROL_ENV_ID = "wedm/ServoControl-v0"
DEFAULT_EPISODE_HORIZON_US = 3_000_000
DEFAULT_CONTROL_INTERVAL_US = 1_000
DEFAULT_MAX_EPISODE_STEPS = (
    DEFAULT_EPISODE_HORIZON_US // DEFAULT_CONTROL_INTERVAL_US
)


def register_envs() -> None:
    """Register SPARC training-facing Gymnasium envs exactly once."""
    if SERVO_CONTROL_ENV_ID in gym.registry:
        return

    gym.register(
        id=SERVO_CONTROL_ENV_ID,
        entry_point="wedm.rl.envs:ServoControlEnv",
        max_episode_steps=DEFAULT_MAX_EPISODE_STEPS,
    )
