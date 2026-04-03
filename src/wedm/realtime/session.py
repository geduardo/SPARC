from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import threading
import time
from typing import Callable

import numpy as np

from ..core.hot_state import HotStateBundle
from ..envs.wire_edm import CompiledActionPacket, WireEDMEnv
from .control import RuntimeControlSnapshot, RuntimeController


class RealtimeSessionState(str, Enum):
    """Lifecycle states for a realtime simulation session."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class PulseChunk:
    """Pulse-resolution samples collected over one control interval."""

    base_time_us: int
    dt_us: int
    voltage: np.ndarray
    current: np.ndarray
    spark_state: np.ndarray


@dataclass(frozen=True, slots=True)
class RealtimeSessionStatus:
    """Thread-safe public session status snapshot."""

    state: RealtimeSessionState
    slowdown_factor: float
    solver_limited: bool
    simulated_time_us: int
    control_steps: int
    wall_time_s: float
    termination_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RealtimeControlStep:
    """Boundary publication emitted once per control interval."""

    process_state: HotStateBundle
    pulse_chunk: PulseChunk
    control_snapshot: RuntimeControlSnapshot
    status: RealtimeSessionStatus


ControlStepCallback = Callable[[RealtimeControlStep], None]
StatusCallback = Callable[[RealtimeSessionStatus], None]
Clock = Callable[[], float]
SleepFn = Callable[[float], None]


class RealtimeSession:
    """Long-lived compiled-fast session with pacing and lifecycle control."""

    def __init__(
        self,
        env: WireEDMEnv,
        controller: RuntimeController,
        *,
        slowdown_factor: float = 100.0,
        on_control_step: ControlStepCallback | None = None,
        on_status_change: StatusCallback | None = None,
        clock: Clock = time.perf_counter,
        sleep: SleepFn = time.sleep,
    ) -> None:
        if slowdown_factor <= 0.0:
            raise ValueError("slowdown_factor must be positive")

        self.env = env
        self.controller = controller
        self._on_control_step = on_control_step
        self._on_status_change = on_status_change
        self._clock = clock
        self._sleep = sleep

        self._condition = threading.Condition()
        self._state = RealtimeSessionState.CREATED
        self._pause_requested = False
        self._stop_requested = False
        self._solver_limited = False
        self._slowdown_factor = float(slowdown_factor)
        self._termination_reason: str | None = None
        self._control_steps = 0
        self._wall_start_s: float | None = None
        self._started = False

        self._voltage_history: deque[float] = deque()
        self._time_history: deque[int] = deque()
        self._step_action: CompiledActionPacket | None = None

    def status(self) -> RealtimeSessionStatus:
        """Return a thread-safe public snapshot of the current session state."""
        now = self._clock()
        with self._condition:
            return self._status_locked(now)

    def set_slowdown_factor(self, slowdown_factor: float) -> RealtimeSessionStatus:
        """Update the pacing slowdown factor for future control intervals."""
        if slowdown_factor <= 0.0:
            raise ValueError("slowdown_factor must be positive")
        now = self._clock()
        with self._condition:
            self._slowdown_factor = float(slowdown_factor)
            return self._status_locked(now)

    def pause(self) -> None:
        """Pause the session at the next control boundary."""
        with self._condition:
            if self._state == RealtimeSessionState.STOPPED:
                return
            self._pause_requested = True
            self._condition.notify_all()

    def resume(self) -> None:
        """Resume a paused session."""
        with self._condition:
            if self._state == RealtimeSessionState.STOPPED:
                return
            self._pause_requested = False
            self._condition.notify_all()

    def stop(self) -> None:
        """Request orderly session shutdown."""
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()

    def run(self, *, max_control_steps: int | None = None) -> RealtimeSessionStatus:
        """Run the session until stopped, terminated, or max_control_steps is hit."""
        self._prepare_run()
        self._emit_status_change(self.status())

        try:
            while True:
                if not self._wait_until_running():
                    break

                update, terminated = self._advance_control_interval()
                self._apply_pacing(update.process_state.time)
                update = RealtimeControlStep(
                    process_state=update.process_state,
                    pulse_chunk=update.pulse_chunk,
                    control_snapshot=update.control_snapshot,
                    status=self.status(),
                )

                if self._on_control_step is not None:
                    self._on_control_step(update)

                if terminated:
                    break

                with self._condition:
                    if (
                        max_control_steps is not None
                        and self._control_steps >= max_control_steps
                        and self._termination_reason is None
                    ):
                        self._termination_reason = "max_control_steps"
                        break
                    if self._stop_requested and self._termination_reason is None:
                        self._termination_reason = "stopped"
                        break
        finally:
            final_status = self._finish_run()
            self._emit_status_change(final_status)

        return final_status

    def _prepare_run(self) -> None:
        with self._condition:
            if self._started:
                raise RuntimeError("RealtimeSession.run() can only be called once")
            self._started = True
            self._pause_requested = False
            self._stop_requested = False
            self._solver_limited = False
            self._termination_reason = None
            self._control_steps = 0
            self._state = RealtimeSessionState.CREATED

        self.controller.reset()
        self._voltage_history.clear()
        self._time_history.clear()
        self.env.init_compiled_scheduler()

        action = self.controller(
            self.env,
            list(self._voltage_history) if self.controller.requires_voltage_history else None,
        )
        self._step_action = self.env.prime_compiled_action(action)

        now = self._clock()
        with self._condition:
            self._wall_start_s = now
            self._state = RealtimeSessionState.RUNNING

    def _wait_until_running(self) -> bool:
        while True:
            paused_status: RealtimeSessionStatus | None = None
            resumed_status: RealtimeSessionStatus | None = None

            with self._condition:
                if self._stop_requested:
                    if self._termination_reason is None:
                        self._termination_reason = "stopped"
                    return False

                if self._pause_requested:
                    if self._state != RealtimeSessionState.PAUSED:
                        self._state = RealtimeSessionState.PAUSED
                        paused_status = self._status_locked(self._clock())
                    self._condition.wait(timeout=0.1)
                else:
                    if self._state != RealtimeSessionState.RUNNING:
                        self._state = RealtimeSessionState.RUNNING
                        resumed_status = self._status_locked(self._clock())
                    else:
                        return True

            if paused_status is not None:
                self._emit_status_change(paused_status)
            if resumed_status is not None:
                self._emit_status_change(resumed_status)
                return True

    def _advance_control_interval(self) -> tuple[RealtimeControlStep, bool]:
        if self._step_action is None:
            raise RuntimeError("RealtimeSession has not been prepared")

        start_time_us = int(self.env._hot_state.time)
        max_samples = int(self.env.servo_interval)
        voltage = np.empty(max_samples, dtype=np.float32)
        current = np.empty(max_samples, dtype=np.float32)
        spark_state = np.empty(max_samples, dtype=np.int8)

        sample_count = 0
        terminated = False
        for sample_count in range(max_samples):
            terminated, truncated = self.env.step_compiled_fast(self._step_action)
            hs = self.env._hot_state
            voltage[sample_count] = hs.voltage
            current[sample_count] = hs.current
            spark_state[sample_count] = hs.spark_state
            self._record_voltage_sample(int(hs.time), float(hs.voltage))

            if terminated or truncated:
                terminated = True
                break

        self.env.sync_compiled_to_state()
        process_state = self.env.build_hot_state_bundle(copy_arrays=True)

        control_snapshot = self.controller.control_state.snapshot()
        if not terminated:
            next_action = self.controller(
                self.env,
                list(self._voltage_history)
                if self.controller.requires_voltage_history
                else None,
            )
            self._step_action = self.env.prime_compiled_action(next_action)
            control_snapshot = self.controller.control_state.snapshot()
        else:
            self._step_action = None
            self._termination_reason = self._resolve_termination_reason()

        with self._condition:
            self._control_steps += 1

        pulse_chunk = PulseChunk(
            base_time_us=start_time_us + int(self.env.dt),
            dt_us=int(self.env.dt),
            voltage=voltage[: sample_count + 1].copy(),
            current=current[: sample_count + 1].copy(),
            spark_state=spark_state[: sample_count + 1].copy(),
        )
        update = RealtimeControlStep(
            process_state=process_state,
            pulse_chunk=pulse_chunk,
            control_snapshot=control_snapshot,
            status=self.status(),
        )
        return update, terminated

    def _record_voltage_sample(self, current_time_us: int, voltage: float) -> None:
        self._voltage_history.append(voltage)
        self._time_history.append(current_time_us)
        cutoff_time_us = current_time_us - int(self.env.servo_interval)
        while self._time_history and self._time_history[0] <= cutoff_time_us:
            self._time_history.popleft()
            self._voltage_history.popleft()

    def _apply_pacing(self, simulated_time_us: int) -> None:
        now = self._clock()
        with self._condition:
            if self._wall_start_s is None:
                raise RuntimeError("RealtimeSession pacing started without a wall clock")
            slowdown_factor = self._slowdown_factor
            elapsed_wall_s = now - self._wall_start_s

        target_wall_s = (simulated_time_us / 1_000_000.0) * slowdown_factor
        sleep_s = target_wall_s - elapsed_wall_s
        if sleep_s > 0.0:
            self._sleep(sleep_s)
            solver_limited = False
        else:
            solver_limited = True

        with self._condition:
            self._solver_limited = solver_limited

    def _resolve_termination_reason(self) -> str:
        if self.env.state.is_target_distance_reached:
            return "target_reached"
        if self.env.state.is_wire_broken:
            return "wire_broken"
        return "terminated"

    def _finish_run(self) -> RealtimeSessionStatus:
        now = self._clock()
        with self._condition:
            if self._termination_reason is None:
                if self._stop_requested:
                    self._termination_reason = "stopped"
                else:
                    self._termination_reason = "completed"
            self._state = RealtimeSessionState.STOPPED
            return self._status_locked(now)

    def _status_locked(self, now: float) -> RealtimeSessionStatus:
        wall_time_s = 0.0
        if self._wall_start_s is not None:
            wall_time_s = max(0.0, now - self._wall_start_s)

        simulated_time_us = int(getattr(self.env.state, "time", 0))
        if hasattr(self.env, "_hot_state"):
            simulated_time_us = int(self.env._hot_state.time)

        return RealtimeSessionStatus(
            state=self._state,
            slowdown_factor=self._slowdown_factor,
            solver_limited=self._solver_limited,
            simulated_time_us=simulated_time_us,
            control_steps=self._control_steps,
            wall_time_s=wall_time_s,
            termination_reason=self._termination_reason,
        )

    def _emit_status_change(self, status: RealtimeSessionStatus) -> None:
        if self._on_status_change is not None:
            self._on_status_change(status)
