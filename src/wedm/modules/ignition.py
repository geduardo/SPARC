# src/edm_env/modules/ignition.py
from __future__ import annotations

import json
import numpy as np
from pathlib import Path
from dataclasses import dataclass

from ..core.module import EDMModule
from ..core.state import EDMState
from ..core.state_utils import is_short_circuited


# ──────────────────────────────────────────────────────────────────────────────
# Ignition Module Parameters - Defined within module
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class IgnitionModuleParameters:
    """Ignition module specific parameters."""

    # ── Critical Debris Short Circuit Model ──
    base_critical_density: float = (
        0.3  # Critical debris density at zero gap [dimensionless]
    )
    gap_coefficient: float = 0.02  # How gap affects critical density [per μm]
    max_critical_density: float = 0.95  # Maximum critical density [dimensionless]
    hard_short_gap: float = 2.0  # Gap for guaranteed short circuit [μm]

    # ── Sigmoid Short Circuit Model ──
    sigmoid_steepness: float = 500.0  # Steepness of sigmoid transition [dimensionless]

    # ── Short Circuit Duration ──
    debris_short_duration: int = 50  # Duration of debris-based shorts [μs]

    # ── Random Short Circuit Model ──
    random_short_duration: int = 100  # Duration of random shorts [μs]
    random_short_min_gap: float = 2.0  # Gap below which probability is maximum [μm]
    random_short_max_gap: float = 50.0  # Gap above which probability is zero [μm]
    random_short_max_probability: float = (
        0.000  # Maximum probability per microsecond [dimensionless]
    )

    # ── Ignition Probability Model ──
    ignition_a_coeff: float = 0.48  # Coefficient 'a' in ignition probability formula
    ignition_b_coeff: float = -3.69  # Coefficient 'b' in ignition probability formula
    ignition_c_coeff: float = 14.05  # Coefficient 'c' in ignition probability formula

    # ── Default Generator Settings ──
    default_target_voltage: float = 80.0  # [V] Default target voltage
    default_on_time: float = 3.0  # [μs] Default ON time
    default_off_time: float = 80.0  # [μs] Default OFF time
    default_current_mode: str = "I5"  # Default current mode

    # ── Voltage Drop During Spark ──
    spark_voltage_factor: float = (
        0.3  # Factor by which voltage drops during spark [dimensionless]
    )


