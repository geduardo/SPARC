from __future__ import annotations
"""Phase-1 servo-control Gym env built on top of the low-level simulator."""

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from ...core.env_config import EnvironmentConfig
from ...envs.wire_edm import WireEDMSimulator, build_scalar_action
from ...modules.dielectric import DielectricModuleParameters
from ...modules.ignition import IgnitionModuleParameters
from ...modules.material import MaterialModuleParameters
from ...modules.mechanics import MechanicsModuleParameters
from ...modules.wire import WireModuleParameters


class ServoControlEnv(gym.Env):
    """Agent-facing env with one public step per simulator control interval.

    The env owns a ``WireEDMSimulator`` internally and turns one external action
    into one full simulator control interval. This keeps the physics at microstep
    resolution while exposing a clean decision cadence to Gym-compatible agents.
    """

    metadata = {"render_modes": []}
    _SCALAR_KEYS = (
        "gap_um",
        "wire_position_um",
        "workpiece_position_um",
        "wire_velocity_um_s",
        "interval_mean_voltage_v",
        "interval_mean_current_a",
        "previous_action",
    )
    _SCALAR_BOUNDS = {
        "gap_um": (-1.0e6, 1.0e6),
        "wire_position_um": (-1.0e6, 1.0e6),
        "workpiece_position_um": (0.0, 1.0e6),
        "wire_velocity_um_s": (-1.0e9, 1.0e9),
        "interval_mean_voltage_v": (0.0, 1.0e3),
        "interval_mean_current_a": (0.0, 1.0e3),
        "previous_action": (-1.0, 1.0),
    }

    def __init__(
        self,
        *,
        render_mode: str | None = None,
        mechanics_control_mode: str = "position",
        config: EnvironmentConfig | None = None,
        ignition_params: IgnitionModuleParameters = None,
        wire_params: WireModuleParameters = None,
        material_params: MaterialModuleParameters = None,
        dielectric_params: DielectricModuleParameters = None,
        mechanics_params: MechanicsModuleParameters = None,
        use_compiled: bool = True,
    ):
        """Build the servo-control task env around one simulator instance."""
        super().__init__()
        self.use_compiled = bool(use_compiled)
        self.simulator = WireEDMSimulator(
            render_mode=render_mode,
            mechanics_control_mode=mechanics_control_mode,
            config=config,
            ignition_params=ignition_params,
            wire_params=wire_params,
            material_params=material_params,
            dielectric_params=dielectric_params,
            mechanics_params=mechanics_params,
        )
        self.control_interval_us = int(self.simulator.servo_interval)

        defaults = self.simulator.get_default_discharge_settings()
        self._fixed_target_voltage = float(defaults["target_voltage"])
        self._fixed_current_mode = int(str(defaults["current_mode"])[1:])
        self._fixed_on_time = float(defaults["ON_time"])
        self._fixed_off_time = float(defaults["OFF_time"])

        self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)
        self.observation_space = spaces.Dict(
            {
                key: spaces.Box(
                    low=np.array([self._SCALAR_BOUNDS[key][0]], dtype=np.float32),
                    high=np.array([self._SCALAR_BOUNDS[key][1]], dtype=np.float32),
                    shape=(1,),
                    dtype=np.float32,
                )
                for key in self._SCALAR_KEYS
            }
        )
        self._last_action = 0.0
        self._last_interval_summary = self._zero_interval_summary()

    def reset(self, *, seed: int | None = None, options=None):
        """Reset the simulator and return the initial task observation/info."""
        super().reset(seed=seed)
        self.simulator.np_random = self.np_random
        self.simulator.reset(seed=None, options=options)
        if self.use_compiled:
            self.simulator.init_compiled_scheduler()
        self._last_action = 0.0
        self._last_interval_summary = self._zero_interval_summary()
        return self._get_obs(), self._build_info()

    def step(self, action):
        """Apply one servo action and advance exactly one control interval."""
        servo_delta = self._coerce_action(action)
        sim_action = build_scalar_action(
            servo=servo_delta,
            target_voltage=self._fixed_target_voltage,
            current_mode=self._fixed_current_mode,
            ON_time=self._fixed_on_time,
            OFF_time=self._fixed_off_time,
        )
        self._last_action = servo_delta
        self._last_interval_summary = self._run_control_interval(sim_action)
        terminated = self.simulator.state.is_wire_broken or self.simulator.state.is_target_distance_reached
        truncated = False
        return (
            self._get_obs(),
            self._calc_reward(),
            terminated,
            truncated,
            self._build_info(),
        )

    def _coerce_action(self, action) -> float:
        """Convert the external action into one clipped scalar servo command."""
        action_array = np.asarray(action, dtype=np.float32).reshape(-1)
        if action_array.size == 0:
            raise ValueError("ServoControlEnv action cannot be empty")
        return float(np.clip(action_array[0], self.action_space.low[0], self.action_space.high[0]))

    def _run_control_interval(self, sim_action) -> dict[str, float | int | bool]:
        """Roll the simulator until the next decision boundary or termination."""
        self._prime_control_boundary()
        interval_microsteps = 0
        charge_c = 0.0
        voltage_sum = 0.0
        current_sum = 0.0
        spark_count = 0
        short_count = 0
        dt_seconds = float(self.simulator.dt) * 1e-6

        while True:
            if self.use_compiled:
                terminated, truncated = self.simulator.step_compiled_fast(sim_action)
                runtime_current = float(self.simulator._hot_state.current)
                runtime_voltage = float(self.simulator._hot_state.voltage)
                runtime_spark_state = int(self.simulator._hot_state.spark_state)
                runtime_spark_duration = int(self.simulator._hot_state.spark_duration)
                interval_complete = (
                    self.simulator._hot_state.time_since_servo >= self.control_interval_us
                )
            else:
                terminated, truncated = self.simulator.step_fast(sim_action)
                runtime_current = float(self.simulator.state.current)
                runtime_voltage = float(self.simulator.state.voltage)
                runtime_spark_state = int(self.simulator.state.spark_status[0])
                runtime_spark_duration = int(self.simulator.state.spark_status[2])
                interval_complete = (
                    self.simulator.state.time_since_servo >= self.control_interval_us
                )

            interval_microsteps += 1
            charge_c += runtime_current * dt_seconds
            voltage_sum += runtime_voltage
            current_sum += runtime_current
            if runtime_spark_state == 1 and runtime_spark_duration == 0:
                spark_count += 1
            if runtime_spark_state == -1 and runtime_spark_duration == 0:
                short_count += 1
            if terminated or truncated or interval_complete:
                break

        if self.use_compiled:
            self.simulator.sync_compiled_to_state()

        duration_us = int(interval_microsteps * self.simulator.dt)
        mean_voltage = 0.0 if interval_microsteps == 0 else voltage_sum / interval_microsteps
        mean_current = 0.0 if interval_microsteps == 0 else current_sum / interval_microsteps
        return {
            "interval_charge": float(charge_c),
            "interval_duration_us": duration_us,
            "interval_mean_current": float(mean_current),
            "interval_mean_voltage": float(mean_voltage),
            "interval_spark_count": int(spark_count),
            "interval_short_count": int(short_count),
            "interval_microsteps": int(interval_microsteps),
        }

    def _prime_control_boundary(self) -> None:
        """Force the next simulator microstep to behave like a control boundary."""
        if self.use_compiled:
            # Rebuild the compiled mirror once per public step so any state edits
            # made outside the simulator loop are reflected before rollout.
            self.simulator._hot_state = self.simulator.build_hot_state_bundle()
            self.simulator._hot_state.time_since_servo = self.control_interval_us
        self.simulator.state.time_since_servo = self.control_interval_us
        if self.use_compiled:
            self.simulator._hot_state.time_since_servo = self.control_interval_us

    def _get_obs(self):
        """Return the current scalar observation for the servo task."""
        gap_um = float(
            self.simulator.state.workpiece_position - self.simulator.state.wire_position
        )
        return {
            "gap_um": np.array([gap_um], dtype=np.float32),
            "wire_position_um": np.array(
                [float(self.simulator.state.wire_position)], dtype=np.float32
            ),
            "workpiece_position_um": np.array(
                [float(self.simulator.state.workpiece_position)], dtype=np.float32
            ),
            "wire_velocity_um_s": np.array(
                [float(self.simulator.state.wire_velocity)], dtype=np.float32
            ),
            "interval_mean_voltage_v": np.array(
                [float(self._last_interval_summary["interval_mean_voltage"])],
                dtype=np.float32,
            ),
            "interval_mean_current_a": np.array(
                [float(self._last_interval_summary["interval_mean_current"])],
                dtype=np.float32,
            ),
            "previous_action": np.array([float(self._last_action)], dtype=np.float32),
        }

    def _calc_reward(self) -> float:
        """Return the default measurable reward for the finished interval."""
        return float(self._last_interval_summary["interval_charge"])

    def _build_info(self) -> dict[str, float | int | bool]:
        """Expose interval summaries and current state for logging/debugging."""
        info = dict(self._last_interval_summary)
        info.update(
            {
            "sim_time_us": int(self.simulator.state.time),
            "control_interval_us": self.control_interval_us,
            "wire_broken": bool(self.simulator.state.is_wire_broken),
            "target_reached": bool(self.simulator.state.is_target_distance_reached),
            "workpiece_position_um": float(self.simulator.state.workpiece_position),
            "wire_position_um": float(self.simulator.state.wire_position),
            "gap_um": float(
                self.simulator.state.workpiece_position - self.simulator.state.wire_position
            ),
            "last_action": float(self._last_action),
            }
        )
        return info

    def _zero_interval_summary(self) -> dict[str, float | int]:
        """Return the zero-valued interval summary used right after reset."""
        return {
            "interval_charge": 0.0,
            "interval_duration_us": 0,
            "interval_mean_current": 0.0,
            "interval_mean_voltage": 0.0,
            "interval_spark_count": 0,
            "interval_short_count": 0,
            "interval_microsteps": 0,
        }
