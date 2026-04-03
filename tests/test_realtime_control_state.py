from __future__ import annotations

import pytest

from wedm import WireEDMEnv
from wedm.realtime import RuntimeControlState, RuntimeController


@pytest.fixture
def env() -> WireEDMEnv:
    env = WireEDMEnv()
    env.reset(seed=123)
    env.state.workpiece_position = 70.0
    env.state.wire_position = 10.0
    env.state.voltage = 40.0
    return env


def test_gap_controller_uses_mutated_runtime_state(env: WireEDMEnv) -> None:
    state = RuntimeControlState(
        controller_type="gap",
        target_gap=5.0,
        generator_voltage=80.0,
        current_mode=7,
        on_time=2.0,
        off_time=33.0,
    )
    controller = RuntimeController(state)

    action = controller(env)
    assert action.servo == pytest.approx(5.5)
    assert action.generator_control.target_voltage == pytest.approx(80.0)
    assert action.generator_control.current_mode == 7

    state.set_param("target_gap", 50.0)
    state.set_param("generator_voltage", 91.0)
    state.set_param("current_mode", 17)
    state.set_param("on_time", 2.5)
    state.set_param("off_time", 17.0)

    updated_action = controller(env)
    assert updated_action.servo == pytest.approx(1.0)
    assert updated_action.generator_control.target_voltage == pytest.approx(91.0)
    assert updated_action.generator_control.current_mode == 17
    assert updated_action.generator_control.ON_time == pytest.approx(2.5)
    assert updated_action.generator_control.OFF_time == pytest.approx(17.0)


def test_voltage_controller_uses_mutated_target_and_generator_state(
    env: WireEDMEnv,
) -> None:
    state = RuntimeControlState(
        controller_type="voltage",
        target_avg_voltage=30.0,
        generator_voltage=80.0,
        current_mode=7,
        on_time=2.0,
        off_time=33.0,
    )
    controller = RuntimeController(state)

    action = controller(env, [40.0, 40.0])
    assert action.servo == pytest.approx(0.501)

    state.set_param("target_avg_voltage", 20.0)
    state.set_param("generator_voltage", 95.0)
    state.set_param("current_mode", 17)
    state.set_param("on_time", 3.0)
    state.set_param("off_time", 10.0)

    updated_action = controller(env, [40.0, 40.0])
    assert updated_action.servo == pytest.approx(1.003)
    assert updated_action.generator_control.target_voltage == pytest.approx(95.0)
    assert updated_action.generator_control.current_mode == 17
    assert updated_action.generator_control.ON_time == pytest.approx(3.0)
    assert updated_action.generator_control.OFF_time == pytest.approx(10.0)


def test_fixed_servo_controller_uses_mutated_servo(env: WireEDMEnv) -> None:
    state = RuntimeControlState(controller_type="fixed-servo", fixed_servo=0.25)
    controller = RuntimeController(state)

    assert controller(env).servo == pytest.approx(0.25)

    state.set_param("fixed_servo", -0.75)
    assert controller(env).servo == pytest.approx(-0.75)


def test_inactive_setpoint_updates_are_rejected() -> None:
    state = RuntimeControlState(controller_type="gap")

    with pytest.raises(ValueError, match="not active"):
        state.set_param("target_avg_voltage", 25.0)

    with pytest.raises(ValueError, match="restart-only"):
        state.set_param("controller_type", "voltage")

    with pytest.raises(KeyError, match="Unknown live control parameter"):
        state.set_param("missing_param", 1)
