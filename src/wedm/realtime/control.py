from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock
from typing import TYPE_CHECKING, Literal, Sequence

import numpy as np

from ..envs.wire_edm import ScalarAction, build_scalar_action

if TYPE_CHECKING:
    from ..envs.wire_edm import WireEDMEnv


ControllerType = Literal["gap", "voltage", "fixed-servo"]

_LIVE_GENERATOR_FIELDS = {"generator_voltage", "current_mode", "off_time"}
_LIVE_SETPOINT_FIELDS = {
    "gap": {"target_gap"},
    "voltage": {"target_avg_voltage"},
    "fixed-servo": {"fixed_servo"},
}


@dataclass(frozen=True, slots=True)
class RuntimeControlSnapshot:
    """Immutable view of the runtime-adjustable control inputs."""

    controller_type: ControllerType
    target_gap: float
    target_avg_voltage: float
    fixed_servo: float
    generator_voltage: float
    current_mode: int
    on_time: float
    off_time: float


class RuntimeControlState:
    """Thread-safe mutable state for live-adjustable controller inputs."""

    def __init__(
        self,
        *,
        controller_type: ControllerType = "gap",
        target_gap: float = 5.0,
        target_avg_voltage: float = 30.0,
        fixed_servo: float = 0.25,
        generator_voltage: float = 80.0,
        current_mode: int = 7,
        on_time: float = 2.0,
        off_time: float = 33.0,
    ) -> None:
        self._lock = RLock()
        self._snapshot = RuntimeControlSnapshot(
            controller_type=controller_type,
            target_gap=float(target_gap),
            target_avg_voltage=float(target_avg_voltage),
            fixed_servo=float(fixed_servo),
            generator_voltage=float(generator_voltage),
            current_mode=int(current_mode),
            on_time=float(on_time),
            off_time=float(off_time),
        )
        self._validate_snapshot(self._snapshot)

    @property
    def controller_type(self) -> ControllerType:
        return self.snapshot().controller_type

    def snapshot(self) -> RuntimeControlSnapshot:
        with self._lock:
            return self._snapshot

    def update(self, **kwargs: float | int | str) -> RuntimeControlSnapshot:
        """Apply validated updates and return the new immutable snapshot."""
        with self._lock:
            if not kwargs:
                return self._snapshot

            normalized = dict(kwargs)
            if "controller_type" in normalized:
                normalized["controller_type"] = str(normalized["controller_type"])

            for field_name in ("target_gap", "target_avg_voltage", "fixed_servo", "generator_voltage", "on_time", "off_time"):
                if field_name in normalized:
                    normalized[field_name] = float(normalized[field_name])

            if "current_mode" in normalized:
                normalized["current_mode"] = int(normalized["current_mode"])

            next_snapshot = replace(self._snapshot, **normalized)
            self._validate_snapshot(next_snapshot)
            self._snapshot = next_snapshot
            return next_snapshot

    def set_param(self, name: str, value: float | int | str) -> RuntimeControlSnapshot:
        """Update one live-editable parameter and reject inactive setpoints."""
        if name == "controller_type":
            return self.update(controller_type=value)

        if name in _LIVE_GENERATOR_FIELDS:
            return self.update(**{name: value})

        active_setpoints = _LIVE_SETPOINT_FIELDS[self.controller_type]
        if name in active_setpoints:
            return self.update(**{name: value})

        if any(name in fields for fields in _LIVE_SETPOINT_FIELDS.values()):
            raise ValueError(
                f"{name} is not active for controller_type={self.controller_type!r}"
            )

        raise KeyError(f"Unknown live control parameter: {name}")

    @staticmethod
    def _validate_snapshot(snapshot: RuntimeControlSnapshot) -> None:
        if snapshot.controller_type not in _LIVE_SETPOINT_FIELDS:
            raise ValueError(
                "controller_type must be one of: "
                f"{', '.join(sorted(_LIVE_SETPOINT_FIELDS))}"
            )

        float_fields = {
            "target_gap": snapshot.target_gap,
            "target_avg_voltage": snapshot.target_avg_voltage,
            "fixed_servo": snapshot.fixed_servo,
            "generator_voltage": snapshot.generator_voltage,
            "on_time": snapshot.on_time,
            "off_time": snapshot.off_time,
        }
        for field_name, value in float_fields.items():
            if not np.isfinite(value):
                raise ValueError(f"{field_name} must be finite")

        if snapshot.target_gap < 0.0:
            raise ValueError("target_gap must be non-negative")
        if snapshot.target_avg_voltage < 0.0:
            raise ValueError("target_avg_voltage must be non-negative")
        if snapshot.generator_voltage < 0.0:
            raise ValueError("generator_voltage must be non-negative")
        if snapshot.on_time < 0.0:
            raise ValueError("on_time must be non-negative")
        if snapshot.off_time < 0.0:
            raise ValueError("off_time must be non-negative")
        if snapshot.current_mode < 1:
            raise ValueError("current_mode must be >= 1")


