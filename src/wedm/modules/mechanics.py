# src/edm_env/modules/mechanics.py
from __future__ import annotations

from dataclasses import dataclass
from ..core.module import EDMModule
from ..core.state import EDMState


# ──────────────────────────────────────────────────────────────────────────────
# Mechanics Module Parameters - Defined within module
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class MechanicsModuleParameters:
    """Mechanics module specific parameters."""

    # ── Control System Parameters ──
    omega_n: float = 235.0  # [rad/s] Natural frequency
    zeta: float = 0.38  # [dimensionless] Damping ratio (only used for position control)

    # ── Physical Limits ──
    max_acceleration: float = 3.0e5  # [µm/s²] Maximum acceleration
    max_jerk: float = 1.0e8  # [µm/s³] Maximum jerk
    max_speed: float = 3.0e4  # [µm/s] Maximum speed


class MechanicsModule(EDMModule):
    """Optimized servo axis with configurable position or velocity control modes."""

    def __init__(
        self,
        env,
        control_mode: str = "position",
        parameters: MechanicsModuleParameters = None,
    ):
        super().__init__(env)

        # Validate control mode
        if control_mode not in ["position", "velocity"]:
            raise ValueError(
                f"control_mode must be 'position' or 'velocity', got {control_mode}"
            )

        self.control_mode = control_mode

        # ── Module Parameters ──
        self.params = parameters or MechanicsModuleParameters()

        # ── Pre-compute Constants for Performance ──
        self.dt = env.config.dt * 1e-6  # Pre-compute dt conversion from µs to s

        # Pre-compute control law constants
        if self.control_mode == "position":
            self.damping_coeff = -2.0 * self.params.zeta * self.params.omega_n
            self.stiffness_coeff = -(self.params.omega_n**2)

        # Pre-compute jerk limiting
        self.max_jerk_dt = self.params.max_jerk * self.dt  # Pre-compute for performance

        # ── Internal State ──
        self.prev_accel = 0.0

        # ── Method Dispatch Setup ──
        # Set up control law computation during init for efficiency
        if self.control_mode == "position":
            self._compute_nominal_accel = self._compute_position_accel
        else:  # velocity
            self._compute_nominal_accel = self._compute_velocity_accel

    def _compute_position_accel(self, state: EDMState, x: float, v: float) -> float:
        """Optimized position control using pre-computed coefficients."""
        x_error = x - (x + state.target_delta)  # x - x_target
        return self.damping_coeff * v + self.stiffness_coeff * x_error

    def _compute_velocity_accel(self, state: EDMState, x: float, v: float) -> float:
        """Optimized velocity control."""
        v_error = v - state.target_delta
        return -self.params.omega_n * v_error

    def update(self, state: EDMState) -> None:
        x = state.wire_position
        v = state.wire_velocity

        # Compute nominal acceleration using dispatched method
        a_nom = self._compute_nominal_accel(state, x, v)

        # Scalar clipping (faster than numpy for single values)
        if a_nom > self.params.max_acceleration:
            a_nom = self.params.max_acceleration
        elif a_nom < -self.params.max_acceleration:
            a_nom = -self.params.max_acceleration

        # Jerk limiting with scalar operations
        da = a_nom - self.prev_accel
        if da > self.max_jerk_dt:
            da = self.max_jerk_dt
        elif da < -self.max_jerk_dt:
            da = -self.max_jerk_dt

        a = self.prev_accel + da
        self.prev_accel = a

        # Update velocity with scalar clipping
        v += a * self.dt
        if v > self.params.max_speed:
            v = self.params.max_speed
        elif v < -self.params.max_speed:
            v = -self.params.max_speed

        # Update position
        x += v * self.dt

        # Update state
        state.wire_velocity = v
        state.wire_position = x
