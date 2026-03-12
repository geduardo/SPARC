from __future__ import annotations

from collections import defaultdict
from dataclasses import fields
from difflib import get_close_matches
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, TypedDict, Union
import pathlib  # Added for path manipulation
import numpy as np  # Added for numpy backend
import json  # Added for JSON backend
import copy  # For deep-copying mutable signals like lists
import io
import zipfile

from ..core.state import EDMState

if TYPE_CHECKING:
    from ..envs import WireEDMEnv  # Assuming WireEDMEnv is the main env type

# --- Configuration Types ---


class LogFrequencyEveryStep(TypedDict):
    type: Literal["every_step"]


class LogFrequencyControlStep(TypedDict):
    type: Literal["control_step"]


class LogFrequencyInterval(TypedDict):
    type: Literal["interval"]
    value: int  # Interval in simulation steps (e.g., microseconds)


LogFrequencyConfig = Union[
    LogFrequencyEveryStep, LogFrequencyControlStep, LogFrequencyInterval
]


class BackendMemory(TypedDict):
    type: Literal["memory"]


class BackendNumpy(TypedDict):
    type: Literal["numpy"]
    filepath: str  # Path to save .npz file
    compress: bool  # Whether to use compressed format np.savez_compressed


class BackendJSON(TypedDict):
    type: Literal["json"]
    filepath: str  # Path to save .json file
    indent: int  # Indentation for pretty printing (0 for compact)


# We'll add more backends like numpy, csv, hdf5 later
BackendConfig = Union[BackendMemory, BackendNumpy, BackendJSON]  # Added BackendJSON


class LoggerConfig(TypedDict):
    signals_to_log: List[str]  # List of attribute names from EDMState or special keys
    log_frequency: LogFrequencyConfig
    backend: BackendConfig
    # Optional: buffer_size for file backends, etc.


