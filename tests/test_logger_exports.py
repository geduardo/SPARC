import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from wedm.core.state import EDMState
from wedm.utils.logger import SimulationLogger


def _memory_logger_config(signals):
    return {
        "signals_to_log": signals,
        "log_frequency": {"type": "every_step"},
        "backend": {"type": "memory"},
    }


def _json_logger_config(signals, output_path, indent=2):
    return {
        "signals_to_log": signals,
        "log_frequency": {"type": "every_step"},
        "backend": {
            "type": "json",
            "filepath": str(output_path),
            "indent": indent,
        },
    }


def _numpy_logger_config(signals, output_path):
    return {
        "signals_to_log": signals,
        "log_frequency": {"type": "every_step"},
        "backend": {"type": "numpy", "filepath": str(output_path)},
    }


def _read_packed_array(output_path, name):
    with zipfile.ZipFile(output_path) as zf:
        return np.load(io.BytesIO(zf.read(f"{name}.npy")), allow_pickle=False)


def _build_env(
    *,
    wire_diameter=0.25,
    initial_gap=12.0,
    workpiece_height=20.0,
    target_cutting_distance=5.0,
    dt=2,
    servo_interval=10,
    base_overcut=0.05,
):
    env = SimpleNamespace(
        config=SimpleNamespace(
            wire_diameter=wire_diameter,
            initial_gap=initial_gap,
            workpiece_height=workpiece_height,
            target_cutting_distance=target_cutting_distance,
            dt=dt,
            servo_interval=servo_interval,
        )
    )
    env.wire = SimpleNamespace(
        params=SimpleNamespace(
            buffer_len_bottom=30.0,
            buffer_len_top=30.0,
            contact_offset_bottom=10.0,
            contact_offset_top=10.0,
            segment_len=0.2,
        )
    )
    if base_overcut is not None:
        env.material = SimpleNamespace(params=SimpleNamespace(base_overcut=base_overcut))
    return env


def test_memory_logger_snapshots_mutable_values():
    logger = SimulationLogger(
        _memory_logger_config(["wire_temperature", "spark_status", "ionized_channel"])
    )
    state = EDMState(
        wire_temperature=np.array([10.0, 20.0], dtype=np.float32),
        spark_status=[1, 0.5, 3],
        ionized_channel=(4.5, 6),
    )

    logger.collect(state)

    state.wire_temperature[0] = 99.0
    state.spark_status[0] = 0
    state.ionized_channel = (0.0, 0)

    data = logger.get_data()

    np.testing.assert_array_equal(
        data["wire_temperature"][0], np.array([10.0, 20.0], dtype=np.float32)
    )
    assert data["spark_status"][0] == [1, 0.5, 3]
    assert data["ionized_channel"][0] == [4.5, 6]


def test_json_logger_writes_serializable_payload_and_metadata(tmp_path):
    output_path = tmp_path / "simulation.json"
    logger = SimulationLogger(
        _json_logger_config(
            ["time", "wire_temperature", "spark_status", "ionized_channel"],
            output_path,
            indent=0,
        ),
        _build_env(),
    )
    state = EDMState(
        time=7,
        wire_temperature=np.array([1.0, 2.0], dtype=np.float32),
        wire_material_positions_mm=np.array([0.0, 0.2], dtype=np.float64),
        spark_status=[1, 0.5, 3],
        ionized_channel=(4.5, 6),
    )

    logger.collect(state)
    logger.finalize()

    payload = json.loads(output_path.read_text())

    assert payload["time"] == [7]
    assert payload["wire_temperature"] == [[1.0, 2.0]]
    assert payload["wire_material_positions_mm"] == [[0.0, 0.2]]
    assert payload["spark_status"] == [[1, 0.5, 3]]
    assert payload["ionized_channel"] == [[4.5, 6]]
    assert payload["metadata"]["wire_diameter"] == 0.25
    assert payload["metadata"]["wire_diameter_um"] == 250.0
    assert payload["metadata"]["initial_gap"] == 12.0
    assert payload["metadata"]["base_overcut"] == 0.05


def test_numpy_logger_writes_pack_and_decomposes_spark_status(tmp_path):
    output_path = tmp_path / "simulation_pack.npz"
    logger = SimulationLogger(
        _numpy_logger_config(["time", "wire_temperature", "spark_status"], output_path)
    )

    logger.collect(
        EDMState(
            time=0,
            wire_temperature=np.array([10.0, 20.0], dtype=np.float32),
            spark_status=[1, 0.5, 3],
        )
    )
    logger.collect(
        EDMState(
            time=1,
            wire_temperature=np.array([11.0, 21.0], dtype=np.float32),
            spark_status=[0, None, 0],
        )
    )
    logger.finalize()

    with zipfile.ZipFile(output_path) as zf:
        names = set(zf.namelist())
        header = json.loads(zf.read("header.json"))

    assert "header.json" in names
    assert "time.npy" in names
    assert "wire_temperature.npy" in names
    assert "spark_status_state.npy" in names
    assert "spark_status_location_mm.npy" in names
    assert "spark_status_extra.npy" in names
    assert "spark_status.npy" not in names
    assert header["format"] == "sparc_pack_v1"
    assert {
        "time",
        "wire_temperature",
        "spark_status_state",
        "spark_status_location_mm",
        "spark_status_extra",
    } <= {entry["name"] for entry in header["arrays"]}

    np.testing.assert_array_equal(_read_packed_array(output_path, "time"), np.array([0, 1]))
    np.testing.assert_array_equal(
        _read_packed_array(output_path, "spark_status_state"),
        np.array([1, 0], dtype=np.int8),
    )
    np.testing.assert_allclose(
        _read_packed_array(output_path, "spark_status_location_mm"),
        np.array([0.5, np.nan]),
        equal_nan=True,
    )
    np.testing.assert_allclose(
        _read_packed_array(output_path, "spark_status_extra"),
        np.array([3.0, 0.0]),
    )


