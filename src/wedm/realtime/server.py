from __future__ import annotations

import asyncio
import copy
from collections import deque
from dataclasses import dataclass
import threading
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection

from ..envs.wire_edm import WireEDMEnv
from .control import RuntimeController
from .schema import (
    ClientCommand,
    dumps_message,
    parse_client_message,
    serialize_error,
    serialize_process_frame,
    serialize_pulse_chunk,
    serialize_session_header,
    serialize_session_state,
)
from .session import (
    RealtimeControlStep,
    PulseChunk,
    RealtimeProcessFrame,
    RealtimeSession,
    RealtimeSessionState,
    RealtimeSessionStatus,
)


@dataclass(frozen=True, slots=True)
class _QueuedMessage:
    payload: dict[str, Any]
    droppable: bool


@dataclass(frozen=True, slots=True)
class _RestartSessionSignal:
    pass


class _DropOldestMessageQueue:
    """Thread-safe queue that drops oldest droppable items on backpressure."""

    def __init__(self, maxsize: int):
        self._maxsize = maxsize
        self._items: deque[_QueuedMessage] = deque()
        self._condition = threading.Condition()
        self._closed = False

    def put(
        self,
        payload: dict[str, Any],
        *,
        droppable: bool,
        priority: bool = False,
    ) -> bool:
        with self._condition:
            if self._closed:
                return False

            if self._maxsize > 0 and len(self._items) >= self._maxsize:
                if not self._drop_one_locked(prefer_droppable=True):
                    if not droppable:
                        return False
                    self._items.popleft()

            queued = _QueuedMessage(payload=payload, droppable=droppable)
            if priority:
                self._items.appendleft(queued)
            else:
                self._items.append(queued)
            self._condition.notify()
            return True

    def get(self) -> dict[str, Any] | None:
        with self._condition:
            while not self._items and not self._closed:
                self._condition.wait()

            if self._items:
                return self._items.popleft().payload
            return None

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def clear(self) -> None:
        with self._condition:
            self._items.clear()
            self._condition.notify_all()

    def _drop_one_locked(self, *, prefer_droppable: bool) -> bool:
        if not self._items:
            return False

        if prefer_droppable:
            for index, item in enumerate(self._items):
                if item.droppable:
                    del self._items[index]
                    return True

        self._items.popleft()
        return True


