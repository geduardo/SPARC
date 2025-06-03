# src/edm_env/envs/wire_edm.py
from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from ..core.state import EDMState
from ..core.env_config import EnvironmentConfig
from ..modules.dielectric import DielectricModule, DielectricModuleParameters
from ..modules.ignition import IgnitionModule, IgnitionModuleParameters
from ..modules.material import MaterialRemovalModule, MaterialModuleParameters
from ..modules.mechanics import MechanicsModule, MechanicsModuleParameters
from ..modules.wire import WireModule, WireModuleParameters


class WireEDMEnv(gym.Env):
    """Main-cut Wire-EDM environment (1 µs base-step, 1 ms control-step)."""

    metadata = {"render_modes": ["human"], "render_fps": 300}

    def __init__(
        self,
        *,
        render_mode: str | None = None,
        mechanics_control_mode: str = "position",
        config: EnvironmentConfig = None,
        # Module parameter overrides
        ignition_params: IgnitionModuleParameters = None,
        wire_params: WireModuleParameters = None,
        material_params: MaterialModuleParameters = None,
        dielectric_params: DielectricModuleParameters = None,
        mechanics_params: MechanicsModuleParameters = None,
    ):
        super().__init__()
        self.render_mode = render_mode

        # Validate mechanics control mode
        if mechanics_control_mode not in ["position", "velocity"]:
            raise ValueError(
                f"mechanics_control_mode must be 'position' or 'velocity', got {mechanics_control_mode}"
            )

        self.mechanics_control_mode = mechanics_control_mode

        # ── Environment Configuration ───────────────────────────────────
        self.config = config or EnvironmentConfig()
        self.config.validate()  # Validate configuration

        # ── Simulation Parameters ───────────────────────────────────────
        self.dt = self.config.dt  # µs
        self.servo_interval = self.config.servo_interval

        # ── RNG ─────────────────────────────────────────────────────────
        self.np_random = np.random.default_rng()

        # ── Global State ────────────────────────────────────────────────
        self.state = EDMState()

        # ── Initialize Modules with Parameters ──────────────────────────
        # All modules now use the new parameter organization structure

        self.ignition = IgnitionModule(self, ignition_params)
        self.wire = WireModule(self, wire_params)
        self.material = MaterialRemovalModule(self, material_params)
        self.dielectric = DielectricModule(self, dielectric_params)
        self.mechanics = MechanicsModule(
            self, control_mode=mechanics_control_mode, parameters=mechanics_params
        )

        # Store module references for easy access
        self.modules = {
            "ignition": self.ignition,
            "material": self.material,
            "dielectric": self.dielectric,
            "wire": self.wire,
            "mechanics": self.mechanics,
        }

        # ── Action Space ─────────────────────────────────────────────────
        # Note: target_delta interpretation depends on control mode:
        # - position: relative position increment [µm]
        # - velocity: target velocity [µm/s]
        self.action_space = spaces.Dict(
            {
                "servo": spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32),
                "generator_control": spaces.Dict(
                    {
                        "target_voltage": spaces.Box(0.0, 200.0, (1,), np.float32),
                        "current_mode": spaces.Box(
                            1, 19, (1,), dtype=np.int32
                        ),  # I1 to I19 (1-19 maps directly to I1-I19)
                        "ON_time": spaces.Box(0.0, 5.0, (1,), np.float32),
                        "OFF_time": spaces.Box(0.0, 100.0, (1,), np.float32),
                    }
                ),
            }
        )

        # observation space placeholder (define as needed)
        self.observation_space = spaces.Dict({})

    # --------------------------------------------------------------------- #
    # Gym API
    # --------------------------------------------------------------------- #
    def reset(self, *, seed: int | None = None, options=None):
        super().reset(seed=seed)

        # Reset state with proper initial conditions from config
        self.state = EDMState()
        self.state.workpiece_position = self.config.initial_gap
        self.state.target_position = self.config.target_cutting_distance

        return self._get_obs(), {}

    def step(self, action):
        is_ctrl_step = self.state.time_since_servo >= self.servo_interval

        if is_ctrl_step:
            self._apply_action(action)
            self.state.time_since_servo = 0

        # physics advance 1 µs
        self.ignition.update(self.state)
        self.material.update(self.state)
        self.dielectric.update(self.state)
        self.wire.update(self.state)

        if self.state.is_wire_broken:
            return None, 0.0, True, False, {"wire_broken": True}

        self.mechanics.update(self.state)

        # time bookkeeping
        self.state.time += self.dt
        self.state.time_since_servo += self.dt
        self.state.time_since_open_voltage += self.dt

        if self.state.spark_status[0] == 1:
            self.state.time_since_spark_ignition += self.dt
            self.state.time_since_spark_end = 0
        else:
            self.state.time_since_spark_end += self.dt
            self.state.time_since_spark_ignition = 0

        terminated = self._check_termination()
        obs = self._get_obs() if is_ctrl_step else None
        reward = self._calc_reward() if is_ctrl_step else 0.0

        info = {
            "wire_broken": self.state.is_wire_broken,
            "target_reached": self.state.is_target_distance_reached,
            "spark_state": int(self.state.spark_status[0]),
            "time": self.state.time,
            "control_step": is_ctrl_step,
        }
        return obs, reward, terminated, False, info

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _apply_action(self, action):
        self.state.target_delta = float(action["servo"][0])
        gc = action["generator_control"]
        self.state.target_voltage = float(gc["target_voltage"][0])
        # Convert integer mode (1-19) to I-mode string ("I1"-"I19")
        mode_int = int(gc["current_mode"][0])
        self.state.current_mode = f"I{mode_int}"
        self.state.ON_time = float(gc["ON_time"][0])
        self.state.OFF_time = float(gc["OFF_time"][0])

    def _check_termination(self) -> bool:
        if self.state.wire_position > self.state.workpiece_position + 100:
            self.state.is_wire_broken = True
            return True
        if self.state.workpiece_position >= self.state.target_position:
            self.state.is_target_distance_reached = True
            return True
        return False

    def _get_obs(self):
        # TODO: design vector/Dict obs
        return {}

    def _calc_reward(self):
        # TODO: implement proper reward
        return 0.0

    # ------------------------------------------------------------------ #
    # Configuration and Material Access
    # ------------------------------------------------------------------ #
    @property
    def workpiece_height(self) -> float:
        """Legacy property access for workpiece height."""
        return self.config.workpiece_height

    @property
    def wire_diameter(self) -> float:
        """Legacy property access for wire diameter."""
        return self.config.wire_diameter