def test_numpy_logger_writes_wire_material_positions_from_state_contract(tmp_path):
    output_path = tmp_path / "wire_positions_pack.npz"
    logger = SimulationLogger(
        _numpy_logger_config(
            ["time", "wire_temperature", "wire_material_positions_mm"], output_path
        )
    )

    logger.collect(
        EDMState(
            time=0,
            wire_temperature=np.array([10.0, 20.0], dtype=np.float32),
            wire_material_positions_mm=np.array([0.0, 0.2], dtype=np.float64),
        )
    )
    logger.collect(
        EDMState(
            time=1,
            wire_temperature=np.array([11.0, 21.0], dtype=np.float32),
            wire_material_positions_mm=np.array([0.1, 0.3], dtype=np.float64),
        )
    )
    logger.finalize()

    with zipfile.ZipFile(output_path) as zf:
        header = json.loads(zf.read("header.json"))

    manifest_names = {entry["name"] for entry in header["arrays"]}
    assert "wire_material_positions_mm" in manifest_names
    np.testing.assert_array_equal(
        _read_packed_array(output_path, "wire_material_positions_mm"),
        np.array([[0.0, 0.2], [0.1, 0.3]], dtype=np.float64),
    )


def test_numpy_logger_auto_includes_visualization_companions_and_metadata(tmp_path):
    output_path = tmp_path / "visualization_pack.npz"
    logger = SimulationLogger(
        _numpy_logger_config(["time", "wire_temperature"], output_path),
        _build_env(),
    )

    logger.collect(
        EDMState(
            time=0,
            wire_temperature=np.array([10.0, 20.0], dtype=np.float32),
            wire_head_idx=1,
            wire_offset_mm=0.05,
            wire_material_positions_mm=np.array([0.05, 0.25], dtype=np.float64),
        )
    )
    logger.finalize()

    with zipfile.ZipFile(output_path) as zf:
        header = json.loads(zf.read("header.json"))

    manifest_names = {entry["name"] for entry in header["arrays"]}
    assert "wire_material_positions_mm" in manifest_names
    assert "wire_head_idx" in manifest_names
    assert "wire_offset_mm" in manifest_names
    assert "wire_material_positions_mm" in header["signals"]
    assert header["metadata"]["wire_diameter_um"] == 250.0
    assert header["metadata"]["initial_gap"] == 12.0
    assert header["metadata"]["workpiece_height_mm"] == 20.0
    assert header["metadata"]["segment_len_mm"] == 0.2
    assert header["metadata"]["base_overcut"] == 0.05


def test_numpy_logger_warns_and_skips_unconvertible_signal(tmp_path, caplog):
    output_path = tmp_path / "partial_pack.npz"
    logger = SimulationLogger(_numpy_logger_config(["time"], output_path))
    logger.log_data["time"] = [0, 1]
    logger.log_data["wire_temperature"] = [
        np.array([1.0], dtype=np.float32),
        np.array([1.0, 2.0], dtype=np.float32),
    ]

    with caplog.at_level("WARNING"):
        logger.finalize()

    assert "Could not convert signal 'wire_temperature' to NumPy array" in caplog.text
    assert output_path.exists()

    with zipfile.ZipFile(output_path) as zf:
        header = json.loads(zf.read("header.json"))

    manifest_names = {entry["name"] for entry in header["arrays"]}
    assert "time" in manifest_names
    assert "wire_temperature" not in manifest_names


def test_json_logger_warns_on_invalid_metadata_and_still_writes_data(
    tmp_path, caplog
):
    output_path = tmp_path / "bad_metadata.json"
    logger = SimulationLogger(
        _json_logger_config(["time"], output_path),
        _build_env(wire_diameter="invalid-value", base_overcut=None),
    )

    logger.collect(EDMState(time=4))
    with caplog.at_level("WARNING"):
        logger.finalize()

    assert "Could not add environment config to JSON metadata" in caplog.text
    payload = json.loads(output_path.read_text())
    assert payload["time"] == [4]
    assert "metadata" not in payload


def test_json_logger_reports_file_write_error(tmp_path, caplog, monkeypatch):
    output_path = tmp_path / "unwritable.json"
    logger = SimulationLogger(_json_logger_config(["time"], output_path))
    logger.collect(EDMState(time=1))

    real_open = open

    def fail_open(path, mode="r", *args, **kwargs):
        if "w" in mode and Path(path) == output_path:
            raise OSError("disk full")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fail_open)

    with caplog.at_level("ERROR"):
        logger.finalize()

    assert f"Error saving data to {output_path}: disk full" in caplog.text
    assert not output_path.exists()
