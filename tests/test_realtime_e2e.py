from __future__ import annotations

import asyncio
import json

import websockets

from wedm import WireEDMEnv
from wedm.realtime import RuntimeControlState, RuntimeController
from wedm.realtime.schema import SCHEMA_VERSION
from wedm.realtime.server import RealtimeSessionServer


def build_env() -> WireEDMEnv:
    env = WireEDMEnv()
    env.reset(seed=123)
    env.state.workpiece_position = 70.0
    env.state.wire_position = 10.0
    env.state.target_position = 5_000.0
    env.state.voltage = 40.0
    return env


async def recv_message(
    websocket: websockets.ClientConnection, timeout: float = 2.0
) -> dict:
    raw_message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    return json.loads(raw_message)


async def recv_until(
    websocket: websockets.ClientConnection,
    predicate,
    *,
    timeout: float = 5.0,
) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    seen_types: list[str] = []

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0.0:
            raise AssertionError(
                f"timed out waiting for expected realtime message; saw {seen_types}"
            )

        message = await recv_message(websocket, timeout=remaining)
        seen_types.append(str(message.get("type")))
        if predicate(message):
            return message


def test_realtime_live_path_end_to_end() -> None:
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
            slowdown_factor=50.0,
            max_pending_messages=1024,
        )
        await server.start()

        try:
            async with websockets.connect(server.url, ping_interval=None) as websocket:
                header = await recv_message(websocket)
                assert header["type"] == "session_header"
                assert header["payload"]["current_params"]["off_time"] == 33.0
                assert header["payload"]["metadata"]["servo_interval_us"] == env.servo_interval

                initial_state = await recv_message(websocket)
                assert initial_state["type"] == "session_state"
                assert initial_state["payload"]["state"] in {"created", "running"}

                saw_process_frame = False
                saw_pulse_chunk = False
                first_process_frame_time_us = None
                while not (saw_process_frame and saw_pulse_chunk):
                    message = await recv_message(websocket, timeout=5.0)
                    if message["type"] == "process_frame":
                        saw_process_frame = True
                        first_process_frame_time_us = message["payload"]["time_us"]
                        assert message["payload"]["off_time_us"] == 33.0
                    elif message["type"] == "pulse_chunk":
                        saw_pulse_chunk = True

                assert saw_process_frame
                assert saw_pulse_chunk
                assert first_process_frame_time_us is not None

                await websocket.send(
                    json.dumps(
                        {
                            "v": SCHEMA_VERSION,
                            "type": "set_param",
                            "payload": {"name": "off_time", "value": 17.0},
                        }
                    )
                )

                param_ack = await recv_until(
                    websocket,
                    lambda message: (
                        message["type"] == "session_state"
                        and message["payload"]["current_params"]["off_time"] == 17.0
                    ),
                )
                assert param_ack["payload"]["current_params"]["off_time"] == 17.0

                updated_process_frame = await recv_until(
                    websocket,
                    lambda message: (
                        message["type"] == "process_frame"
                        and message["payload"]["time_us"] > first_process_frame_time_us
                        and message["payload"]["off_time_us"] == 17.0
                    ),
                )
                assert updated_process_frame["payload"]["off_time_us"] == 17.0

                await websocket.send(
                    json.dumps(
                        {
                            "v": SCHEMA_VERSION,
                            "type": "pause",
                            "payload": {},
                        }
                    )
                )

                paused_state = await recv_until(
                    websocket,
                    lambda message: (
                        message["type"] == "session_state"
                        and message["payload"]["state"] == "paused"
                    ),
                )
                assert paused_state["payload"]["state"] == "paused"

                frozen_time_us = server.session.status().simulated_time_us
                await asyncio.sleep(0.12)
                assert server.session.status().simulated_time_us == frozen_time_us

                await websocket.send(
                    json.dumps(
                        {
                            "v": SCHEMA_VERSION,
                            "type": "resume",
                            "payload": {},
                        }
                    )
                )

                resumed_state = await recv_until(
                    websocket,
                    lambda message: (
                        message["type"] == "session_state"
                        and message["payload"]["state"] == "running"
                    ),
                )
                assert resumed_state["payload"]["state"] == "running"

                resumed_process_frame = await recv_until(
                    websocket,
                    lambda message: (
                        message["type"] == "process_frame"
                        and message["payload"]["time_us"] > frozen_time_us
                    ),
                )
                assert resumed_process_frame["payload"]["time_us"] > frozen_time_us

                await websocket.send(
                    json.dumps(
                        {
                            "v": SCHEMA_VERSION,
                            "type": "stop",
                            "payload": {},
                        }
                    )
                )

                stopped_state = await recv_until(
                    websocket,
                    lambda message: (
                        message["type"] == "session_state"
                        and message["payload"]["state"] == "stopped"
                    ),
                )
                assert stopped_state["payload"]["termination_reason"] == "stopped"
        finally:
            await server.stop()

    asyncio.run(scenario())
