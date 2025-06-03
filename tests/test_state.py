"""Tests for EDM State."""

import numpy as np
from wedm.core.state import EDMState


class TestEDMState:
    """Test EDM State functionality."""

    def test_state_creation(self):
        """Test state can be created."""
        state = EDMState()
        assert state is not None
        assert state.time == 0
        assert state.wire_position == 0.0
        assert state.workpiece_position == 0.0

    def test_state_attributes(self):
        """Test state attributes can be set."""
        state = EDMState()

        state.wire_position = 10.0
        state.workpiece_position = 15.0
        state.target_position = 100.0

        assert state.wire_position == 10.0
        assert state.workpiece_position == 15.0
        assert state.target_position == 100.0
