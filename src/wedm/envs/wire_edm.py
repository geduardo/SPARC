from __future__ import annotations

from dataclasses import dataclass

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from ..core.hot_state import HotStateBundle
from ..core.compiled_step import (
    SchedulerConstants,
    compiled_microstep,
)
from ..core.constants import WIRE_BREAK_POSITION_MARGIN_UM
from ..core.state import EDMState
from ..core.env_config import EnvironmentConfig
from ..modules.dielectric import DielectricModule, DielectricModuleParameters
from ..modules.ignition import IgnitionModule, IgnitionModuleParameters
from ..modules.material import MaterialRemovalModule, MaterialModuleParameters
from ..modules.mechanics import MechanicsModule, MechanicsModuleParameters
from ..modules.wire import WireModule, WireModuleParameters


@dataclass(frozen=True, slots=True)
class ScalarGeneratorControl:
    """Lightweight scalar generator settings."""

    target_voltage: float
    current_mode: int
    ON_time: float
    OFF_time: float


@dataclass(frozen=True, slots=True)
class ScalarAction:
    """Scalar action payload that avoids per-step NumPy indexing overhead."""

    servo: float
    generator_control: ScalarGeneratorControl


@dataclass(frozen=True, slots=True)
class CompiledActionPacket:
    """Resolved control packet for compiled stepping."""

    target_delta: float
    target_voltage: float
    current_mode: int
    on_time: float
    off_time: float
    peak_current: float
    crater_mean_um3: float
    crater_std_um3: float
    kerf_width_mm: float


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
    """Main-cut Wire-EDM environment (1 us base step, 1 ms control step)."""

    metadata = {"render_modes": ["human"], "render_fps": 300}

    def __init__(
        self,
        *,
        render_mode: str | None = None,
        mechanics_control_mode: str = "position",
        config: EnvironmentConfig | None = None,
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
        self._compiled_cached_mode_int = None
        self._compiled_action_source = None
        self._compiled_action_packet = None

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

    def _decode_action(self, action) -> tuple[float, float, int, float, float]:
        if isinstance(action, ScalarAction):
            gc = action.generator_control
            return (
                action.servo,
                gc.target_voltage,
                gc.current_mode,
                gc.ON_time,
                gc.OFF_time,
            )

        gc = action["generator_control"]
        return (
            float(action["servo"][0]),
            float(gc["target_voltage"][0]),
            int(gc["current_mode"][0]),
            float(gc["ON_time"][0]),
            float(gc["OFF_time"][0]),
        )

    def _resolve_mode_str(self, mode_int: int) -> str:
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
        return mode_str

    def _update_compiled_mode_cache(self, mode_int: int) -> None:
        if mode_int == self._compiled_cached_mode_int:
            return

        mode_str = self._resolve_mode_str(mode_int)
        crater_info = self.material.crater_data[mode_str]
        crater_depth_mm = crater_info["depth_um"] / 1000.0

        self._compiled_peak_current = self.ignition._get_current_from_mode(mode_str)
        self._compiled_crater_mean = crater_info["volume_um3"]
        self._compiled_crater_std = crater_info["volume_std_um3"]
        self._compiled_kerf_width_mm = (
            self.material.params.base_overcut
            + self.config.wire_diameter
            + crater_depth_mm
        )
        self._compiled_cached_mode_int = mode_int

    def _build_compiled_action_packet(
        self,
        target_delta: float,
        target_voltage: float,
        mode_int: int,
        on_time: float,
        off_time: float,
    ) -> CompiledActionPacket:
        self._update_compiled_mode_cache(mode_int)
        return CompiledActionPacket(
            target_delta=target_delta,
            target_voltage=target_voltage,
            current_mode=mode_int,
            on_time=on_time,
            off_time=off_time,
            peak_current=self._compiled_peak_current,
            crater_mean_um3=self._compiled_crater_mean,
            crater_std_um3=self._compiled_crater_std,
            kerf_width_mm=self._compiled_kerf_width_mm,
        )

    def _resolve_compiled_action_packet(self, action) -> CompiledActionPacket:
        if isinstance(action, CompiledActionPacket):
            return action

        if isinstance(action, ScalarAction) and action is self._compiled_action_source:
            return self._compiled_action_packet

        target_delta, target_voltage, mode_int, on_time, off_time = self._decode_action(
            action
        )
        packet = self._build_compiled_action_packet(
            target_delta, target_voltage, mode_int, on_time, off_time
        )

        if isinstance(action, ScalarAction):
            self._compiled_action_source = action
            self._compiled_action_packet = packet

        return packet

    def _step_impl(self, action, *, fast: bool):
        state = self.state
        is_ctrl_step = state.time_since_servo >= self.servo_interval

        if is_ctrl_step:
            self._apply_action(action)
            state.time_since_servo = 0

        # physics advance 1 µs
        self.ignition.update(state)
        self.material.update(state)
        self.dielectric.update(state)
        self.wire.update(state)

        if state.is_wire_broken:
            if fast:
                return True, False
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

        terminated = self._check_termination()

        if fast:
            return terminated, False

        if is_ctrl_step:
            obs = self._get_obs()
            reward = self._calc_reward()
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

    def step(self, action):
        return self._step_impl(action, fast=False)

    def step_fast(self, action) -> tuple[bool, bool]:
        return self._step_impl(action, fast=True)

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
        target_delta, target_voltage, mode_int, on_time, off_time = self._decode_action(
            action
        )
        self.state.target_delta = target_delta
        self.state.target_voltage = target_voltage
        self.state.ON_time = on_time
        self.state.OFF_time = off_time
        self.state.current_mode = self._resolve_mode_str(mode_int)

    def _check_termination(self) -> bool:
        if (
            self.state.wire_position
            > self.state.workpiece_position + WIRE_BREAK_POSITION_MARGIN_UM
        ):
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

    def build_hot_state_bundle(self) -> HotStateBundle:
        """Capture the scheduler state bundle from the current environment."""
        return HotStateBundle.from_env(self)

    def apply_hot_state_bundle(self, hot_state: HotStateBundle) -> None:
        """Restore environment and module state from a scheduler bundle."""
        hot_state.apply_to_env(self)

    # ------------------------------------------------------------------ #
    # Compiled scheduler path
    # ------------------------------------------------------------------ #
    def init_compiled_scheduler(self) -> None:
        """Prepare the compiled scheduler for repeated stepping.

        Must be called after reset() and before step_compiled().
        Captures all module constants into a frozen snapshot.
        """
        self._scheduler_constants = SchedulerConstants.from_env(self)
        self._hot_state = self.build_hot_state_bundle()
        self._compiled_cached_mode_int = None
        self._compiled_action_source = None
        self._compiled_action_packet = None
        self._resolve_compiled_generator_settings()
        self._resolve_compiled_crater_params()

    def compile_action(self, action) -> CompiledActionPacket:
        """Resolve an action into a compiled control packet."""
        return self._resolve_compiled_action_packet(action)

    def _resolve_compiled_generator_settings(self) -> None:
        """Cache generator settings used by compiled stepping."""
        state = self.state
        ign = self.ignition
        tv = state.target_voltage
        self._compiled_target_voltage = (
            tv if tv is not None else ign.params.default_target_voltage
        )
        on = state.ON_time
        self._compiled_on_time = (
            on if on is not None else ign.params.default_on_time
        )
        off = state.OFF_time
        self._compiled_off_time = (
            off if off is not None else ign.params.default_off_time
        )
        mode = self.resolve_current_mode(state.current_mode)
        self._update_compiled_mode_cache(int(mode[1:]))

    def _resolve_compiled_crater_params(self) -> None:
        """Cache crater sampling parameters used by compiled stepping."""
        mode = self.resolve_current_mode(self.state.current_mode)
        self._update_compiled_mode_cache(int(mode[1:]))

    def _step_compiled_impl(self, action, *, fast: bool):
        """Advance one microstep using the compiled scheduler.

        Eliminates per-microstep Python module dispatch. RNG stays in
        Python for branch-consumption parity with the modular path.

        Public `step_compiled()` preserves the Gym-style return tuple.
        `step_compiled_fast()` returns only termination flags for
        tight stepping loops.
        """
        hs = self._hot_state
        sc = self._scheduler_constants
        is_ctrl_step = hs.time_since_servo >= sc.servo_interval

        if is_ctrl_step:
            packet = self._resolve_compiled_action_packet(action)

            hs.target_delta = packet.target_delta
            hs.target_voltage = packet.target_voltage
            hs.current_mode_code = packet.current_mode
            hs.on_time_us = packet.on_time
            hs.off_time_us = packet.off_time
            self._compiled_target_voltage = packet.target_voltage
            self._compiled_on_time = packet.on_time
            self._compiled_off_time = packet.off_time
            self._compiled_peak_current = packet.peak_current
            self._compiled_crater_mean = packet.crater_mean_um3
            self._compiled_crater_std = packet.crater_std_um3
            self._compiled_kerf_width_mm = packet.kerf_width_mm
            self._compiled_cached_mode_int = packet.current_mode

            hs.time_since_servo = 0

        termination_code = compiled_microstep(
            hs, self.np_random, sc,
            self._compiled_target_voltage,
            self._compiled_peak_current,
            self._compiled_on_time,
            self._compiled_off_time,
            self._compiled_crater_mean,
            self._compiled_crater_std,
            self._compiled_kerf_width_mm,
        )

        if fast:
            return termination_code != 0, False

        self.sync_compiled_to_state()
        terminated = bool(termination_code != 0 or self._check_termination())

        if is_ctrl_step:
            obs = self._get_obs()
            reward = self._calc_reward()
        else:
            obs = None
            reward = 0.0

        info = {
            "wire_broken": self.state.is_wire_broken,
            "target_reached": self.state.is_target_distance_reached,
            "spark_state": int(self.state.spark_status[0]),
            "time": self.state.time,
            "control_step": is_ctrl_step,
        }
        return obs, reward, terminated, False, info

    def step_compiled(self, action) -> tuple:
        """Advance one compiled microstep and return the Gym-style tuple."""
        return self._step_compiled_impl(action, fast=False)

    def step_compiled_fast(self, action) -> tuple[bool, bool]:
        """Advance one compiled microstep and return termination flags only."""
        return self._step_compiled_impl(action, fast=True)

    def sync_compiled_to_state(self) -> None:
        """Write the scheduler bundle back into EDMState and module internals.

        Call this when you need the environment state to reflect compiled
        progress (e.g., for logging, dashboards, or episode end).
        """
        self._hot_state.apply_to_env(self)

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
