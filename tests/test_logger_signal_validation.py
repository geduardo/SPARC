import pytest

from wedm.core.state import EDMState
from wedm.utils.logger import SimulationLogger


def _memory_logger_config(signals):
    return {
        "signals_to_log": signals,
        "log_frequency": {"type": "every_step"},
        "backend": {"type": "memory"},
    }


def test_logger_accepts_edm_state_signal():
    logger = SimulationLogger(_memory_logger_config(["workpiece_position"]))
    state = EDMState(workpiece_position=12.5)

    logger.collect(state)

    assert logger.get_data()["workpiece_position"] == [12.5]


def test_logger_accepts_supported_derived_signal():
    logger = SimulationLogger(_memory_logger_config(["gap_um"]))
    state = EDMState(workpiece_position=30.0, wire_position=17.0)

    logger.collect(state)

    assert logger.get_data()["gap_um"] == [13.0]


def test_logger_rejects_unknown_signal_name():
    with pytest.raises(ValueError, match="Unknown signals_to_log entries: gap_width"):
        SimulationLogger(_memory_logger_config(["gap_width"]))


def test_logger_error_includes_typo_hint():
    with pytest.raises(ValueError) as exc_info:
        SimulationLogger(_memory_logger_config(["workpiece_postion"]))

    assert "did you mean workpiece_position" in str(exc_info.value)
