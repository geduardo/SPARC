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
        self.observation_space = spaces.Dict({})
        self._last_action = 0.0

    def reset(self, *, seed: int | None = None, options=None):
        """Reset the simulator and return the initial task observation/info."""
        self.simulator.reset(seed=seed, options=options)
        if self.use_compiled:
            self.simulator.init_compiled_scheduler()
        self._last_action = 0.0
        return self._get_obs(), self._build_info(interval_microsteps=0)

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
        interval_microsteps = self._run_control_interval(sim_action)
        terminated = self.simulator.state.is_wire_broken or self.simulator.state.is_target_distance_reached
        truncated = False
        return (
            self._get_obs(),
            self._calc_reward(),
            terminated,
            truncated,
            self._build_info(interval_microsteps=interval_microsteps),
        )

    def _coerce_action(self, action) -> float:
        """Convert the external action into one clipped scalar servo command."""
        action_array = np.asarray(action, dtype=np.float32).reshape(-1)
        if action_array.size == 0:
            raise ValueError("ServoControlEnv action cannot be empty")
        return float(np.clip(action_array[0], self.action_space.low[0], self.action_space.high[0]))

    def _run_control_interval(self, sim_action) -> int:
        """Roll the simulator until the next decision boundary or termination."""
        self._prime_control_boundary()
        interval_microsteps = 0

        while True:
            if self.use_compiled:
                terminated, truncated = self.simulator.step_compiled_fast(sim_action)
                interval_complete = (
                    self.simulator._hot_state.time_since_servo >= self.control_interval_us
                )
            else:
                terminated, truncated = self.simulator.step_fast(sim_action)
                interval_complete = (
                    self.simulator.state.time_since_servo >= self.control_interval_us
                )

            interval_microsteps += 1
            if terminated or truncated or interval_complete:
                break

        if self.use_compiled:
            self.simulator.sync_compiled_to_state()

        return interval_microsteps

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
        """Return the current task observation placeholder."""
        return {}

    def _calc_reward(self) -> float:
        """Return the current task reward placeholder."""
        return 0.0

    def _build_info(self, *, interval_microsteps: int) -> dict[str, float | int | bool]:
        """Expose minimal interval bookkeeping for debugging and later extensions."""
        return {
            "sim_time_us": int(self.simulator.state.time),
            "control_interval_us": self.control_interval_us,
            "interval_microsteps": int(interval_microsteps),
            "wire_broken": bool(self.simulator.state.is_wire_broken),
            "target_reached": bool(self.simulator.state.is_target_distance_reached),
            "last_action": float(self._last_action),
        }
