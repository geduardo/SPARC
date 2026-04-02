import json
import subprocess
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "run_simulation.py"
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


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
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


def test_runner_help_shows_engine_and_voltage_flags() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    assert "--generator-voltage" in result.stdout
    assert "--target-avg-voltage" in result.stdout
    assert "--engine" in result.stdout
    assert "compiled-fast" in result.stdout
    assert "fixed-servo" in result.stdout


def test_runner_rejects_legacy_target_voltage_flag() -> None:
    result = run_cli("--target-voltage", "47")

    assert result.returncode != 0
    assert "ambiguous" in result.stderr
    assert "--generator-voltage" in result.stderr
    assert "--target-avg-voltage" in result.stderr


def test_runner_modular_smoke_run_completes(tmp_path) -> None:
    output_path = tmp_path / "runner_modular_smoke.npz"
    result = run_cli(
        "--steps",
        "5",
        "--output",
        str(output_path),
    )

    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    assert "Simulation loop" in result.stdout
    assert "Recorded run" in result.stdout
    assert "slower than realtime" in result.stdout
    assert_dashboard_pack_contract(load_pack_header(output_path))


def test_runner_compiled_smoke_run_completes(tmp_path) -> None:
    output_path = tmp_path / "runner_compiled_smoke.npz"
    result = run_cli(
        "--steps",
        "5",
        "--engine",
        "compiled",
        "--output",
        str(output_path),
    )

    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    assert "Engine: COMPILED" in result.stdout
    assert "Simulation loop" in result.stdout
    assert "Recorded run" in result.stdout
    assert_dashboard_pack_contract(load_pack_header(output_path))


def test_runner_compiled_fast_requires_no_log() -> None:
    result = run_cli(
        "--steps",
        "5",
        "--engine",
        "compiled-fast",
    )

    assert result.returncode != 0
    assert "requires `--no-log`" in result.stderr


def test_runner_compiled_fast_no_log_smoke_run_completes() -> None:
    result = run_cli(
        "--steps",
        "5",
        "--engine",
        "compiled-fast",
        "--no-log",
    )

    assert result.returncode == 0, result.stderr
    assert "Engine: COMPILED-FAST" in result.stdout
    assert "Logging: DISABLED (--no-log)" in result.stdout
    assert "Output file:" not in result.stdout
    assert "Simulation loop" in result.stdout
    assert "Recorded run" in result.stdout


def test_runner_modular_no_log_suppresses_output_file_message() -> None:
    result = run_cli(
        "--steps",
        "5",
        "--engine",
        "modular",
        "--no-log",
    )

    assert result.returncode == 0, result.stderr
    assert "Engine: MODULAR" in result.stdout
    assert "Logging: DISABLED (--no-log)" in result.stdout
    assert "Output file:" not in result.stdout