class IgnitionModule(EDMModule):
    """Stochastic plasma-channel ignition model with critical debris short circuit detection."""

    def __init__(
        self,
        env,
        parameters: IgnitionModuleParameters = None,
    ):
        super().__init__(env)

        # ── Module Parameters ──
        self.params = parameters or IgnitionModuleParameters()

        # ── Internal State ──
        self.lambda_cache: dict[float, float] = {}
        self.random_short_remaining = 0  # Remaining microseconds of random short
        self.debris_short_remaining = 0  # Remaining microseconds of debris short

        # ── Current Mapping Data ──
        self.currents_data = self._load_currents_data()

        # ── Caching for Performance ──
        self._cached_current_mode: str | None = None
        self._cached_current_value: float = 60.0  # Default to I5 current

    def _load_currents_data(self) -> dict:
        """Load current mode mappings from currents.json."""
        # Get the path relative to this module
        current_dir = Path(__file__).parent
        json_path = current_dir / "currents.json"

        try:
            with open(json_path, "r") as f:
                data = json.load(f)
            return data
        except FileNotFoundError:
            raise FileNotFoundError(f"Could not find currents data file at {json_path}")

    def _get_current_from_mode(self, current_mode: str | None) -> float:
        """Get actual current value from current mode with caching."""
        # Only recalculate if current_mode has changed
        if current_mode != self._cached_current_mode:
            if current_mode is None:
                current_mode = self.params.default_current_mode

            # Get actual current from current mode (0-18 maps to I1-I19)
            if current_mode not in self.currents_data:
                # Fallback to default if invalid mode
                current_mode = self.params.default_current_mode

            self._cached_current_value = self.currents_data[current_mode]["Current"]
            self._cached_current_mode = current_mode

        return self._cached_current_value

    def _get_debris_short_probability(self, gap: float, debris_density: float) -> float:
        """
        Calculate short circuit probability based on debris density using sigmoid function.

        Returns probability between 0 and 1, with sigmoid centered at critical density.
        Hard short circuit for very small gaps still applies.

        The sigmoid function: P = 1 / (1 + exp(-k * (ρ - ρ_crit)))
        where k is the steepness parameter.
        """
        # Hard short circuit for very small gaps
        if gap < self.params.hard_short_gap:
            return 1.0

        # Calculate critical debris density for this gap
        critical_density = (
            self.params.base_critical_density + self.params.gap_coefficient * gap
        )
        critical_density = min(critical_density, self.params.max_critical_density)

        # Calculate sigmoid probability
        # P = 1 / (1 + exp(-k * (ρ - ρ_crit)))
        delta_density = debris_density - critical_density
        exponent = -self.params.sigmoid_steepness * delta_density

        # Prevent overflow for very large negative exponents
        if exponent > 500:
            return 0.0
        elif exponent < -500:
            return 1.0
        else:
            return 1.0 / (1.0 + np.exp(exponent))

    def _detect_critical_debris_short(self, gap: float, debris_density: float) -> bool:
        """
        Detect short circuit based on critical debris density model.

        Short circuit occurs when:
        1. Gap < hard_short_gap (physical contact), OR
        2. Debris density exceeds critical value for the current gap

        Critical density increases linearly with gap:
        ρ_crit = base_critical_density + gap_coefficient * gap
        """
        # Hard short circuit for very small gaps
        if gap < self.params.hard_short_gap:
            return True

        # Calculate critical debris density for this gap
        critical_density = (
            self.params.base_critical_density + self.params.gap_coefficient * gap
        )
        critical_density = min(critical_density, self.params.max_critical_density)

        # Short circuit if debris exceeds critical density
        return debris_density > critical_density

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #
    def update(self, state: EDMState) -> None:
        """Update ignition state with clear, simple logic."""

        # Step 1: Update short circuit detection with debris consideration
        self._update_short_circuit_detection(state)

        # Step 2: Force voltage to 0 if short circuit
        if state.is_short_circuit:
            state.voltage = 0

        # Step 3: Handle state machine
        spark_state = state.spark_status[0]

        if spark_state == 0:
            self._handle_idle_state(state)
        elif spark_state == 1:
            self._handle_spark_state(state)
        elif spark_state == -1:
            self._handle_short_state(state)
        elif spark_state == -2:
            self._handle_rest_state(state)

    def _update_short_circuit_detection(self, state: EDMState) -> None:
        """Update short circuit flag based on gap and debris density using sigmoid probability."""
        gap = max(0.0, state.workpiece_position - state.wire_position)

        # Get debris density from state (default to 0 if not available)
        debris_density = getattr(state, "debris_density", 0.0)

        # Check for active short circuits first (either type)
        if self.random_short_remaining > 0:
            self.random_short_remaining -= 1
            state.is_short_circuit = True
            return

        if self.debris_short_remaining > 0:
            self.debris_short_remaining -= 1
            state.is_short_circuit = True
            return

        # Calculate probabilities for new short circuits
        # Use sigmoid model for debris-based short circuit probability
        debris_short_prob = self._get_debris_short_probability(gap, debris_density)

        # Check for random gap-dependent short circuit
        # Linear probability: 0% at gap > max_gap, max_probability at gap < min_gap, linear in between
        if gap >= self.params.random_short_max_gap:
            random_short_prob = 0.0
        elif gap <= self.params.random_short_min_gap:
            random_short_prob = self.params.random_short_max_probability
        else:
            # Linear interpolation between max_probability and 0%
            gap_factor = 1.0 - (gap - self.params.random_short_min_gap) / (
                self.params.random_short_max_gap - self.params.random_short_min_gap
            )
            random_short_prob = gap_factor * self.params.random_short_max_probability

        # Roll for debris short circuit
        if self.env.np_random.random() < debris_short_prob:
            self.debris_short_remaining = self.params.debris_short_duration
            state.is_short_circuit = True
            return

        # Roll for random short circuit
        if self.env.np_random.random() < random_short_prob:
            self.random_short_remaining = self.params.random_short_duration
            state.is_short_circuit = True
            return

        # No short circuit
        state.is_short_circuit = False

    def _handle_idle_state(self, state: EDMState) -> None:
        """Handle idle state (state 0)."""
        state.current = 0

        if state.is_short_circuit:
            # Short circuit during idle → deliver pulse
            state.spark_status = [-1, None, 0]
            state.current = self._get_peak_current(state)
        else:
            # Normal idle → set voltage and check for ignition
            state.voltage = self._get_target_voltage(state)

            if self._should_ignite(state):
                # Start normal spark
                spark_location = self.env.np_random.uniform(
                    0, self.env.config.workpiece_height
                )
                state.spark_status = [1, spark_location, 0]
                state.voltage = (
                    self._get_target_voltage(state) * self.params.spark_voltage_factor
                )
                state.current = self._get_peak_current(state)

    def _handle_spark_state(self, state: EDMState) -> None:
        """Handle active spark state (state 1)."""
        duration = state.spark_status[2] + 1
        state.spark_status[2] = duration

        if duration >= self._get_on_time(state):
            # Spark finished → go to rest
            state.spark_status[0] = -2
            state.current = 0
            if not state.is_short_circuit:
                state.voltage = 0
        else:
            # Continue spark
            state.current = self._get_peak_current(state)
            if not state.is_short_circuit:
                state.voltage = (
                    self._get_target_voltage(state) * self.params.spark_voltage_factor
                )

    def _handle_short_state(self, state: EDMState) -> None:
        """Handle short circuit pulse state (state -1)."""
        duration = state.spark_status[2] + 1
        state.spark_status[2] = duration

        if duration >= self._get_on_time(state):
            # Short pulse finished → go to rest
            state.spark_status[0] = -2
            state.current = 0
        else:
            # Continue short pulse
            state.current = self._get_peak_current(state)

    def _handle_rest_state(self, state: EDMState) -> None:
        """Handle rest/off state (state -2)."""
        duration = state.spark_status[2] + 1
        state.spark_status[2] = duration

        total_cycle_time = self._get_on_time(state) + self._get_off_time(state)

        if duration >= total_cycle_time:
            # Rest finished → back to idle
            state.spark_status = [0, None, 0]
            state.current = 0
            if not state.is_short_circuit:
                state.voltage = self._get_target_voltage(state)
        else:
            # Continue rest
            state.current = 0
            if not state.is_short_circuit:
                state.voltage = 0

    def _should_ignite(self, state: EDMState) -> bool:
        """Check if normal ignition should occur."""
        if state.is_short_circuit:
            return False

        ignition_probability = self.get_lambda(state)
        return self.env.np_random.random() < ignition_probability

    def _get_target_voltage(self, state: EDMState) -> float:
        """Get target voltage with default."""
        return state.target_voltage or self.params.default_target_voltage

    def _get_peak_current(self, state: EDMState) -> float:
        """Get peak current for current mode."""
        return self._get_current_from_mode(state.current_mode)

    def _get_on_time(self, state: EDMState) -> float:
        """Get ON time with default."""
        return state.ON_time or self.params.default_on_time

    def _get_off_time(self, state: EDMState) -> float:
        """Get OFF time with default."""
        return state.OFF_time or self.params.default_off_time

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def get_lambda(self, state: EDMState) -> float:
        """Calculate ignition probability based on gap."""
        if state.is_short_circuit:
            raise ValueError("get_lambda called during short circuit condition.")

        gap = state.workpiece_position - state.wire_position

        if gap not in self.lambda_cache:
            # λ = ln(2) / (a*gap² + b*gap + c)
            denominator = (
                self.params.ignition_a_coeff * gap**2
                + self.params.ignition_b_coeff * gap
                + self.params.ignition_c_coeff
            )
            self.lambda_cache[gap] = np.log(2) / denominator

        return self.lambda_cache[gap]

    def get_critical_density_for_gap(self, gap: float) -> float:
        """
        Get the critical debris density for a given gap.
        Useful for monitoring and debugging.
        """
        if gap < self.params.hard_short_gap:
            return 0.0  # Any debris density causes short

        critical_density = (
            self.params.base_critical_density + self.params.gap_coefficient * gap
        )
        return min(critical_density, self.params.max_critical_density)

    def get_debris_short_probability(self, gap: float, debris_density: float) -> float:
        """
        Public interface to get debris short circuit probability.
        Useful for monitoring and debugging.
        """
        return self._get_debris_short_probability(gap, debris_density)

    def get_short_circuit_status(self) -> dict:
        """
        Get detailed short circuit status.
        Returns dict with type of short circuit and remaining duration.
        """
        return {
            "has_random_short": self.random_short_remaining > 0,
            "random_short_remaining_us": self.random_short_remaining,
            "has_debris_short": self.debris_short_remaining > 0,
            "debris_short_remaining_us": self.debris_short_remaining,
            "total_short_remaining_us": max(
                self.random_short_remaining, self.debris_short_remaining
            ),
        }