class RealtimeSessionServer:
    """Single-client WebSocket transport for a realtime simulation session."""

    def __init__(
        self,
        env: WireEDMEnv,
        controller: RuntimeController,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        slowdown_factor: float = 100.0,
        max_pending_messages: int = 256,
        max_control_steps: int | None = None,
        include_wire_field_arrays: bool = True,
        ping_interval: float | None = 20.0,
        ping_timeout: float | None = 20.0,
    ) -> None:
        self.env = env
        self.controller = controller
        self.host = host
        self.port = port
        self.max_pending_messages = max_pending_messages
        self.max_control_steps = max_control_steps
        self.include_wire_field_arrays = include_wire_field_arrays
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self._initial_hot_state = env.build_hot_state_bundle(copy_arrays=True)
        bit_generator = getattr(getattr(env, "np_random", None), "bit_generator", None)
        self._initial_rng_state = (
            copy.deepcopy(bit_generator.state) if bit_generator is not None else None
        )

        self.session = self._build_session(slowdown_factor)

        self._server: websockets.asyncio.server.Server | None = None
        self._session_thread: threading.Thread | None = None
        self._session_started = False
        self._transport_lock = threading.Lock()
        self._active_queue: _DropOldestMessageQueue | None = None
        self._active_connection: ServerConnection | None = None
        self._active_connection_lock = asyncio.Lock()

    @property
    def bound_port(self) -> int:
        if self._server is None or not self._server.sockets:
            return self.port
        return int(self._server.sockets[0].getsockname()[1])

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.bound_port}"

    async def start(self) -> "RealtimeSessionServer":
        """Start accepting WebSocket connections."""
        if self._server is not None:
            return self

        self._server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port,
            ping_interval=self.ping_interval,
            ping_timeout=self.ping_timeout,
        )
        return self

    async def stop(self) -> None:
        """Stop accepting connections and request session shutdown."""
        self.session.stop()

        queue = self._get_active_queue()
        if queue is not None:
            queue.close()

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        if self._session_thread is not None:
            await asyncio.to_thread(self._session_thread.join, 5.0)
            self._session_thread = None

    async def _handle_client(self, websocket: ServerConnection) -> None:
        async with self._active_connection_lock:
            if self._active_connection is not None:
                await websocket.send(
                    dumps_message(
                        serialize_error(
                            "session_busy",
                            "another client is already controlling this realtime session",
                        )
                    )
                )
                await websocket.close(code=1013, reason="session busy")
                return

            queue = _DropOldestMessageQueue(self.max_pending_messages)
            self._active_connection = websocket
            with self._transport_lock:
                self._active_queue = queue

        sender = asyncio.create_task(self._send_messages(websocket, queue))
        try:
            await websocket.send(
                dumps_message(
                    serialize_session_header(
                        self.env,
                        self.controller.control_state.snapshot(),
                        self.session.status(),
                    )
                )
            )
            await websocket.send(
                dumps_message(
                    serialize_session_state(
                        self.session.status(),
                        self.controller.control_state.snapshot(),
                    )
                )
            )
            self._ensure_session_started()

            async for raw_message in websocket:
                response = self._handle_client_command(raw_message, queue=queue)
                if isinstance(response, _RestartSessionSignal):
                    await websocket.close(code=1012, reason="session restarted")
                    return
                if response is not None:
                    self._publish_direct(
                        queue,
                        response,
                        droppable=False,
                        priority=True,
                    )
        finally:
            queue.close()
            try:
                await asyncio.wait_for(sender, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                sender.cancel()
                try:
                    await sender
                except asyncio.CancelledError:
                    pass
            except websockets.ConnectionClosed:
                pass

            async with self._active_connection_lock:
                self._active_connection = None
                with self._transport_lock:
                    if self._active_queue is queue:
                        self._active_queue = None

    async def _send_messages(
        self, websocket: ServerConnection, queue: _DropOldestMessageQueue
    ) -> None:
        while True:
            message = await asyncio.to_thread(queue.get)
            if message is None:
                return
            await websocket.send(dumps_message(message))

    def _ensure_session_started(self) -> None:
        with self._transport_lock:
            if self._session_started:
                return
            self._session_started = True
            self._session_thread = threading.Thread(
                target=self._run_session,
                name="wedm-realtime-session",
                daemon=True,
            )
            self._session_thread.start()

    def _run_session(self) -> None:
        self.session.run(max_control_steps=self.max_control_steps)

    def _build_session(self, slowdown_factor: float) -> RealtimeSession:
        return RealtimeSession(
            self.env,
            self.controller,
            slowdown_factor=slowdown_factor,
            on_process_frame=self._on_process_frame,
            on_pulse_chunk=self._on_pulse_chunk,
            on_status_change=self._on_status_change,
        )

    def _reset_env_to_initial_state(self) -> None:
        self.env.apply_hot_state_bundle(self._initial_hot_state)
        bit_generator = getattr(getattr(self.env, "np_random", None), "bit_generator", None)
        if bit_generator is not None and self._initial_rng_state is not None:
            bit_generator.state = copy.deepcopy(self._initial_rng_state)

    def _restart_session(
        self, queue: _DropOldestMessageQueue | None = None
    ) -> _RestartSessionSignal:
        status = self.session.status()
        if status.state != RealtimeSessionState.STOPPED:
            raise ValueError("restart is only available after the live session stops")

        self._session_thread = None

        slowdown_factor = float(status.requested_slowdown_factor)
        if slowdown_factor <= 0.0:
            slowdown_factor = float(status.slowdown_factor)

        self._reset_env_to_initial_state()
        self.session = self._build_session(slowdown_factor)

        with self._transport_lock:
            self._session_started = False

        if queue is None:
            queue = self._get_active_queue()
        if queue is not None:
            queue.clear()
        return _RestartSessionSignal()

    def _handle_client_command(
        self,
        raw_message: str | bytes,
        *,
        queue: _DropOldestMessageQueue | None = None,
    ) -> dict[str, Any] | _RestartSessionSignal | None:
        if isinstance(raw_message, bytes):
            return serialize_error(
                "invalid_message",
                "binary client messages are not supported",
            )

        try:
            command = parse_client_message(raw_message)
            return self._apply_command(command, queue=queue)
        except Exception as exc:
            return serialize_error(
                "invalid_message",
                str(exc),
            )

    def _apply_command(
        self,
        command: ClientCommand,
        *,
        queue: _DropOldestMessageQueue | None = None,
    ) -> dict[str, Any] | _RestartSessionSignal | None:
        if command.command_type == "set_param":
            param_name = command.payload.get("name")
            if not isinstance(param_name, str):
                raise ValueError("set_param requires payload.name")
            if "value" not in command.payload:
                raise ValueError("set_param requires payload.value")
            self.controller.set_param(
                param_name,
                command.payload["value"],
            )
        elif command.command_type == "set_speed":
            slowdown_factor = command.payload.get("slowdown_factor")
            if slowdown_factor is None:
                raise ValueError("set_speed requires payload.slowdown_factor")
            self.session.set_slowdown_factor(float(slowdown_factor))
        elif command.command_type == "pause":
            self.session.pause()
        elif command.command_type == "resume":
            self.session.resume()
        elif command.command_type == "stop":
            self.session.stop()
        elif command.command_type == "restart":
            return self._restart_session(queue=queue)
        else:
            raise ValueError(f"unsupported client command: {command.command_type!r}")

        return serialize_session_state(
            self.session.status(),
            self.controller.control_state.snapshot(),
        )

    def _on_control_step(self, update: RealtimeControlStep) -> None:
        return

    def _on_pulse_chunk(self, chunk: PulseChunk) -> None:
        queue = self._get_active_queue()
        if queue is None:
            return

        self._publish_direct(
            queue,
            serialize_pulse_chunk(chunk),
            droppable=True,
            priority=False,
        )

    def _on_process_frame(self, update: RealtimeProcessFrame) -> None:
        queue = self._get_active_queue()
        if queue is None:
            return

        self._publish_direct(
            queue,
            serialize_process_frame(
                update,
                include_wire_field_arrays=self.include_wire_field_arrays,
            ),
            droppable=True,
            priority=False,
        )

    def _on_status_change(self, status: RealtimeSessionStatus) -> None:
        queue = self._get_active_queue()
        if queue is None:
            return
        self._publish_direct(
            queue,
            serialize_session_state(status, self.controller.control_state.snapshot()),
            droppable=False,
            priority=True,
        )

    def _get_active_queue(self) -> _DropOldestMessageQueue | None:
        with self._transport_lock:
            return self._active_queue

    @staticmethod
    def _publish_direct(
        queue: _DropOldestMessageQueue,
        message: dict[str, Any],
        *,
        droppable: bool,
        priority: bool,
    ) -> None:
        queue.put(message, droppable=droppable, priority=priority)
