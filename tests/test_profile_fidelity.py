from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_run_step_loop_counts_craters_without_analysis_tracking() -> None:
    module = load_module(REPO_ROOT / "scripts" / "profile_simulation.py", "profile_fidelity_run")

    class FakeEnv:
        def __init__(self) -> None:
            self.servo_interval = 1
            self._index = 0
            self._crater_volumes = [0.0, 0.002, 0.0, 0.003]
            self.state = SimpleNamespace(
                time=0,
                last_crater_volume=0.0,
                wire_temperature=np.array([300.0, 320.0], dtype=np.float32),
                wire_max_damage=0.125,
                workpiece_position=4.5,
            )

        def step(self, _action):
            self.state.last_crater_volume = self._crater_volumes[self._index]
            self._index += 1
            self.state.time += 1
            terminated = self._index >= len(self._crater_volumes)
            info = {"wire_broken": False, "target_reached": False}
            return None, None, terminated, False, info

    sample = module.run_step_loop(FakeEnv(), action={}, steps=10)

    assert sample.crater_count == 2
    assert abs(sample.crater_volume_mm3 - 0.005) < 1e-9
    assert sample.termination_reason == "terminated"
    assert sample.workpiece_position_um == 4.5


def test_reset_for_run_initializes_compiled_scheduler_after_servo_mark() -> None:
    module = load_module(REPO_ROOT / "scripts" / "profile_simulation.py", "profile_reset_compiled")
    calls = []

    class FakeEnv:
        def __init__(self) -> None:
            self.servo_interval = 7
            self.state = SimpleNamespace(time_since_servo=0)

        def reset(self, *, seed: int) -> None:
            calls.append(("reset", seed))
            self.state.time_since_servo = 0

        def init_compiled_scheduler(self) -> None:
            calls.append(("init", self.state.time_since_servo))

    env = FakeEnv()
    module.reset_for_run(env, seed=123, engine="compiled")

    assert calls == [("reset", 123), ("init", 7)]
    assert env.state.time_since_servo == 7


def test_run_step_loop_uses_compiled_hot_state_for_crater_tracking() -> None:
    module = load_module(REPO_ROOT / "scripts" / "profile_simulation.py", "profile_fidelity_compiled")

    class FakeEnv:
        def __init__(self) -> None:
            self._index = 0
            self._crater_volumes = [0.0, 0.002, 0.0, 0.003]
            self._hot_state = SimpleNamespace(last_crater_volume=0.0)
            self.state = SimpleNamespace(
                time=0,
                last_crater_volume=99.0,
                wire_temperature=np.array([300.0, 320.0], dtype=np.float32),
                wire_max_damage=0.125,
                workpiece_position=7.5,
            )

        def step_compiled(self, _action):
            self._hot_state.last_crater_volume = self._crater_volumes[self._index]
            self._index += 1
            terminated = self._index >= len(self._crater_volumes)
            return None, 0.0, terminated, False, {"wire_broken": False, "target_reached": False}

        def sync_compiled_to_state(self) -> None:
            self.state.time = self._index
            self.state.last_crater_volume = self._hot_state.last_crater_volume

    sample = module.run_step_loop(FakeEnv(), action={}, steps=10, engine="compiled")

    assert sample.crater_count == 2
    assert abs(sample.crater_volume_mm3 - 0.005) < 1e-9
    assert sample.termination_reason == "terminated"
    assert sample.workpiece_position_um == 7.5


def test_build_dashboard_signal_status_marks_thermal_panel_ready() -> None:
    module = load_module(REPO_ROOT / "scripts" / "profile_simulation.py", "profile_fidelity_status")
    env = SimpleNamespace(
        state=SimpleNamespace(
            wire_temperature=np.array([300.0, 320.0], dtype=np.float32),
            wire_material_positions_mm=np.array([0.0, 0.2], dtype=np.float64),
            wire_head_idx=0,
            wire_offset_mm=0.0,
        )
    )

    status = module.build_dashboard_signal_status(env)

    assert status["thermal_profile_ready"] is True
    assert status["wire_temperature"]["shape"] == [2]
    assert status["wire_material_positions_mm"]["shape"] == [2]


