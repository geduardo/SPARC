from pathlib import Path

import pytest

from wedm.rl.sb3_training import plot_episode_rewards, train_servo_control_ppo


def test_plot_episode_rewards_writes_png(tmp_path):
    output_path = tmp_path / "reward_curve.png"

    result = plot_episode_rewards(
        [10, 20, 30, 40],
        [1.0, 0.5, 1.5, 2.0],
        output_path,
        rolling_window=2,
    )

    assert result == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_train_servo_control_ppo_short_run_if_sb3_installed(tmp_path):
    pytest.importorskip("stable_baselines3")

    summary = train_servo_control_ppo(
        total_timesteps=128,
        output_dir=tmp_path,
        seed=123,
        max_episode_steps=16,
        eval_episodes=2,
        checkpoint_interval_episodes=1,
    )

    assert Path(summary["reward_curve_path"]).exists()
    assert Path(summary["model_path"]).exists()
    assert Path(summary["summary_path"]).exists()
    assert summary["episodes_recorded"] >= 1
    assert summary["checkpoint_paths"]
    for checkpoint_path in summary["checkpoint_paths"]:
        assert Path(checkpoint_path).exists()
