from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .state import EDMState


def is_short_circuited(state: EDMState, dielectric_module: Optional = None) -> bool:
    """Checks if a short-circuit condition exists in the given state.

    Uses simple gap-based detection: gap < 10μm = short circuit.
    Also checks for explicit short circuit state.

    Args:
        state: The current EDMState object.
        dielectric_module: Deprecated parameter, kept for compatibility.

    Returns:
        True if a short-circuit condition exists, False otherwise.
    """
    # Check for explicit short circuit state
    if state.spark_status[0] == -1:
        return True

    # Use simple gap-based detection updated by ignition module
    return state.is_short_circuit


def get_gap(state: EDMState) -> float:
    """Calculate the gap between wire and workpiece.

    Args:
        state: The current EDMState object.

    Returns:
        Gap in micrometers (μm). Returns 0.0 if wire is at or past workpiece.
    """
    return max(0.0, state.workpiece_position - state.wire_position)
