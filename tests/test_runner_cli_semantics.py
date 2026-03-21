import json
import subprocess
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_RUNNER = REPO_ROOT / "examples" / "run_simulation.py"
EXPERIMENT_RUNNER = REPO_ROOT / "experiments" / "run_simulation.py"
REQUIRED_DASHBOARD_ARRAYS = {
    "time",
    "voltage",
    "current",
    "wire_position",
    "workpiece_position",
    "debris_density",
    "wire_temperature",
    "wire_material_positions_mm",
    "spark_status_state",
    "spark_status_location_mm",
    "spark_status_extra",
}
REQUIRED_DASHBOARD_METADATA = {
    "wire_diameter",
    "wire_diameter_um",
    "initial_gap",
    "workpiece_height_mm",
    "base_overcut",
    "buffer_len_bottom",
    "buffer_len_top",
    "contact_offset_bottom",
    "contact_offset_top",
}


def run_cli(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def load_pack_header(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("header.json"))


def assert_dashboard_pack_contract(header: dict) -> None:
    manifest_names = {entry["name"] for entry in header["arrays"]}

    assert REQUIRED_DASHBOARD_ARRAYS <= manifest_names
    assert REQUIRED_DASHBOARD_METADATA <= set(header["metadata"])
    assert set(header["signals"]) == manifest_names


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


def test_example_runner_smoke_run_completes(tmp_path) -> None:
    output_path = tmp_path / "example_smoke.npz"
    result = run_cli(
        EXAMPLE_RUNNER,
        "--steps",
        "5",
        "--quiet",
        "--output",
        str(output_path),
    )

    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    assert_dashboard_pack_contract(load_pack_header(output_path))


def test_experiment_runner_smoke_run_completes(tmp_path) -> None:
    output_path = tmp_path / "experiment_smoke.npz"
    result = run_cli(
        EXPERIMENT_RUNNER,
        "--steps",
        "5",
        "--output",
        str(output_path),
    )

    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    assert_dashboard_pack_contract(load_pack_header(output_path))