class RuntimeController:
    """Callable controller that reads its parameters from RuntimeControlState."""

    def __init__(self, control_state: RuntimeControlState):
        self.control_state = control_state
        self._integral_error = 0.0

    @property
    def requires_voltage_history(self) -> bool:
        return self.control_state.controller_type == "voltage"

    def reset(self) -> None:
        self._integral_error = 0.0

    def set_param(self, name: str, value: float | int | str) -> RuntimeControlSnapshot:
        """Update one runtime control parameter and reset internal state if needed."""
        previous_type = self.control_state.controller_type
        snapshot = self.control_state.set_param(name, value)
        if name == "controller_type" and snapshot.controller_type != previous_type:
            self.reset()
        return snapshot

    def __call__(
        self, env: WireEDMEnv, voltage_history: Sequence[float] | None = None
    ) -> ScalarAction:
        snapshot = self.control_state.snapshot()
        if snapshot.controller_type == "gap":
            return self._gap_action(env, snapshot)
        if snapshot.controller_type == "voltage":
            return self._voltage_action(env, snapshot, voltage_history)
        return self._fixed_servo_action(snapshot)

    def _gap_action(
        self, env: WireEDMEnv, snapshot: RuntimeControlSnapshot
    ) -> ScalarAction:
        gap = env.state.workpiece_position - env.state.wire_position
        error = gap - snapshot.target_gap

        if env.mechanics.control_mode == "position":
            delta = error * 0.1
        else:
            delta = float(np.clip(error * 50.0, -1000.0, 1000.0))

        return self._build_action(delta, snapshot)

    def _voltage_action(
        self,
        env: WireEDMEnv,
        snapshot: RuntimeControlSnapshot,
        voltage_history: Sequence[float] | None,
    ) -> ScalarAction:
        if voltage_history:
            avg_voltage = float(np.mean(tuple(voltage_history)))
        else:
            avg_voltage = env.state.voltage

        error = snapshot.target_avg_voltage - avg_voltage
        self._integral_error += error
        self._integral_error = float(np.clip(self._integral_error, -100.0, 100.0))

        pi_output = -(0.05 * error + 0.1 * self._integral_error * 0.001)

        if env.mechanics.control_mode == "position":
            delta = float(np.clip(pi_output, -5.0, 5.0))
        else:
            delta = float(np.clip(pi_output * 100.0, -1000.0, 1000.0))

        return self._build_action(delta, snapshot)

    def _fixed_servo_action(self, snapshot: RuntimeControlSnapshot) -> ScalarAction:
        return self._build_action(snapshot.fixed_servo, snapshot)

    @staticmethod
    def _build_action(
        servo: float, snapshot: RuntimeControlSnapshot
    ) -> ScalarAction:
        return build_scalar_action(
            servo=float(servo),
            target_voltage=snapshot.generator_voltage,
            current_mode=snapshot.current_mode,
            ON_time=snapshot.on_time,
            OFF_time=snapshot.off_time,
        )