def test_compare_fidelity_signatures_detects_dashboard_regression() -> None:
    module = load_module(REPO_ROOT / "scripts" / "profile_simulation.py", "profile_fidelity_compare")

    baseline_report = {
        "scenarios": [
            {
                "segment_len_mm": 0.2,
                "n_segments": 400,
                "fidelity_signature": {
                    "termination_reason": "completed",
                    "crater_count": 200,
                    "wire_temperature_mean": 312.3,
                    "wire_max_damage": 0.00001,
                    "workpiece_position_um": 7.5,
                    "dashboard_required_signals": {
                        "wire_temperature": {"present": True, "shape": [400]},
                        "wire_material_positions_mm": {"present": True, "shape": [400]},
                        "wire_head_idx": {"present": True, "value": 0},
                        "wire_offset_mm": {"present": True, "value": 0.0},
                        "thermal_profile_ready": True,
                    },
                },
            }
        ]
    }
    current_report = {
        "scenarios": [
            {
                "segment_len_mm": 0.2,
                "n_segments": 400,
                "fidelity_signature": {
                    "termination_reason": "completed",
                    "crater_count": 200,
                    "wire_temperature_mean": 312.55,
                    "wire_max_damage": 0.00002,
                    "workpiece_position_um": 7.55,
                    "dashboard_required_signals": {
                        "wire_temperature": {"present": True, "shape": [400]},
                        "wire_material_positions_mm": {"present": False, "shape": None},
                        "wire_head_idx": {"present": True, "value": 0},
                        "wire_offset_mm": {"present": True, "value": 0.0},
                        "thermal_profile_ready": False,
                    },
                },
            }
        ]
    }

    comparison = module.compare_fidelity_signatures(
        baseline_report,
        current_report,
        tolerances={
            "crater_count_abs": 0.0,
            "wire_temperature_mean_abs": 0.5,
            "wire_max_damage_abs": 1e-3,
            "workpiece_position_um_abs": 0.1,
        },
    )

    assert comparison["passed"] is False
    assert comparison["scenarios"][0]["dashboard_required_signals"]["passed"] is False


def test_compare_fidelity_signatures_passes_within_tolerance() -> None:
    module = load_module(REPO_ROOT / "scripts" / "profile_simulation.py", "profile_fidelity_compare_ok")

    signature = {
        "termination_reason": "completed",
        "crater_count": 200,
        "wire_temperature_mean": 312.3,
        "wire_max_damage": 0.00001,
        "workpiece_position_um": 7.5,
        "dashboard_required_signals": {
            "wire_temperature": {"present": True, "shape": [400]},
            "wire_material_positions_mm": {"present": True, "shape": [400]},
            "wire_head_idx": {"present": True, "value": 0},
            "wire_offset_mm": {"present": True, "value": 0.0},
            "thermal_profile_ready": True,
        },
    }
    baseline_report = {
        "scenarios": [{"segment_len_mm": 0.2, "n_segments": 400, "fidelity_signature": signature}]
    }
    current_report = {
        "scenarios": [
            {
                "segment_len_mm": 0.2,
                "n_segments": 400,
                "fidelity_signature": {
                    **signature,
                    "wire_temperature_mean": 312.6,
                    "wire_max_damage": 0.00005,
                    "workpiece_position_um": 7.55,
                },
            }
        ]
    }

    comparison = module.compare_fidelity_signatures(
        baseline_report,
        current_report,
        tolerances={
            "crater_count_abs": 0.0,
            "wire_temperature_mean_abs": 0.5,
            "wire_max_damage_abs": 1e-3,
            "workpiece_position_um_abs": 0.1,
        },
    )

    assert comparison["passed"] is True
