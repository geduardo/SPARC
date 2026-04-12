import subprocess
import sys
from pathlib import Path
import json

from wedm import EnvironmentConfig
from wedm.realtime.launch import (
    build_arg_parser,
    build_demo_env,
    build_environment_config,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REALTIME_RUNNER = REPO_ROOT / "scripts" / "run_realtime.py"
REALTIME_SMOKE_ALIAS = REPO_ROOT / "scripts" / "run_realtime_smoke.py"


def run_cli(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_realtime_launcher_help_shows_canonical_pacing_flags() -> None:
    result = run_cli(REALTIME_RUNNER, "--help")

    assert result.returncode == 0
    assert "--pace-us-per-s" in result.stdout
    assert "--slowdown-factor" in result.stdout
    assert "--config" in result.stdout
    assert "--workpiece-height" in result.stdout
    assert "--wire-material" in result.stdout
    assert "--dt" not in result.stdout
    assert "--open-browser" in result.stdout
    assert "realtime mode entrypoint" in result.stdout


def test_realtime_smoke_alias_reuses_canonical_help() -> None:
    result = run_cli(REALTIME_SMOKE_ALIAS, "--help")

    assert result.returncode == 0
    assert "--pace-us-per-s" in result.stdout
    assert "--slowdown-factor" in result.stdout
    assert "--config" in result.stdout


def test_realtime_launcher_builds_environment_config_from_cli_overrides() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "--workpiece-height",
            "15.5",
            "--wire-diameter",
            "0.25",
            "--wire-material",
            "brass",
            "--servo-interval",
            "2000",
            "--initial-gap",
            "18",
            "--target-cutting-distance",
            "750",
        ]
    )

    config = build_environment_config(args)

    assert config == EnvironmentConfig(
        workpiece_height=15.5,
        wire_diameter=0.25,
        wire_material="brass",
        dt=1,
        servo_interval=2000,
        initial_gap=18.0,
        target_cutting_distance=750.0,
    )


def test_realtime_launcher_loads_config_file_and_applies_cli_overrides(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "realtime_env.json"
    config_path.write_text(
        json.dumps(
            {
                "workpiece_height": 12.0,
                "wire_diameter": 0.2,
                "wire_material": "brass",
                "dt": 1,
                "servo_interval": 1000,
                "initial_gap": 10.0,
                "target_cutting_distance": 500.0,
            }
        )
    )

    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "--config",
            str(config_path),
            "--wire-diameter",
            "0.3",
            "--initial-gap",
            "22",
        ]
    )

    config = build_environment_config(args)

    assert config.workpiece_height == 12.0
    assert config.wire_diameter == 0.3
    assert config.wire_material == "brass"
    assert config.initial_gap == 22.0
    assert config.target_cutting_distance == 500.0


def test_realtime_launcher_rejects_non_default_dt_from_config_file(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "realtime_env_bad_dt.json"
    config_path.write_text(
        json.dumps(
            {
                "workpiece_height": 12.0,
                "wire_diameter": 0.2,
                "wire_material": "brass",
                "dt": 2,
                "servo_interval": 1000,
                "initial_gap": 10.0,
                "target_cutting_distance": 500.0,
            }
        )
    )

    parser = build_arg_parser()
    args = parser.parse_args(["--config", str(config_path)])

    try:
        build_environment_config(args)
    except ValueError as exc:
        assert "dt=1 us" in str(exc)
    else:
        raise AssertionError("expected realtime launcher to reject non-default dt")


def test_realtime_launcher_builds_demo_env_from_config_values() -> None:
    config = EnvironmentConfig(
        workpiece_height=18.0,
        wire_diameter=0.25,
        wire_material="brass",
        dt=1,
        servo_interval=1000,
        initial_gap=21.0,
        target_cutting_distance=650.0,
    )

    env = build_demo_env(
        123,
        config=config,
        mechanics_control_mode="velocity",
    )

    assert env.config.workpiece_height == 18.0
    assert env.config.initial_gap == 21.0
    assert env.state.workpiece_position == 21.0
    assert env.state.target_position == 650.0
    assert env.mechanics_control_mode == "velocity"
