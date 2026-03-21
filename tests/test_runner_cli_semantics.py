import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_RUNNER = REPO_ROOT / "examples" / "run_simulation.py"
EXPERIMENT_RUNNER = REPO_ROOT / "experiments" / "run_simulation.py"


def run_cli(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_example_runner_help_shows_explicit_voltage_flags() -> None:
    result = run_cli(EXAMPLE_RUNNER, "--help")

    assert result.returncode == 0
    assert "--generator-voltage" in result.stdout
    assert "--target-avg-voltage" in result.stdout
    assert "fixed-servo" in result.stdout


def test_experiment_runner_help_shows_explicit_voltage_flags() -> None:
    result = run_cli(EXPERIMENT_RUNNER, "--help")

    assert result.returncode == 0
    assert "--generator-voltage" in result.stdout
    assert "--target-avg-voltage" in result.stdout
    assert "fixed-servo" in result.stdout


def test_example_runner_rejects_legacy_target_voltage_flag() -> None:
    result = run_cli(EXAMPLE_RUNNER, "--target-voltage", "47")

    assert result.returncode != 0
    assert "ambiguous" in result.stderr
    assert "--generator-voltage" in result.stderr
    assert "--target-avg-voltage" in result.stderr


def test_experiment_runner_rejects_legacy_target_voltage_flag() -> None:
    result = run_cli(EXPERIMENT_RUNNER, "--target-voltage", "47")

    assert result.returncode != 0
    assert "ambiguous" in result.stderr
    assert "--generator-voltage" in result.stderr
    assert "--target-avg-voltage" in result.stderr
