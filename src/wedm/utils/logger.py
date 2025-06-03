from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, List, Literal, TypedDict, Union
import pathlib  # Added for path manipulation
import numpy as np  # Added for numpy backend

if TYPE_CHECKING:
    from ..core.state import EDMState
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


# We'll add more backends like numpy, csv, hdf5 later
BackendConfig = Union[BackendMemory, BackendNumpy]  # Added BackendNumpy


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

        # Placeholder for more complex signal definitions (e.g., derived values)
        # For now, signals are assumed to be direct attributes of EDMState
        self.signal_accessors: Dict[str, callable] = {}
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
        if backend_type not in ["memory", "numpy"]:
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

    def _prepare_signal_accessors(self):
        """
        Prepares functions to access signal data.
        For now, assumes direct attribute access on EDMState.
        Can be extended for derived signals or specific array indexing.
        """
        for signal_name in self.config["signals_to_log"]:
            # Example: if signal_name is "wire_temp_segment_0", we might parse it
            # and create a lambda like: lambda state: state.wire_temperature[0]
            # For now, direct access:
            self.signal_accessors[signal_name] = (
                lambda state, name=signal_name: getattr(state, name, None)
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
                    processed_value = (
                        value.copy() if isinstance(value, np.ndarray) else value
                    )

                    if self.config["backend"]["type"] == "memory":
                        self.log_data[signal_name].append(processed_value)
                    elif self.config["backend"]["type"] == "numpy":
                        # For numpy, we also append to lists first, convert to np.array in finalize
                        self.log_data[signal_name].append(processed_value)
                    else:
                        # Logic for other backends would go here
                        pass
                else:
                    # Optionally log a warning if an accessor isn't found
                    print(
                        f"Warning: No accessor found for signal '{signal_name}'. Skipping."
                    )

    def finalize(self):
        """
        Finalizes logging. For memory backend, this might not do much.
        For file backends, this is where data is flushed to disk.
        """
        if self.config["backend"]["type"] == "memory":
            # print("Memory logger finalized. Data available via get_data().")
            pass
        elif self.config["backend"]["type"] == "numpy":
            filepath_str = self.config["backend"]["filepath"]
            should_compress = self.config["backend"].get("compress", False)

            if not self.log_data:
                print("No data collected, skipping .npz file creation.")
                return

            # Convert lists to numpy arrays
            numpy_data = {}
            for signal_name, data_list in self.log_data.items():
                try:
                    # Attempt to convert, ensuring all elements can form a consistent NumPy array
                    # This is crucial if logged values are, e.g., mixed types or variable-length arrays themselves
                    # For simple scalar series, this is usually fine.
                    # If a signal itself is a list/array per step, np.array(data_list) creates an object array if ragged,
                    # or a 2D+ array if consistent.
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

            try:
                if should_compress:
                    np.savez_compressed(output_path, **numpy_data)
                else:
                    np.savez(output_path, **numpy_data)
                print(f"Logged data saved to {output_path}")
            except Exception as e:
                print(f"Error saving data to {output_path}: {e}")

    def get_data(self) -> Dict[str, List[Any]] | str | None:
        """
        Retrieves the logged data or its location.

        Returns:
            - A dictionary (signal -> list of values) if backend is "memory".
            - A string (filepath) if backend is "numpy" and successful.
            - None otherwise or if data hasn't been finalized for file backends.
        """
        if self.config["backend"]["type"] == "memory":
            return self.log_data
        elif self.config["backend"]["type"] == "numpy":
            # Return the filepath, assuming finalize has been called.
            # User is responsible for loading the .npz file.
            return self.config["backend"].get("filepath")
        return None

    def reset(self):
        """
        Resets the logger's internal state for a new episode.
        """
        self.log_data = defaultdict(list)
        self.step_counter = 0


# Example Usage (conceptual, would be in simulation script):
# if __name__ == "__main__":
#     # Dummy EDMState and WireEDMEnv for illustration
#     class DummyEDMState:
#         def __init__(self):
#             self.time = 0
#             self.voltage = 0.0
#             self.wire_average_temperature = 293.15

#     class DummyWireEDMEnv:
#         pass

#     dummy_env = DummyWireEDMEnv()
#     current_state = DummyEDMState()

#     logger_config: LoggerConfig = {
#         "signals_to_log": ["time", "voltage", "wire_average_temperature"],
#         "log_frequency": {"type": "interval", "value": 2},
#         "backend": {"type": "memory"}
#     }
#     logger = SimulationLogger(config=logger_config, env_reference=dummy_env)

#     for i in range(10):
#         current_state.time = i
#         current_state.voltage = float(i * 10)
#         current_state.wire_average_temperature = 293.15 + i

#         # Simulate info dict
#         sim_info = {"control_step": i % 5 == 0} if logger_config["log_frequency"]["type"] == "control_step" else {}

#         logger.collect(current_state, sim_info)

#     logger.finalize()
#     collected_data = logger.get_data()
#     if collected_data:
#         for signal, values in collected_data.items():
#             print(f"{signal}: {values}")
