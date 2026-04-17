import json
import zipfile
from pathlib import Path

import pytest

from wedm.rl.policy_rollout import rollout_servo_control_policy_to_npz
from wedm.rl.sb3_training import build_servo_control_training_env


def test_policy_rollout_exports_dashboard_pack_if_sb3_installed(tmp_path):
    stable_baselines3 = pytest.importorskip("stable_baselines3")
    PPO = stable_baselines3.PPO
    Monitor = pytest.importorskip("stable_baselines3.common.monitor").Monitor

    env = Monitor(
        build_servo_control_training_env(
            max_episode_steps=8,
            seed=123,
            use_compiled=True,
            mechanics_control_mode="position",
        )
    )
    model = PPO(
        "MlpPolicy",
        env,
        verbose=0,
        device="cpu",
        seed=123,
        n_steps=16,
        batch_size=8,
        policy_kwargs={"net_arch": [16, 16]},
    )
    model_path = tmp_path / "tiny_policy"
    model.save(model_path)
    env.close()

    output_path = tmp_path / "policy_rollout.npz"
    summary = rollout_servo_control_policy_to_npz(
        model_path=model_path.with_suffix(".zip"),
        output_path=output_path,
        max_episode_steps=5,
        seed=123,
    )

    assert output_path.exists()
    assert Path(summary["summary_path"]).exists()
    assert summary["public_steps_run"] >= 1
    assert summary["sim_time_us"] >= 1

    with zipfile.ZipFile(output_path) as zf:
        header = json.loads(zf.read("header.json"))

    manifest_names = {entry["name"] for entry in header["arrays"]}
    assert {"time", "voltage", "current", "wire_temperature"} <= manifest_names
    assert header["metadata"]["initial_gap"] > 0.0
