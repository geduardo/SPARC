"""Regression coverage for cross-episode reset isolation."""

import numpy as np

from wedm import EnvironmentConfig, WireEDMEnv


def _make_env() -> WireEDMEnv:
    """Use a fast control cadence and ignition-friendly gap for episode checks."""
    return WireEDMEnv(config=EnvironmentConfig(initial_gap=15.0, servo_interval=1))


def _build_action(
    *,
    servo: float = 0.25,
    target_voltage: float = 90.0,
    current_mode: int = 5,
    on_time: float = 3.0,
    off_time: float = 20.0,
) -> dict:
    return {
        "servo": np.array([servo], dtype=np.float32),
        "generator_control": {
            "target_voltage": np.array([target_voltage], dtype=np.float32),
            "current_mode": np.array([current_mode], dtype=np.int32),
            "ON_time": np.array([on_time], dtype=np.float32),
            "OFF_time": np.array([off_time], dtype=np.float32),
        },
    }


def _rounded(value: float | None, *, digits: int = 12) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _reset_snapshot(env: WireEDMEnv) -> dict:
    return {
        "time": env.state.time,
        "workpiece_position": _rounded(env.state.workpiece_position),
        "wire_position": _rounded(env.state.wire_position),
        "wire_velocity": _rounded(env.state.wire_velocity),
        "target_voltage": _rounded(env.state.target_voltage),
        "current_mode": env.state.current_mode,
        "on_time": _rounded(env.state.ON_time),
        "off_time": _rounded(env.state.OFF_time),
        "voltage": _rounded(env.state.voltage),
        "current": _rounded(env.state.current),
        "spark_status": (
            int(env.state.spark_status[0]),
            _rounded(env.state.spark_status[1]),
            int(env.state.spark_status[2]),
        ),
        "debris_volume": _rounded(env.state.debris_volume),
        "debris_density": _rounded(env.state.debris_density),
        "last_crater_volume": _rounded(env.state.last_crater_volume),
        "wire_temperature_mean": _rounded(np.mean(env.state.wire_temperature)),
        "wire_damage_sum": _rounded(np.sum(env.state.wire_damage)),
        "wire_max_damage": _rounded(env.state.wire_max_damage),
        "random_short_remaining": env.ignition.random_short_remaining,
        "debris_short_remaining": env.ignition.debris_short_remaining,
        "crater_count": len(env.material.crater_volumes_um3),
        "prev_accel": _rounded(env.mechanics.prev_accel),
    }


def _episode_trace(
    env: WireEDMEnv, *, seed: int, steps: int, action: dict
) -> list[tuple]:
    env.reset(seed=seed)
    env.state.time_since_servo = env.servo_interval

    trace = []
    for _ in range(steps):
        env.step(action)
        trace.append(
            (
                env.state.time,
                _rounded(env.state.workpiece_position),
                _rounded(env.state.wire_position),
                _rounded(env.state.wire_velocity),
                _rounded(env.state.current),
                _rounded(env.state.voltage),
                (
                    int(env.state.spark_status[0]),
                    _rounded(env.state.spark_status[1]),
                    int(env.state.spark_status[2]),
                ),
                _rounded(env.state.debris_volume),
                _rounded(env.state.debris_density),
                _rounded(env.state.last_crater_volume),
                _rounded(np.mean(env.state.wire_temperature)),
                _rounded(env.state.wire_max_damage),
                env.ignition.random_short_remaining,
                env.ignition.debris_short_remaining,
                len(env.material.crater_volumes_um3),
            )
        )

    return trace


class TestResetIsolation:
    def test_reset_is_idempotent_after_multiple_dirty_episodes(self):
        """Repeated resets should always rebuild the same clean episode baseline."""
        env = _make_env()
        dirty_action = _build_action()

        env.reset()
        baseline = _reset_snapshot(env)

        for _ in range(3):
            env.state.time_since_servo = env.servo_interval
            for _ in range(40):
                env.step(dirty_action)

            env.reset()
            assert _reset_snapshot(env) == baseline

    def test_same_seed_replays_episode_on_reused_environment(self):
        """Reseeding should reproduce the same episode even after divergent history."""
        env = _make_env()
        reference_action = _build_action()
        dirty_action = _build_action(
            servo=-0.75,
            target_voltage=70.0,
            current_mode=17,
            on_time=4.0,
            off_time=5.0,
        )

        reference_trace = _episode_trace(
            env, seed=123, steps=60, action=reference_action
        )

        _episode_trace(env, seed=999, steps=80, action=dirty_action)

        assert (
            _episode_trace(env, seed=123, steps=60, action=reference_action)
            == reference_trace
        )

    def test_reused_env_matches_fresh_env_after_dirty_prior_episode(self):
        """A reused env should behave like a fresh env once the new seed is applied."""
        reference_action = _build_action()
        dirty_action = _build_action(
            servo=-0.5,
            target_voltage=75.0,
            current_mode=17,
            on_time=5.0,
            off_time=10.0,
        )

        fresh_env = _make_env()
        reused_env = _make_env()

        fresh_trace = _episode_trace(
            fresh_env, seed=321, steps=50, action=reference_action
        )
        _episode_trace(reused_env, seed=999, steps=90, action=dirty_action)

        assert (
            _episode_trace(reused_env, seed=321, steps=50, action=reference_action)
            == fresh_trace
        )