class SimulationLogger:
    """
    Handles logging of simulation data based on a flexible configuration.
    """

    def __init__(self, config: LoggerConfig, env_reference: WireEDMEnv | None = None):
        self.config = config
        self.env = env_reference  # Optional, for accessing env-level info if needed for signals

        self._validate_config()

        self.log_data: Dict[str, List[Any]] = defaultdict(list)
        self.step_counter = 0  # For interval-based logging

        # Known EDMState and derived signals for strict validation
        self._state_signal_names = {f.name for f in fields(EDMState)}
        self._derived_signal_accessors: Dict[str, Callable[[EDMState], Any]] = {
            # Explicitly supported derived signal names.
            "gap_um": lambda state: state.workpiece_position - state.wire_position,
        }
        self.signal_accessors: Dict[str, Callable[[EDMState], Any]] = {}
        self._prepare_signal_accessors()

    def _validate_config(self):
        if not self.config.get("signals_to_log"):
            raise ValueError(
                "LoggerConfig: 'signals_to_log' must be provided and non-empty."
            )
        if not self.config.get("log_frequency"):
            raise ValueError("LoggerConfig: 'log_frequency' must be provided.")
        if not self.config.get("backend"):
            raise ValueError("LoggerConfig: 'backend' must be provided.")

        backend_type = self.config["backend"]["type"]
        if backend_type not in ["memory", "numpy", "json"]:
            raise NotImplementedError(
                f"Backend type '{backend_type}' is not yet implemented."
            )

        if backend_type == "numpy":
            if "filepath" not in self.config["backend"]:
                raise ValueError(
                    "LoggerConfig: 'filepath' must be provided for 'numpy' backend."
                )
            # Ensure filepath is a string, as TypedDict doesn't enforce this at runtime fully alone
            if not isinstance(self.config["backend"]["filepath"], str):
                raise ValueError(
                    "LoggerConfig: 'filepath' for 'numpy' backend must be a string."
                )
            if (
                "compress" not in self.config["backend"]
            ):  # Default compress to False if not specified
                self.config["backend"]["compress"] = False

        if backend_type == "json":
            if "filepath" not in self.config["backend"]:
                raise ValueError(
                    "LoggerConfig: 'filepath' must be provided for 'json' backend."
                )
            if not isinstance(self.config["backend"]["filepath"], str):
                raise ValueError(
                    "LoggerConfig: 'filepath' for 'json' backend must be a string."
                )
            if "indent" not in self.config["backend"]:
                self.config["backend"]["indent"] = 2  # Default to pretty print

    def _prepare_signal_accessors(self):
        """
        Prepare accessors for known state/derived signals.
        Unknown signal names fail fast to avoid silent None logging.
        """
        invalid_signals = []

        for signal_name in self.config["signals_to_log"]:
            if signal_name in self._state_signal_names:
                self.signal_accessors[signal_name] = (
                    lambda state, name=signal_name: getattr(state, name)
                )
            elif signal_name in self._derived_signal_accessors:
                self.signal_accessors[signal_name] = self._derived_signal_accessors[
                    signal_name
                ]
            else:
                invalid_signals.append(signal_name)

        if invalid_signals:
            supported_names = sorted(
                self._state_signal_names | set(self._derived_signal_accessors.keys())
            )
            hint_parts = []
            for signal_name in invalid_signals:
                suggestions = get_close_matches(
                    signal_name, supported_names, n=3, cutoff=0.6
                )
                if suggestions:
                    hint_parts.append(
                        f"'{signal_name}' -> did you mean {', '.join(suggestions)}?"
                    )

            hint_text = f" Hints: {'; '.join(hint_parts)}" if hint_parts else ""
            derived = ", ".join(sorted(self._derived_signal_accessors.keys()))
            raise ValueError(
                "LoggerConfig: Unknown signals_to_log entries: "
                f"{', '.join(invalid_signals)}. "
                f"Known derived signals: {derived}.{hint_text}"
            )

    def collect(self, state: EDMState, info: Dict[str, Any] | None = None):
        """
        Collects data for the current simulation step if logging criteria are met.

        Args:
            state: The current EDMState object.
            info: Optional dictionary from env.step(), useful for 'control_step' frequency.
        """
        self.step_counter += 1
        should_log = False
        log_freq_conf = self.config["log_frequency"]

        if log_freq_conf["type"] == "every_step":
            should_log = True
        elif log_freq_conf["type"] == "control_step":
            if info and info.get("control_step", False):
                should_log = True
        elif log_freq_conf["type"] == "interval":
            if self.step_counter % log_freq_conf["value"] == 0:
                should_log = True

        if should_log:
            for signal_name in self.config["signals_to_log"]:
                accessor = self.signal_accessors.get(signal_name)
                if accessor:
                    value = accessor(state)
                    # Handle cases like NumPy arrays or specific data types if needed by backend

                    # If the value is a NumPy array, store a copy to avoid issues with in-place modifications
                    # of the original array in the simulation state.
                    # Ensure we snapshot mutable data structures so later in-place
                    # mutations in the simulation don't retroactively change logged values
                    if isinstance(value, np.ndarray):
                        processed_value = value.copy()
                    elif isinstance(value, (list, dict)):
                        processed_value = copy.deepcopy(value)
                    elif isinstance(value, tuple):
                        # Convert tuples to lists for JSON friendliness and snapshot
                        processed_value = list(value)
                    else:
                        processed_value = value

                    if self.config["backend"]["type"] == "memory":
                        self.log_data[signal_name].append(processed_value)
                    elif self.config["backend"]["type"] == "numpy":
                        # For numpy, we also append to lists first, convert to np.array in finalize
                        self.log_data[signal_name].append(processed_value)
                    elif self.config["backend"]["type"] == "json":
                        # For JSON, we append to lists, will serialize in finalize
                        self.log_data[signal_name].append(processed_value)
                    else:
                        # Logic for other backends would go here
                        pass
                else:
                    raise RuntimeError(
                        f"Missing signal accessor for '{signal_name}'. "
                        "Logger configuration should have been validated at initialization."
                    )

    def finalize(self):
        """
        Finalizes logging. For memory backend, this might not do much.
        For file backends, this is where data is flushed to disk.
        """
        if self.config["backend"]["type"] == "memory":
            # print("Memory logger finalized. Data available via get_data().")
            pass
        elif self.config["backend"]["type"] == "json":
            self._finalize_json()
        elif self.config["backend"]["type"] == "numpy":
            filepath_str = self.config["backend"]["filepath"]

            if not self.log_data:
                print("No data collected, skipping .npz file creation.")
                return

            # Convert lists to numpy arrays
            numpy_data: Dict[str, np.ndarray] = {}
            for signal_name, data_list in self.log_data.items():
                try:
                    numpy_data[signal_name] = np.array(data_list)
                except Exception as e:
                    print(
                        f"Warning: Could not convert signal '{signal_name}' to NumPy array: {e}. Skipping this signal in .npz."
                    )

            if not numpy_data:
                print(
                    "No signals could be converted to NumPy arrays, skipping .npz file creation."
                )
                return

            output_path = pathlib.Path(filepath_str)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Export as sparc_pack_v1 format for dashboard compatibility
            self._finalize_numpy_pack(output_path, numpy_data)

    def _finalize_json(self):
        """
        Saves logged data as JSON file for web dashboard consumption.
        """
        filepath_str = self.config["backend"]["filepath"]
        indent = self.config["backend"].get("indent", 2)

        if not self.log_data:
            print("No data collected, skipping .json file creation.")
            return

        # Convert numpy arrays and other types to JSON-serializable format
        json_data = {}
        for signal_name, data_list in self.log_data.items():
            try:
                # Convert each value in the list
                serializable_list = []
                for value in data_list:
                    if isinstance(value, np.ndarray):
                        serializable_list.append(value.tolist())
                    elif isinstance(value, (np.integer, np.floating)):
                        serializable_list.append(value.item())
                    elif isinstance(value, list):
                        # Handle nested lists with numpy elements
                        serializable_list.append(
                            [
                                v.item() if isinstance(v, (np.integer, np.floating)) else v
                                for v in value
                            ]
                        )
                    else:
                        serializable_list.append(value)

                json_data[signal_name] = serializable_list
            except Exception as e:
                print(
                    f"Warning: Could not serialize signal '{signal_name}' to JSON: {e}. Skipping this signal."
                )

        if not json_data:
            print("No signals could be serialized to JSON, skipping .json file creation.")
            return

        # Add environment config as metadata for dashboard
        if self.env and hasattr(self.env, 'config'):
            try:
                json_data['metadata'] = {
                    'wire_diameter': float(self.env.config.wire_diameter),
                    'wire_diameter_um': float(self.env.config.wire_diameter * 1000),
                    'initial_gap': float(self.env.config.initial_gap),
                    'workpiece_height': float(self.env.config.workpiece_height),
                    'workpiece_height_mm': float(self.env.config.workpiece_height),
                    'target_cutting_distance': float(self.env.config.target_cutting_distance),
                    'dt': int(self.env.config.dt),
                    'servo_interval': int(self.env.config.servo_interval),
                }
                # Add material parameters if available
                if hasattr(self.env, 'material') and hasattr(self.env.material, 'params'):
                    json_data['metadata']['base_overcut'] = float(self.env.material.params.base_overcut)
                print("Added environment config as metadata to JSON")
            except Exception as e:
                print(f"Warning: Could not add environment config to JSON metadata: {e}")

        output_path = pathlib.Path(filepath_str)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(output_path, 'w') as f:
                if indent == 0:
                    json.dump(json_data, f, separators=(',', ':'))  # Compact
                else:
                    json.dump(json_data, f, indent=indent)
            print(f"Logged data saved to {output_path}")
        except Exception as e:
            print(f"Error saving data to {output_path}: {e}")

    def _finalize_numpy_pack(self, output_path: pathlib.Path, numpy_data: Dict[str, np.ndarray]) -> None:
        """Export data as sparc_pack_v1 format for web dashboard compatibility.

        Format: ZIP file containing:
          - header.json: lists arrays, shapes, dtypes, and metadata
          - one .npy file per array (NumPy binary, little-endian, no pickle)

        Notes:
          - Object arrays like spark_status are split into numeric 1D arrays:
            spark_status_state (int8), spark_status_location_mm (float64), spark_status_extra (float64)
          - All numeric arrays are written losslessly as-is.
        """
        # Build metadata from environment config
        metadata = {}
        if self.env and hasattr(self.env, 'config'):
            try:
                metadata = {
                    "workpiece_height": float(self.env.config.workpiece_height),
                    "wire_diameter": float(self.env.config.wire_diameter),
                }
            except Exception as e:
                print(f"Warning: Could not extract env config for metadata: {e}")

        # Add wire module parameters if available
        if self.env and hasattr(self.env, 'wire') and hasattr(self.env.wire, 'params'):
            try:
                wire_params = self.env.wire.params
                metadata["buffer_len_bottom"] = float(getattr(wire_params, "buffer_len_bottom", 20.0))
                metadata["buffer_len_top"] = float(getattr(wire_params, "buffer_len_top", 20.0))
                metadata["contact_offset_bottom"] = float(getattr(wire_params, "contact_offset_bottom", 10.0))
                metadata["contact_offset_top"] = float(getattr(wire_params, "contact_offset_top", 10.0))
            except Exception as e:
                print(f"Warning: Could not extract wire params for metadata: {e}")

        # Set defaults if not already set
        metadata.setdefault("workpiece_height", 20.0)
        metadata.setdefault("buffer_len_bottom", 20.0)
        metadata.setdefault("buffer_len_top", 20.0)
        metadata.setdefault("contact_offset_bottom", 10.0)
        metadata.setdefault("contact_offset_top", 10.0)
        metadata.setdefault("wire_diameter", 0.25)

        arrays_manifest = []

        def add_numpy_to_zip(zf: zipfile.ZipFile, name: str, arr: np.ndarray) -> None:
            """Add a numpy array to the zip file as .npy format."""
            if arr.dtype == object:
                raise ValueError(f"Cannot pack object dtype array directly: {name}")
            arr_c = np.ascontiguousarray(arr)
            buf = io.BytesIO()
            np.save(buf, arr_c, allow_pickle=False)
            zf.writestr(f"{name}.npy", buf.getvalue())
            arrays_manifest.append({
                "name": name,
                "dtype": str(arr_c.dtype),
                "shape": list(arr_c.shape),
            })

        # Use STORED (no compression) so the viewer can read bytes directly
        with zipfile.ZipFile(output_path.as_posix(), mode="w", compression=zipfile.ZIP_STORED) as zf:
            # Write all numeric arrays
            for key, arr in numpy_data.items():
                if isinstance(arr, np.ndarray) and arr.dtype != object:
                    try:
                        add_numpy_to_zip(zf, key, arr)
                    except Exception as e:
                        print(f"[WARN] Skipping array '{key}': {e}")

            # Special handling for spark_status (object array of 3-tuple-like entries)
            if "spark_status" in numpy_data:
                s = numpy_data["spark_status"]
                if s.dtype == object:
                    try:
                        T = int(len(s))
                        state = np.zeros(T, dtype=np.int8)
                        loc_mm = np.full(T, np.nan, dtype=np.float64)
                        extra = np.full(T, np.nan, dtype=np.float64)
                        for i in range(T):
                            item = s[i]
                            if item is None:
                                continue
                            try:
                                if isinstance(item, (list, tuple, np.ndarray)):
                                    if len(item) > 0 and item[0] is not None:
                                        state[i] = int(item[0])
                                    if len(item) > 1 and item[1] is not None:
                                        loc_mm[i] = float(item[1])
                                    if len(item) > 2 and item[2] is not None:
                                        extra[i] = float(item[2])
                            except Exception:
                                pass
                        add_numpy_to_zip(zf, "spark_status_state", state)
                        add_numpy_to_zip(zf, "spark_status_location_mm", loc_mm)
                        add_numpy_to_zip(zf, "spark_status_extra", extra)
                    except Exception as e:
                        print(f"[WARN] Failed to decompose 'spark_status': {e}")

            # Write header.json last
            header = {
                "format": "sparc_pack_v1",
                "arrays": arrays_manifest,
                "metadata": metadata,
            }
            zf.writestr("header.json", json.dumps(header))

        file_size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"Logged data saved to {output_path} ({file_size_mb:.2f} MB) [sparc_pack_v1 format]")

    def get_data(self) -> Dict[str, List[Any]] | str | None:
        """
        Retrieves the logged data or its location.

        Returns:
            - A dictionary (signal -> list of values) if backend is "memory".
            - A string (filepath) if backend is "numpy" or "json" and successful.
            - None otherwise or if data hasn't been finalized for file backends.
        """
        if self.config["backend"]["type"] == "memory":
            return self.log_data
        elif self.config["backend"]["type"] in ["numpy", "json"]:
            # Return the filepath, assuming finalize has been called.
            # User is responsible for loading the file.
            return self.config["backend"].get("filepath")
        return None

    def reset(self):
        """
        Resets the logger's internal state for a new episode.
        """
        self.log_data = defaultdict(list)
        self.step_counter = 0
