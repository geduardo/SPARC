# src/edm_env/envs/wire_edm.py
from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class ScalarGeneratorControl:
    """Scalar generator settings for the env fast path."""

    target_voltage: float
    current_mode: int
    ON_time: float
    OFF_time: float


@dataclass(frozen=True, slots=True)
class ScalarAction:
    """Scalar action payload that avoids per-step NumPy indexing overhead."""

    servo: float
    generator_control: ScalarGeneratorControl


def build_scalar_action(
    *,
    servo: float,
    target_voltage: float,
    current_mode: int,
    ON_time: float,
    OFF_time: float,
) -> ScalarAction:
    """Build a scalar action payload for repeated env stepping."""
    return ScalarAction(
        servo=float(servo),
        generator_control=ScalarGeneratorControl(
            target_voltage=float(target_voltage),
            current_mode=int(current_mode),
            ON_time=float(ON_time),
            OFF_time=float(OFF_time),
        ),
    )


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

        # Valid current modes — only modes with empirical crater data
        self.valid_current_modes = set(self.material.crater_data.keys())
        if self.ignition.params.default_current_mode not in self.valid_current_modes:
            raise ValueError(
                "ignition default_current_mode must have crater data. "
                f"Got {self.ignition.params.default_current_mode}, "
                f"valid modes: {sorted(self.valid_current_modes, key=lambda m: int(m[1:]))}"
            )
        self._valid_modes_sorted = sorted(
            self.valid_current_modes, key=lambda m: int(m[1:])
        )
        self._mode_int_lut = tuple(
            f"I{mode_int}" if f"I{mode_int}" in self.valid_current_modes else ""
            for mode_int in range(20)
        )
        env_type = type(self)
        self._uses_default_apply_action = (
            env_type._apply_action is WireEDMEnv._apply_action
        )
        self._uses_default_check_termination = (
            env_type._check_termination is WireEDMEnv._check_termination
        )
        self._uses_default_get_obs = env_type._get_obs is WireEDMEnv._get_obs
        self._uses_default_calc_reward = (
            env_type._calc_reward is WireEDMEnv._calc_reward
        )

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
        for module in self.modules.values():
            module.reset(self.state)
        self._apply_episode_start_defaults()

        return self._get_obs(), {}

    def step(self, action):
        state = self.state
        is_ctrl_step = state.time_since_servo >= self.servo_interval

        if is_ctrl_step:
            if self._uses_default_apply_action:
                if isinstance(action, ScalarAction):
                    state.target_delta = action.servo
                    gc = action.generator_control
                    state.target_voltage = gc.target_voltage
                    mode_int = gc.current_mode
                    state.ON_time = gc.ON_time
                    state.OFF_time = gc.OFF_time
                else:
                    state.target_delta = float(action["servo"][0])
                    gc = action["generator_control"]
                    state.target_voltage = float(gc["target_voltage"][0])
                    mode_int = int(gc["current_mode"][0])
                    state.ON_time = float(gc["ON_time"][0])
                    state.OFF_time = float(gc["OFF_time"][0])
                mode_str = (
                    self._mode_int_lut[mode_int]
                    if 0 <= mode_int < len(self._mode_int_lut)
                    else ""
                )
                if not mode_str:
                    raise ValueError(
                        f"current_mode {mode_int} ('I{mode_int}') has no crater data. "
                        f"Valid modes: {self._valid_modes_sorted}"
                    )
                state.current_mode = mode_str
            else:
                self._apply_action(action)
            state.time_since_servo = 0

        # physics advance 1 µs
        self.ignition.update(state)
        self.material.update(state)
        self.dielectric.update(state)
        self.wire.update(state)

        if state.is_wire_broken:
            return None, 0.0, True, False, {"wire_broken": True}

        self.mechanics.update(state)

        # time bookkeeping
        dt = self.dt
        state.time += dt
        state.time_since_servo += dt
        state.time_since_open_voltage += dt

        if state.spark_status[0] == 1:
            state.time_since_spark_ignition += dt
            state.time_since_spark_end = 0
        else:
            state.time_since_spark_end += dt
            state.time_since_spark_ignition = 0

        if self._uses_default_check_termination:
            terminated = False
            if state.wire_position > state.workpiece_position + 100:
                state.is_wire_broken = True
                terminated = True
            elif state.workpiece_position >= state.target_position:
                state.is_target_distance_reached = True
                terminated = True
        else:
            terminated = self._check_termination()

        if is_ctrl_step:
            obs = {} if self._uses_default_get_obs else self._get_obs()
            reward = 0.0 if self._uses_default_calc_reward else self._calc_reward()
        else:
            obs = None
            reward = 0.0

        info = {
            "wire_broken": state.is_wire_broken,
            "target_reached": state.is_target_distance_reached,
            "spark_state": int(state.spark_status[0]),
            "time": state.time,
            "control_step": is_ctrl_step,
        }
        return obs, reward, terminated, False, info

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @property
    def default_current_mode(self) -> str:
        """Crater-backed default discharge mode shared across modules."""
        return self.ignition.params.default_current_mode

    def get_default_discharge_settings(self) -> dict[str, float | str]:
        """Return the shared startup and fallback generator defaults."""
        return {
            "target_voltage": self.ignition.params.default_target_voltage,
            "current_mode": self.default_current_mode,
            "ON_time": self.ignition.params.default_on_time,
            "OFF_time": self.ignition.params.default_off_time,
        }

    def resolve_current_mode(self, current_mode: str | None) -> str:
        """Normalize to a crater-backed current mode for physics fallbacks."""
        if current_mode in self.valid_current_modes:
            return current_mode
        return self.default_current_mode

    def _apply_episode_start_defaults(self) -> None:
        """Populate state with explicit startup defaults for a new episode."""
        defaults = self.get_default_discharge_settings()

        self.state.workpiece_position = self.config.initial_gap
        self.state.target_position = self.config.target_cutting_distance
        self.state.spark_status = [0, None, 0]

        self.state.target_voltage = float(defaults["target_voltage"])
        self.state.current_mode = str(defaults["current_mode"])
        self.state.ON_time = float(defaults["ON_time"])
        self.state.OFF_time = float(defaults["OFF_time"])

        self.state.voltage = self.state.target_voltage
        self.state.current = 0.0
        self.state.dielectric_temperature = self.dielectric.params.dielectric_temperature

    def _apply_action(self, action):
        if isinstance(action, ScalarAction):
            self.state.target_delta = action.servo
            gc = action.generator_control
            self.state.target_voltage = gc.target_voltage
            mode_int = gc.current_mode
            self.state.ON_time = gc.ON_time
            self.state.OFF_time = gc.OFF_time
        else:
            self.state.target_delta = float(action["servo"][0])
            gc = action["generator_control"]
            self.state.target_voltage = float(gc["target_voltage"][0])
            mode_int = int(gc["current_mode"][0])
            self.state.ON_time = float(gc["ON_time"][0])
            self.state.OFF_time = float(gc["OFF_time"][0])
        # Convert integer mode (1-19) to I-mode string and validate
        mode_str = (
            self._mode_int_lut[mode_int]
            if 0 <= mode_int < len(self._mode_int_lut)
            else ""
        )
        if not mode_str:
            raise ValueError(
                f"current_mode {mode_int} ('I{mode_int}') has no crater data. "
                f"Valid modes: {self._valid_modes_sorted}"
            )
        self.state.current_mode = mode_str

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
