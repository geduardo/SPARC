from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from gymnasium.spaces.utils import flatten

from ..core.env_config import EnvironmentConfig
from ..envs.wire_edm import build_scalar_action
from ..utils.logger import LoggerConfig, SimulationLogger
from .envs import ServoControlEnv


_DASHBOARD_SIGNALS = [
    "time",
    "voltage",
    "current",
    "wire_position",
    "wire_velocity",
    "workpiece_position",
    "target_voltage",
    "current_mode",
    "ON_time",
    "OFF_time",
    "is_short_circuit",
    "flow_rate",
    "spark_status",
    "debris_density",
    "wire_temperature",
    "wire_damage",
    "wire_head_idx",
    "wire_offset_mm",
    "wire_material_positions_mm",
]


def _import_sb3():
    try:
        from stable_baselines3 import PPO
    except ImportError as exc:
        raise ImportError(
            "stable-baselines3 is required for policy rollout export. "
            "Install it with `pip install -e \".[rl]\"` or "
            "`pip install stable-baselines3`."
        ) from exc
    return PPO


def build_policy_rollout_logger_config(output_path: str | Path) -> LoggerConfig:
    """Create a dashboard-compatible logging config for offline policy playback."""
    return {
        "signals_to_log": list(_DASHBOARD_SIGNALS),
        "log_frequency": {"type": "every_step"},
        "backend": {
            "type": "numpy",
            "filepath": str(output_path),
            "compress": False,
        },
    }


def _run_logged_control_interval(
    env: ServoControlEnv,
    action,
    logger: SimulationLogger,
) -> tuple[bool, bool]:
    """Advance one public control interval and log every microstep state."""
    servo_delta = env._coerce_action(action)
    sim_action = build_scalar_action(
        servo=servo_delta,
        target_voltage=env._fixed_target_voltage,
        current_mode=env._fixed_current_mode,
        ON_time=env._fixed_on_time,
        OFF_time=env._fixed_off_time,
    )
    env._last_action = servo_delta
    env._prime_control_boundary()

    interval_microsteps = 0
    charge_c = 0.0
    voltage_sum = 0.0
    current_sum = 0.0
    spark_count = 0
    short_count = 0
    dt_seconds = float(env.simulator.dt) * 1e-6

    terminated = False
    truncated = False

    while True:
        if env.use_compiled:
            _, _, terminated, truncated, info = env.simulator.step_compiled(sim_action)
        else:
            _, _, terminated, truncated, info = env.simulator.step(sim_action)

        state = env.simulator.state
        logger.collect(state, info)

        interval_microsteps += 1
        charge_c += float(state.current) * dt_seconds
        voltage_sum += float(state.voltage)
        current_sum += float(state.current)

        spark_state = int(state.spark_status[0])
        spark_duration = int(state.spark_status[2])
        if spark_state == 1 and spark_duration == 0:
            spark_count += 1
        if spark_state == -1 and spark_duration == 0:
            short_count += 1

        interval_complete = state.time_since_servo >= env.control_interval_us
        if terminated or truncated or interval_complete:
            break

    env._last_interval_summary = {
        "interval_charge": float(charge_c),
        "interval_duration_us": int(interval_microsteps * env.simulator.dt),
        "interval_mean_current": (
            0.0 if interval_microsteps == 0 else float(current_sum / interval_microsteps)
        ),
        "interval_mean_voltage": (
            0.0 if interval_microsteps == 0 else float(voltage_sum / interval_microsteps)
        ),
        "interval_spark_count": int(spark_count),
        "interval_short_count": int(short_count),
        "interval_microsteps": int(interval_microsteps),
    }
    return terminated, truncated


def rollout_servo_control_policy_to_npz(
    *,
    model_path: str | Path,
    output_path: str | Path,
    max_episode_steps: int = 3_000,
    seed: int = 123,
    use_compiled: bool = True,
    mechanics_control_mode: str = "position",
    config: EnvironmentConfig | None = None,
    deterministic: bool = True,
) -> dict[str, Any]:
    """Run one offline policy rollout and export a dashboard-compatible NPZ pack."""
    PPO = _import_sb3()

    if max_episode_steps <= 0:
        raise ValueError("max_episode_steps must be positive")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    env = ServoControlEnv(
        use_compiled=use_compiled,
        mechanics_control_mode=mechanics_control_mode,
        config=config,
    )
    logger = SimulationLogger(
        build_policy_rollout_logger_config(output_path),
        env.simulator,
    )
    summary_path = output_path.with_name(f"{output_path.stem}_summary.json")

    try:
        model = PPO.load(str(model_path), device="cpu")
        obs, _ = env.reset(seed=seed)

        cumulative_reward = 0.0
        public_steps_run = 0
        terminated = False
        truncated = False

        while public_steps_run < max_episode_steps:
            flat_obs = flatten(env.observation_space, obs).astype(np.float32)
            action, _ = model.predict(flat_obs, deterministic=deterministic)
            terminated, truncated = _run_logged_control_interval(env, action, logger)
            cumulative_reward += env._calc_reward()
            public_steps_run += 1
            obs = env._get_obs()
            if terminated or truncated:
                break

        if not terminated and not truncated and public_steps_run >= max_episode_steps:
            truncated = True

        logger.finalize()

        summary = {
            "model_path": str(Path(model_path).resolve()),
            "output_path": str(output_path.resolve()),
            "seed": seed,
            "use_compiled": use_compiled,
            "mechanics_control_mode": mechanics_control_mode,
            "max_episode_steps": max_episode_steps,
            "public_steps_run": public_steps_run,
            "sim_time_us": int(env.simulator.state.time),
            "control_interval_us": int(env.control_interval_us),
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "wire_broken": bool(env.simulator.state.is_wire_broken),
            "target_reached": bool(env.simulator.state.is_target_distance_reached),
            "cumulative_reward": float(cumulative_reward),
            "final_gap_um": float(
                env.simulator.state.workpiece_position - env.simulator.state.wire_position
            ),
        }
        summary_path.write_text(json.dumps(summary, indent=2))
        summary["summary_path"] = str(summary_path.resolve())
        return summary
    finally:
        env.close()
