from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Literal, Mapping

import numpy as np

from ..core.hot_state import HotStateBundle
from ..envs.wire_edm import WireEDMEnv
from .control import RuntimeControlSnapshot
from .session import (
    PulseChunk,
    RealtimeControlStep,
    RealtimeProcessFrame,
    RealtimeSessionState,
    RealtimeSessionStatus,
)


SCHEMA_VERSION = 1

ClientCommandType = Literal["set_param", "set_speed", "pause", "resume", "stop"]

LIVE_EDITABLE_PARAMS = (
    "controller_type",
    "target_gap",
    "target_avg_voltage",
    "fixed_servo",
    "generator_voltage",
    "current_mode",
    "off_time",
    "slowdown_factor",
)


@dataclass(frozen=True, slots=True)
class ClientCommand:
    """Validated client-to-server command envelope."""

    command_type: ClientCommandType
    payload: Mapping[str, Any]


def build_envelope(message_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap a payload in the realtime transport envelope."""
    return {
        "v": SCHEMA_VERSION,
        "type": message_type,
        "payload": dict(payload),
    }


def dumps_message(message: Mapping[str, Any]) -> str:
    """Serialize a transport message to JSON."""
    return json.dumps(message, separators=(",", ":"))


def parse_client_message(raw_message: str | Mapping[str, Any]) -> ClientCommand:
    """Parse and validate a client command envelope."""
    if isinstance(raw_message, str):
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON message") from exc
    else:
        message = dict(raw_message)

    if not isinstance(message, dict):
        raise ValueError("client message must decode to an object")

    version = message.get("v")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema version: {version!r}")

    command_type = message.get("type")
    if command_type not in {"set_param", "set_speed", "pause", "resume", "stop"}:
        raise ValueError(f"unsupported client command: {command_type!r}")

    payload = message.get("payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("client message payload must be an object")

    return ClientCommand(command_type=command_type, payload=payload)


def snapshot_to_params(
    snapshot: RuntimeControlSnapshot, slowdown_factor: float
) -> dict[str, Any]:
    """Serialize live-adjustable runtime parameters."""
    return {
        "controller_type": snapshot.controller_type,
        "target_gap": snapshot.target_gap,
        "target_avg_voltage": snapshot.target_avg_voltage,
        "fixed_servo": snapshot.fixed_servo,
        "generator_voltage": snapshot.generator_voltage,
        "current_mode": snapshot.current_mode,
        "on_time": snapshot.on_time,
        "off_time": snapshot.off_time,
        "slowdown_factor": slowdown_factor,
    }


def serialize_session_header(
    env: WireEDMEnv,
    snapshot: RuntimeControlSnapshot,
    status: RealtimeSessionStatus,
) -> dict[str, Any]:
    """Build the session-header message sent on connect."""
    wire_params = env.wire.params
    payload = {
        "schema_version": SCHEMA_VERSION,
        "state": _serialize_session_state(status.state),
        "metadata": {
            "workpiece_height_mm": float(env.config.workpiece_height),
            "wire_diameter": float(env.config.wire_diameter),
            "wire_diameter_um": float(env.config.wire_diameter * 1000.0),
            "buffer_len_bottom": float(wire_params.buffer_len_bottom),
            "buffer_len_top": float(wire_params.buffer_len_top),
            "contact_offset_bottom": float(wire_params.contact_offset_bottom),
            "contact_offset_top": float(wire_params.contact_offset_top),
            "segment_len_mm": float(wire_params.segment_len),
            "control_mode": env.mechanics.control_mode,
            "controller_strategy": snapshot.controller_type,
            "dt_us": int(env.dt),
            "servo_interval_us": int(env.servo_interval),
        },
        "supported_params": list(LIVE_EDITABLE_PARAMS),
        "current_params": snapshot_to_params(snapshot, status.slowdown_factor),
    }
    return build_envelope("session_header", payload)


def serialize_session_state(
    status: RealtimeSessionStatus,
    snapshot: RuntimeControlSnapshot,
) -> dict[str, Any]:
    """Build a session-state message."""
    payload = {
        "state": _serialize_session_state(status.state),
        "slowdown_factor": status.slowdown_factor,
        "solver_limited": bool(status.solver_limited),
        "simulated_time_us": int(status.simulated_time_us),
        "control_steps": int(status.control_steps),
        "wall_time_s": float(status.wall_time_s),
        "termination_reason": status.termination_reason,
        "current_params": snapshot_to_params(snapshot, status.slowdown_factor),
    }
    return build_envelope("session_state", payload)


def serialize_process_frame(
    update: RealtimeControlStep | RealtimeProcessFrame,
    *,
    include_wire_field_arrays: bool = True,
) -> dict[str, Any]:
    """Build a process-frame message from a control-step update."""
    state = update.process_state
    spark_events = update.spark_events
    payload: dict[str, Any] = {
        "time_us": int(state.time),
        "wire_position_um": float(state.wire_position_um),
        "wire_velocity_um_s": float(state.wire_velocity_um_s),
        "workpiece_position_um": float(state.workpiece_position_um),
        "target_delta": float(state.target_delta),
        "target_voltage": _decode_optional_float(state.target_voltage),
        "current_mode": _decode_current_mode(state.current_mode_code),
        "on_time_us": _decode_optional_float(state.on_time_us),
        "off_time_us": _decode_optional_float(state.off_time_us),
        "voltage": float(state.voltage),
        "current": float(state.current),
        "spark_state": int(state.spark_state),
        "spark_location_mm": _decode_optional_float(state.spark_location_mm),
        "spark_duration": int(state.spark_duration),
        "is_short_circuit": bool(state.is_short_circuit),
        "debris_density": float(state.debris_density),
        "flow_rate": float(state.flow_rate),
        "wire_head_idx": int(state.wire_head_idx),
        "wire_offset_mm": float(state.wire_offset_mm),
        "spark_events": [
            {
                "time_us": int(event.time_us),
                "location_mm": float(event.location_mm),
            }
            for event in spark_events
        ],
    }
    if include_wire_field_arrays:
        payload["wire_temperature"] = _array_to_list(state.wire_temperature, cast=float)
        payload["wire_damage"] = _array_to_list(state.wire_damage, cast=float)
        payload["wire_material_positions_mm"] = _array_to_list(
            state.wire_material_positions_mm, cast=float
        )

    return build_envelope("process_frame", payload)


def serialize_pulse_chunk(chunk: PulseChunk) -> dict[str, Any]:
    """Build a pulse-chunk message."""
    payload = {
        "base_time_us": int(chunk.base_time_us),
        "dt_us": int(chunk.dt_us),
        "voltage": _array_to_list(chunk.voltage, cast=float),
        "current": _array_to_list(chunk.current, cast=float),
        "spark_state": _array_to_list(chunk.spark_state, cast=int),
    }
    return build_envelope("pulse_chunk", payload)


def serialize_error(code: str, message: str, *, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build an error message."""
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details:
        payload["details"] = dict(details)
    return build_envelope("error", payload)


def _serialize_session_state(state: RealtimeSessionState | str) -> str:
    if isinstance(state, RealtimeSessionState):
        return state.value
    return str(state)


def _decode_optional_float(value: float) -> float | None:
    return None if math.isnan(value) else float(value)


def _decode_current_mode(value: int) -> str | None:
    return None if value <= 0 else f"I{value}"


def _array_to_list(array: np.ndarray, *, cast: type) -> list[Any]:
    return [cast(item) for item in np.asarray(array).tolist()]
