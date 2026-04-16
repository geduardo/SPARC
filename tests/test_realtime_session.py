from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from wedm import WireEDMEnv
from wedm.realtime import (
    RealtimeSession,
    RealtimeSessionState,
    RuntimeControlState,
    RuntimeController,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleep_calls: list[float] = []

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.sleep_calls.append(duration)
        self.now += duration


class IncrementingClock(FakeClock):
    def __init__(self, tick_s: float) -> None:
        super().__init__()
        self.tick_s = tick_s

    def perf_counter(self) -> float:
        value = self.now
        self.now += self.tick_s
        return value


class ScriptedClock(FakeClock):
    def __init__(self, timeline_s: list[float]) -> None:
        super().__init__()
        self.timeline_s = list(timeline_s)
        self.index = 0

    def perf_counter(self) -> float:
        if self.index < len(self.timeline_s):
            self.now = self.timeline_s[self.index]
            self.index += 1
        return self.now


@pytest.fixture
def env() -> WireEDMEnv:
    env = WireEDMEnv()
    env.reset(seed=123)
    env.state.workpiece_position = 70.0
    env.state.wire_position = 10.0
    env.state.target_position = 5_000.0
    env.state.voltage = 40.0
    return env


def test_realtime_session_emits_control_steps_and_applies_live_updates(
    env: WireEDMEnv,
) -> None:
    clock = FakeClock()
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
    updates = []

    def on_control_step(update) -> None:
        updates.append(update)
        if len(updates) == 1:
            controller.control_state.set_param("target_gap", 50.0)

    session = RealtimeSession(
        env,
        controller,
        slowdown_factor=100.0,
        on_control_step=on_control_step,
        clock=clock.perf_counter,
        sleep=clock.sleep,
    )

    final_status = session.run(max_control_steps=2)

    assert final_status.state == RealtimeSessionState.STOPPED
    assert final_status.termination_reason == "max_control_steps"
    assert len(updates) == 2
    assert updates[0].process_state.time == 1000
    assert updates[1].process_state.time == 2000
    assert updates[0].pulse_chunk.base_time_us == 1
    assert len(updates[0].pulse_chunk.voltage) == env.servo_interval
    assert updates[1].control_snapshot.target_gap == pytest.approx(50.0)
    assert sum(clock.sleep_calls) == pytest.approx(0.2, abs=1e-6)
    assert final_status.control_steps == 2


def test_realtime_session_caps_pace_to_measured_compute_throughput(
    env: WireEDMEnv,
) -> None:
    clock = ScriptedClock([0.0, 0.0, 0.0, 0.01, 0.02, 0.02, 0.02])
    controller = RuntimeController(RuntimeControlState(controller_type="fixed-servo"))

    session = RealtimeSession(
        env,
        controller,
        slowdown_factor=1.0,
        clock=clock.perf_counter,
        sleep=clock.sleep,
    )

    final_status = session.run(max_control_steps=1)

    assert final_status.slowdown_factor == pytest.approx(12.5, abs=1e-9)
    assert final_status.min_slowdown_factor == pytest.approx(12.5, abs=1e-9)
    assert final_status.max_sim_us_per_wall_second == pytest.approx(80_000.0, abs=1e-6)
    assert final_status.control_compute_wall_s == pytest.approx(0.02, abs=1e-9)
    assert clock.sleep_calls == []


def test_realtime_session_rebases_pacing_when_slowdown_changes(
    env: WireEDMEnv,
) -> None:
    clock = FakeClock()
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
    updates = []

    def on_control_step(update) -> None:
        updates.append(update)
        if len(updates) == 1:
            session.set_slowdown_factor(200.0)

    session = RealtimeSession(
        env,
        controller,
        slowdown_factor=100.0,
        on_control_step=on_control_step,
        clock=clock.perf_counter,
        sleep=clock.sleep,
    )

    final_status = session.run(max_control_steps=2)

    assert final_status.state == RealtimeSessionState.STOPPED
    assert len(updates) == 2
    assert sum(clock.sleep_calls) == pytest.approx(0.3, abs=1e-6)


def test_realtime_session_clamps_requested_speed_to_known_compute_cap(
    env: WireEDMEnv,
) -> None:
    clock = ScriptedClock([0.0, 0.0, 0.0, 0.01, 0.02, 0.02, 0.02, 0.02, 0.02])
    controller = RuntimeController(RuntimeControlState(controller_type="fixed-servo"))
    command_statuses = []

    def on_control_step(update) -> None:
        if not command_statuses:
            command_statuses.append(session.set_slowdown_factor(1.0))

    session = RealtimeSession(
        env,
        controller,
        slowdown_factor=20.0,
        on_control_step=on_control_step,
        clock=clock.perf_counter,
        sleep=clock.sleep,
    )

    final_status = session.run(max_control_steps=1)

    assert len(command_statuses) == 1
    assert command_statuses[0].slowdown_factor == pytest.approx(
        12.5, abs=1e-9
    )
    assert final_status.slowdown_factor == pytest.approx(
        12.5, abs=1e-9
    )


def test_realtime_session_pause_resume_and_stop(env: WireEDMEnv) -> None:
    controller = RuntimeController(RuntimeControlState(controller_type="fixed-servo"))
    first_update = threading.Event()
    second_update = threading.Event()
    updates = []

    def on_control_step(update) -> None:
        updates.append(update)
        if len(updates) == 1:
            session.pause()
            first_update.set()
        elif len(updates) == 2:
            session.stop()
            second_update.set()

    session = RealtimeSession(
        env,
        controller,
        slowdown_factor=0.001,
        on_control_step=on_control_step,
    )

    worker = threading.Thread(target=session.run, kwargs={"max_control_steps": None})
    worker.start()

    assert first_update.wait(timeout=2.0)

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if session.status().state == RealtimeSessionState.PAUSED:
            break
        time.sleep(0.01)
    else:
        pytest.fail("session did not transition to paused")

    session.resume()
    assert second_update.wait(timeout=2.0)

    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert session.status().state == RealtimeSessionState.STOPPED
    assert len(updates) == 2


def test_realtime_session_emits_intermediate_process_frames_at_visual_cadence(
    env: WireEDMEnv,
) -> None:
    clock = FakeClock()
    controller = RuntimeController(RuntimeControlState(controller_type="fixed-servo"))
    process_frames = []

    session = RealtimeSession(
        env,
        controller,
        slowdown_factor=1000.0,
        on_process_frame=process_frames.append,
        clock=clock.perf_counter,
        sleep=clock.sleep,
    )

    final_status = session.run(max_control_steps=1)

    assert final_status.state == RealtimeSessionState.STOPPED
    assert final_status.control_steps == 1
    assert len(process_frames) >= 50
    assert process_frames[0].process_state.time == 17
    assert process_frames[-1].process_state.time == env.servo_interval
    assert sum(clock.sleep_calls) == pytest.approx(1.0, abs=1e-6)


def test_realtime_session_streams_pulse_chunks_during_control_interval(
    env: WireEDMEnv,
) -> None:
    clock = FakeClock()
    controller = RuntimeController(RuntimeControlState(controller_type="fixed-servo"))
    pulse_chunks = []

    session = RealtimeSession(
        env,
        controller,
        slowdown_factor=1000.0,
        on_pulse_chunk=pulse_chunks.append,
        clock=clock.perf_counter,
        sleep=clock.sleep,
    )

    final_status = session.run(max_control_steps=1)

    assert final_status.state == RealtimeSessionState.STOPPED
    assert final_status.control_steps == 1
    assert len(pulse_chunks) >= 2
    assert pulse_chunks[0].base_time_us == 1
    assert all(len(chunk.voltage) > 0 for chunk in pulse_chunks)
    assert sum(len(chunk.voltage) for chunk in pulse_chunks) == env.servo_interval
    assert sum(clock.sleep_calls) == pytest.approx(1.0, abs=1e-6)


def test_realtime_session_compute_cap_ignores_pacing_sleep(
    env: WireEDMEnv,
) -> None:
    clock = FakeClock()
    controller = RuntimeController(RuntimeControlState(controller_type="fixed-servo"))

    session = RealtimeSession(
        env,
        controller,
        slowdown_factor=1000.0,
        clock=clock.perf_counter,
        sleep=clock.sleep,
    )

    final_status = session.run(max_control_steps=1)

    assert final_status.min_slowdown_factor == pytest.approx(12.5, abs=1e-9)
    assert final_status.max_sim_us_per_wall_second == pytest.approx(80_000.0, abs=1e-6)
    assert final_status.control_compute_wall_s == pytest.approx(0.0, abs=1e-12)
    assert sum(clock.sleep_calls) == pytest.approx(1.0, abs=1e-6)


def test_realtime_session_snapshots_refresh_wire_material_positions(
    env: WireEDMEnv,
) -> None:
    clock = FakeClock()
    controller = RuntimeController(RuntimeControlState(controller_type="fixed-servo"))

    session = RealtimeSession(
        env,
        controller,
        slowdown_factor=100.0,
        clock=clock.perf_counter,
        sleep=clock.sleep,
    )

    session._prepare_run()
    try:
        update, _ = session._advance_control_interval()
    finally:
        session.stop()

    expected_positions = env.wire._base_positions_mm + update.process_state.wire_position_offset_mm
    np.testing.assert_allclose(
        update.process_state.wire_material_positions_mm,
        expected_positions,
    )
