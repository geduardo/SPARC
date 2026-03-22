from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_powercfg_setting_indices() -> None:
    module = load_module(REPO_ROOT / "scripts" / "profile_simulation.py", "profile_simulation")
    sample = """
    Current AC Power Setting Index: 0x00000064
    Current DC Power Setting Index: 0x00000050
    """

    assert module.parse_powercfg_setting_indices(sample) == {"ac": 100, "dc": 80}


def test_build_comparability_assessment_flags_battery_cap() -> None:
    module = load_module(REPO_ROOT / "scripts" / "profile_simulation.py", "profile_simulation_flags")

    assessment = module.build_comparability_assessment(
        power_status={
            "power_source": "battery",
            "battery_saver": True,
        },
        power_scheme={
            "max_processor_state_pct": {"ac": 100, "dc": 80},
        },
        performance_snapshot={
            "percent_of_max_frequency": 78.0,
        },
        thermal_info={
            "available": False,
            "reason": "Thermal sensor access denied.",
        },
    )

    assert assessment["underclocked_policy_hint"] is True
    assert assessment["frequency_limited_hint"] is True
    assert assessment["thermal_limited_hint"] is None
    assert "Machine is running on battery power." in assessment["warnings"]
    assert "Battery saver is active." in assessment["warnings"]
    assert "Thermal sensor access denied." in assessment["notes"]


def test_realtime_baseline_command_uses_frozen_preset(tmp_path: Path) -> None:
    module = load_module(
        REPO_ROOT / "scripts" / "profile_realtime_baseline.py",
        "profile_realtime_baseline",
    )
    output_path = tmp_path / "baseline.json"

    command = module.build_profile_command(output_path)

    assert command[0].endswith("python.exe") or command[0].endswith("python")
    assert str(REPO_ROOT / "scripts" / "profile_simulation.py") in command
    assert "--segment-len" in command
    assert command.count("--segment-len") == 2
    assert "--steps" in command
    assert command[command.index("--steps") + 1] == "200000"
    assert "--warmup" in command
    assert command[command.index("--warmup") + 1] == "5000"
    assert "--repeats" in command
    assert command[command.index("--repeats") + 1] == "2"
    assert "--current-mode" in command
    assert command[command.index("--current-mode") + 1] == "1"
    assert "--json-out" in command
    assert command[-1] == str(output_path)
