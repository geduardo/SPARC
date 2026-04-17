from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium.wrappers import FlattenObservation, RecordEpisodeStatistics

from ..core.env_config import EnvironmentConfig
from . import SERVO_CONTROL_ENV_ID


def build_servo_control_training_env(
    *,
    max_episode_steps: int,
    seed: int,
    use_compiled: bool,
    mechanics_control_mode: str,
    config: EnvironmentConfig | None = None,
) -> gym.Env:
    """Create a flattened, statistics-enabled ServoControl env for training."""
    env = gym.make(
        SERVO_CONTROL_ENV_ID,
        max_episode_steps=max_episode_steps,
        disable_env_checker=True,
        use_compiled=use_compiled,
        mechanics_control_mode=mechanics_control_mode,
        config=config,
    )
    env = FlattenObservation(env)
    env = RecordEpisodeStatistics(env)
    env.reset(seed=seed)
    return env


def plot_episode_rewards(
    timesteps: list[int] | np.ndarray,
    episode_rewards: list[float] | np.ndarray,
    output_path: str | Path,
    *,
    rolling_window: int = 10,
) -> Path:
    """Plot episode reward evolution with a simple rolling mean overlay."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    timesteps_arr = np.asarray(timesteps, dtype=np.int64)
    rewards_arr = np.asarray(episode_rewards, dtype=np.float64)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    if rewards_arr.size:
        ax.plot(timesteps_arr, rewards_arr, alpha=0.35, label="Episode reward")
        if rewards_arr.size >= rolling_window:
            kernel = np.ones(rolling_window, dtype=np.float64) / rolling_window
            moving_average = np.convolve(rewards_arr, kernel, mode="valid")
            ax.plot(
                timesteps_arr[rolling_window - 1 :],
                moving_average,
                linewidth=2.0,
                label=f"{rolling_window}-episode moving average",
            )
    else:
        ax.text(
            0.5,
            0.5,
            "No completed episodes recorded.",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )

    ax.set_title("ServoControl Episode Reward During Training")
    ax.set_xlabel("Training timesteps")
    ax.set_ylabel("Episode reward")
    ax.grid(True, alpha=0.3)
    if rewards_arr.size:
        ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def _import_sb3():
    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.callbacks import BaseCallback
        from stable_baselines3.common.evaluation import evaluate_policy
        from stable_baselines3.common.monitor import Monitor
    except ImportError as exc:
        raise ImportError(
            "stable-baselines3 is required for SB3 training scripts. "
            "Install it with `pip install -e \".[rl]\"` or "
            "`pip install stable-baselines3`."
        ) from exc
    return PPO, BaseCallback, evaluate_policy, Monitor


def train_servo_control_ppo(
    *,
    total_timesteps: int,
    output_dir: str | Path,
    seed: int = 123,
    max_episode_steps: int = 200,
    use_compiled: bool = True,
    mechanics_control_mode: str = "position",
    config: EnvironmentConfig | None = None,
    learning_rate: float = 3e-4,
    n_steps: int = 256,
    batch_size: int = 64,
    eval_episodes: int = 5,
    rolling_window: int = 10,
    verbose: bool = False,
    progress_step_interval: int = 2_000,
    checkpoint_interval_episodes: int = 20,
) -> dict[str, Any]:
    """Train a small PPO baseline and save model, curve, and summary JSON."""
    PPO, BaseCallback, evaluate_policy, Monitor = _import_sb3()

    class EpisodeRewardCallback(BaseCallback):
        """Collect episode rewards from RecordEpisodeStatistics infos."""

        def __init__(self):
            super().__init__()
            self.timesteps: list[int] = []
            self.episode_rewards: list[float] = []
            self.last_progress_report_step = 0
            self.checkpoint_paths: list[str] = []

        def _on_step(self) -> bool:
            infos = self.locals.get("infos", [])
            for info in infos:
                episode = info.get("episode")
                if episode is None:
                    continue
                self.timesteps.append(int(self.num_timesteps))
                self.episode_rewards.append(float(episode["r"]))
                if verbose:
                    print(
                        "[train] "
                        f"episode={len(self.episode_rewards)} "
                        f"timesteps={self.num_timesteps}/{total_timesteps} "
                        f"episode_reward={self.episode_rewards[-1]:.3f}"
                    )
                if (
                    checkpoint_interval_episodes > 0
                    and len(self.episode_rewards) % checkpoint_interval_episodes == 0
                ):
                    checkpoint_path = (
                        checkpoint_dir
                        / "servo_control_ppo_"
                        f"ep{len(self.episode_rewards):05d}_"
                        f"step{self.num_timesteps:09d}"
                    )
                    self.model.save(checkpoint_path)
                    checkpoint_zip = str(checkpoint_path.with_suffix(".zip"))
                    self.checkpoint_paths.append(checkpoint_zip)
                    if verbose:
                        print(f"[save] checkpoint={checkpoint_zip}")

            if (
                verbose
                and progress_step_interval > 0
                and self.num_timesteps - self.last_progress_report_step
                >= progress_step_interval
            ):
                latest_reward = (
                    f"{self.episode_rewards[-1]:.3f}"
                    if self.episode_rewards
                    else "n/a"
                )
                print(
                    "[train] "
                    f"timesteps={self.num_timesteps}/{total_timesteps} "
                    f"episodes={len(self.episode_rewards)} "
                    f"latest_episode_reward={latest_reward}"
                )
                self.last_progress_report_step = self.num_timesteps
            return True

    if total_timesteps <= 0:
        raise ValueError("total_timesteps must be positive")
    if max_episode_steps <= 0:
        raise ValueError("max_episode_steps must be positive")
    if eval_episodes <= 0:
        raise ValueError("eval_episodes must be positive")
    if progress_step_interval < 0:
        raise ValueError("progress_step_interval must be non-negative")
    if checkpoint_interval_episodes < 0:
        raise ValueError("checkpoint_interval_episodes must be non-negative")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    train_env = build_servo_control_training_env(
        max_episode_steps=max_episode_steps,
        seed=seed,
        use_compiled=use_compiled,
        mechanics_control_mode=mechanics_control_mode,
        config=config,
    )
    train_env = Monitor(train_env)
    eval_env = build_servo_control_training_env(
        max_episode_steps=max_episode_steps,
        seed=seed + 1,
        use_compiled=use_compiled,
        mechanics_control_mode=mechanics_control_mode,
        config=config,
    )
    eval_env = Monitor(eval_env)

    callback = EpisodeRewardCallback()
    model_path = output_dir / "servo_control_ppo_model"
    interrupted_model_path = output_dir / "servo_control_ppo_interrupted_model"
    plot_path = output_dir / "servo_control_training_reward.png"
    summary_path = output_dir / "servo_control_training_summary.json"

    def build_summary(
        *,
        initial_mean_reward: float,
        initial_std_reward: float,
        trained_mean_reward: float | None,
        trained_std_reward: float | None,
        interrupted: bool,
        saved_model_path: Path,
    ) -> dict[str, Any]:
        return {
            "algo": "ppo",
            "env_id": SERVO_CONTROL_ENV_ID,
            "seed": seed,
            "use_compiled": use_compiled,
            "max_episode_steps": max_episode_steps,
            "total_timesteps": total_timesteps,
            "eval_episodes": eval_episodes,
            "initial_mean_reward": float(initial_mean_reward),
            "initial_std_reward": float(initial_std_reward),
            "trained_mean_reward": (
                None if trained_mean_reward is None else float(trained_mean_reward)
            ),
            "trained_std_reward": (
                None if trained_std_reward is None else float(trained_std_reward)
            ),
            "episodes_recorded": len(callback.episode_rewards),
            "interrupted": interrupted,
            "checkpoint_interval_episodes": checkpoint_interval_episodes,
            "checkpoint_dir": str(checkpoint_dir),
            "checkpoint_paths": callback.checkpoint_paths,
            "reward_curve_path": str(plot_path),
            "model_path": str(saved_model_path.with_suffix(".zip")),
        }

    def save_summary(summary: dict[str, Any]) -> dict[str, Any]:
        summary_path.write_text(json.dumps(summary, indent=2))
        summary["summary_path"] = str(summary_path)
        if verbose:
            print(f"[save] reward_curve={summary['reward_curve_path']}")
            print(f"[save] summary={summary['summary_path']}")
        return summary

    try:
        if verbose:
            print(
                "[setup] "
                f"env={SERVO_CONTROL_ENV_ID} "
                f"timesteps={total_timesteps} "
                f"max_episode_steps={max_episode_steps} "
                f"use_compiled={use_compiled} "
                f"mechanics_control_mode={mechanics_control_mode}"
            )

        model = PPO(
            "MlpPolicy",
            train_env,
            verbose=1 if verbose else 0,
            device="cpu",
            seed=seed,
            learning_rate=learning_rate,
            n_steps=n_steps,
            batch_size=batch_size,
            policy_kwargs={"net_arch": [32, 32]},
        )

        if verbose:
            print(
                "[eval] running initial deterministic evaluation "
                f"({eval_episodes} episodes)"
            )
        initial_mean_reward, initial_std_reward = evaluate_policy(
            model,
            eval_env,
            n_eval_episodes=eval_episodes,
            deterministic=True,
        )
        if verbose:
            print(
                "[eval] "
                f"initial_mean_reward={initial_mean_reward:.3f} "
                f"initial_std_reward={initial_std_reward:.3f}"
            )

        if verbose:
            print("[train] starting PPO learning")
        try:
            model.learn(total_timesteps=total_timesteps, callback=callback)
            interrupted = False
        except KeyboardInterrupt:
            interrupted = True
            if verbose:
                print("[train] interrupted by user, saving current model state")
            model.save(interrupted_model_path)
            plot_episode_rewards(
                callback.timesteps,
                callback.episode_rewards,
                plot_path,
                rolling_window=rolling_window,
            )
            summary = build_summary(
                initial_mean_reward=initial_mean_reward,
                initial_std_reward=initial_std_reward,
                trained_mean_reward=None,
                trained_std_reward=None,
                interrupted=True,
                saved_model_path=interrupted_model_path,
            )
            if verbose:
                print(f"[save] model={summary['model_path']}")
            return save_summary(summary)

        trained_mean_reward = None
        trained_std_reward = None
        if not interrupted:
            if verbose:
                print(
                    "[eval] running post-training deterministic evaluation "
                    f"({eval_episodes} episodes)"
                )
            trained_mean_reward, trained_std_reward = evaluate_policy(
                model,
                eval_env,
                n_eval_episodes=eval_episodes,
                deterministic=True,
            )
            if verbose:
                print(
                    "[eval] "
                    f"trained_mean_reward={trained_mean_reward:.3f} "
                    f"trained_std_reward={trained_std_reward:.3f}"
                )

        model.save(model_path)
        plot_episode_rewards(
            callback.timesteps,
            callback.episode_rewards,
            plot_path,
            rolling_window=rolling_window,
        )

        summary = build_summary(
            initial_mean_reward=initial_mean_reward,
            initial_std_reward=initial_std_reward,
            trained_mean_reward=trained_mean_reward,
            trained_std_reward=trained_std_reward,
            interrupted=False,
            saved_model_path=model_path,
        )
        if verbose:
            print(f"[save] model={summary['model_path']}")
        return save_summary(summary)
    finally:
        train_env.close()
        eval_env.close()
