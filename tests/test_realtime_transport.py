from __future__ import annotations

import asyncio
import json

import websockets

from wedm import WireEDMEnv
from wedm.realtime import RuntimeControlState, RuntimeController
from wedm.realtime.schema import (
    SCHEMA_VERSION,
    parse_client_message,
    serialize_process_frame,
    serialize_session_header,
    serialize_session_state,
)
from wedm.realtime.server import RealtimeSessionServer


def build_env() -> WireEDMEnv:
    env = WireEDMEnv()
    env.reset(seed=123)
    env.state.workpiece_position = 70.0
    env.state.wire_position = 10.0
    env.state.target_position = 5_000.0
    env.state.voltage = 40.0
    return env


def test_schema_serialization_matches_realtime_contract() -> None:
    env = build_env()
    controller = RuntimeController(
        RuntimeControlState(
            controller_type="gap",
            target_gap=5.0,
            generator_voltage=80.0,
            current_mode=7,
            on_time=2.0,
            off_time=33.0,
        )
    )

    session = RealtimeSessionServer(
        env,
        controller,
        slowdown_factor=100.0,
        max_control_steps=1,
    )
    session.session._prepare_run()
    try:
        update, _ = session.session._advance_control_interval()
        status = session.session.status()

        header = serialize_session_header(
            env,
            controller.control_state.snapshot(),
            status,
        )
        state = serialize_session_state(status, controller.control_state.snapshot())
        frame = serialize_process_frame(update)

        assert header["v"] == SCHEMA_VERSION
        assert header["type"] == "session_header"
        assert header["payload"]["metadata"]["dt_us"] == env.dt
        assert "current_params" in header["payload"]
        assert "controller_type" in header["payload"]["supported_params"]

        assert state["type"] == "session_state"
        assert state["payload"]["current_params"]["controller_type"] == "gap"

        assert frame["type"] == "process_frame"
        assert frame["payload"]["time_us"] == env.servo_interval
        assert isinstance(frame["payload"]["wire_temperature"], list)
        assert isinstance(frame["payload"]["wire_damage"], list)
        assert isinstance(frame["payload"]["wire_material_positions_mm"], list)
        assert isinstance(frame["payload"]["spark_events"], list)
    finally:
        session.session.stop()


def test_parse_client_message_requires_versioned_envelope() -> None:
    parsed = parse_client_message(
        {
            "v": SCHEMA_VERSION,
            "type": "set_param",
            "payload": {"name": "target_gap", "value": 25.0},
        }
    )
    assert parsed.command_type == "set_param"
    assert parsed.payload["name"] == "target_gap"


def test_realtime_websocket_server_streams_and_applies_commands() -> None:
    async def scenario() -> None:
        env = build_env()
        controller = RuntimeController(
            RuntimeControlState(
                controller_type="gap",
                target_gap=5.0,
                generator_voltage=80.0,
                current_mode=7,
                on_time=2.0,
                off_time=33.0,
            )
        )
        server = RealtimeSessionServer(
            env,
            controller,
            host="127.0.0.1",
            port=0,
            slowdown_factor=1.0,
            max_pending_messages=512,
        )
        await server.start()

        try:
            async with websockets.connect(server.url, ping_interval=None) as websocket:
                header = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2.0))
                assert header["type"] == "session_header"
                assert header["payload"]["current_params"]["target_gap"] == 5.0

                initial_state = json.loads(
                    await asyncio.wait_for(websocket.recv(), timeout=2.0)
                )
                assert initial_state["type"] == "session_state"

                await websocket.send(
                    json.dumps(
                        {
                            "v": SCHEMA_VERSION,
                            "type": "set_param",
                            "payload": {"name": "controller_type", "value": "voltage"},
                        }
                    )
                )

                await websocket.send(
                    json.dumps(
                        {
                            "v": SCHEMA_VERSION,
                            "type": "set_param",
                            "payload": {"name": "target_avg_voltage", "value": 50.0},
                        }
                    )
                )

                saw_param_ack = False
                saw_controller_switch = False
                saw_process_frame = False
                saw_pulse_chunk = False
                deadline = asyncio.get_running_loop().time() + 2.0
                while asyncio.get_running_loop().time() < deadline:
                    message = json.loads(
                        await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    )
                    if message["type"] == "session_state":
                        current_params = message["payload"]["current_params"]
                        if current_params["controller_type"] == "voltage":
                            saw_controller_switch = True
                        if current_params["target_avg_voltage"] == 50.0:
                            saw_param_ack = True
                    elif message["type"] == "process_frame":
                        saw_process_frame = True
                    elif message["type"] == "pulse_chunk":
                        saw_pulse_chunk = True

                    if saw_controller_switch and saw_param_ack and saw_process_frame and saw_pulse_chunk:
                        break

                assert saw_controller_switch
                assert saw_param_ack
                assert saw_process_frame
                assert saw_pulse_chunk

                await websocket.send(
                    json.dumps(
                        {
                            "v": SCHEMA_VERSION,
                            "type": "stop",
                            "payload": {},
                        }
                    )
                )

                saw_stopped_state = False
                deadline = asyncio.get_running_loop().time() + 5.0
                while asyncio.get_running_loop().time() < deadline:
                    message = json.loads(
                        await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    )
                    if (
                        message["type"] == "session_state"
                        and message["payload"]["state"] == "stopped"
                    ):
                        saw_stopped_state = True
                        break

                assert saw_stopped_state
        finally:
            await server.stop()

    asyncio.run(scenario())
