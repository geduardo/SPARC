# src/edm_env/modules/ignition.py
from __future__ import annotations

import json
import math
from pathlib import Path
from dataclasses import dataclass
from numba import njit

from ..core.module import EDMModule
from ..core.state import EDMState
@njit(cache=False)
def _get_debris_short_probability_scalar(
    gap: float,
    debris_density: float,
    hard_short_gap: float,
    base_critical_density: float,
    gap_coefficient: float,
    max_critical_density: float,
    sigmoid_steepness: float,
) -> float:
    """Scalar debris-short probability helper for the compiled ignition path."""
    if gap < hard_short_gap:
        return 1.0

    critical_density = base_critical_density + gap_coefficient * gap
    if critical_density > max_critical_density:
        critical_density = max_critical_density

    exponent = -sigmoid_steepness * (debris_density - critical_density)
    if exponent > 500.0:
        return 0.0
    if exponent < -500.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(exponent))


@njit(cache=False)
def _roll_new_short_circuit_state(
    gap: float,
    dt: int,
    debris_density: float,
    debris_roll: float,
    random_roll: float,
    hard_short_gap: float,
    base_critical_density: float,
    gap_coefficient: float,
    max_critical_density: float,
    sigmoid_steepness: float,
    random_short_min_gap: float,
    random_short_max_gap: float,
    random_short_max_probability: float,
) -> int:
    """Return 0 for no short, 1 for debris short, and 2 for random short."""
    base_debris_prob = _get_debris_short_probability_scalar(
        gap,
        debris_density,
        hard_short_gap,
        base_critical_density,
        gap_coefficient,
        max_critical_density,
        sigmoid_steepness,
    )
    if base_debris_prob >= 1.0 or dt == 1:
        debris_short_prob = base_debris_prob
    else:
        debris_short_prob = 1.0 - math.pow(1.0 - base_debris_prob, dt)

    if gap >= random_short_max_gap:
        random_short_rate = 0.0
    elif gap <= random_short_min_gap:
        random_short_rate = random_short_max_probability
    else:
        gap_factor = 1.0 - (gap - random_short_min_gap) / (
            random_short_max_gap - random_short_min_gap
        )
        random_short_rate = gap_factor * random_short_max_probability

    random_short_prob = 1.0 - math.exp(-random_short_rate * dt)

    if debris_roll < debris_short_prob:
        return 1
    if random_roll < random_short_prob:
        return 2
    return 0


@njit(cache=False)
def _roll_new_debris_short_state(
    gap: float,
    dt: int,
    debris_density: float,
    debris_roll: float,
    hard_short_gap: float,
    base_critical_density: float,
    gap_coefficient: float,
    max_critical_density: float,
    sigmoid_steepness: float,
) -> bool:
    """Return whether a new debris-driven short should start."""
    base_debris_prob = _get_debris_short_probability_scalar(
        gap,
        debris_density,
        hard_short_gap,
        base_critical_density,
        gap_coefficient,
        max_critical_density,
        sigmoid_steepness,
    )
    if base_debris_prob >= 1.0 or dt == 1:
        return debris_roll < base_debris_prob
    debris_short_prob = 1.0 - math.pow(1.0 - base_debris_prob, dt)
    return debris_roll < debris_short_prob


@njit(cache=False)
def _advance_short_circuit_state(
    gap: float,
    dt: int,
    debris_density: float,
    random_short_remaining: int,
    debris_short_remaining: int,
    debris_roll: float,
    random_roll: float,
    hard_short_gap: float,
    base_critical_density: float,
    gap_coefficient: float,
    max_critical_density: float,
    sigmoid_steepness: float,
    debris_short_duration: int,
    random_short_duration: int,
    random_short_min_gap: float,
    random_short_max_gap: float,
    random_short_max_probability: float,
) -> tuple[int, int, bool]:
    """Advance short-circuit timers and evaluate new short events."""
    if random_short_remaining > 0:
        next_random_remaining = random_short_remaining - dt
        if next_random_remaining < 0:
            next_random_remaining = 0
        return next_random_remaining, debris_short_remaining, True

    if debris_short_remaining > 0:
        next_debris_remaining = debris_short_remaining - dt
        if next_debris_remaining < 0:
            next_debris_remaining = 0
        return random_short_remaining, next_debris_remaining, True

    base_debris_prob = _get_debris_short_probability_scalar(
        gap,
        debris_density,
        hard_short_gap,
        base_critical_density,
        gap_coefficient,
        max_critical_density,
        sigmoid_steepness,
    )
    if base_debris_prob >= 1.0:
        debris_short_prob = 1.0
    else:
        debris_short_prob = 1.0 - math.pow(1.0 - base_debris_prob, dt)

    if gap >= random_short_max_gap:
        random_short_rate = 0.0
    elif gap <= random_short_min_gap:
        random_short_rate = random_short_max_probability
    else:
        gap_factor = 1.0 - (gap - random_short_min_gap) / (
            random_short_max_gap - random_short_min_gap
        )
        random_short_rate = gap_factor * random_short_max_probability

    random_short_prob = 1.0 - math.exp(-random_short_rate * dt)

    if debris_roll < debris_short_prob:
        return random_short_remaining, debris_short_duration, True

    if random_roll < random_short_prob:
        return random_short_duration, debris_short_remaining, True

    return random_short_remaining, debris_short_remaining, False


@njit(cache=False)
def _get_ignition_probability_scalar(
    gap: float,
    rounded_gap: float,
    dt: int,
    log2_value: float,
    ignition_a_coeff: float,
    ignition_b_coeff: float,
    ignition_c_coeff: float,
) -> float:
    """Compute ignition probability with the same rounded-gap semantics as the cached path."""
    if gap > 25.0:
        return 0.0

    denominator = (
        ignition_a_coeff * rounded_gap * rounded_gap
        + ignition_b_coeff * rounded_gap
        + ignition_c_coeff
    )
    if denominator <= 1e-9:
        return 1.0

    hazard_rate = log2_value / denominator
    return 1.0 - math.exp(-hazard_rate * dt)


@njit(cache=False)
def _advance_discharge_state(
    spark_state: int,
    spark_location_mm: float,
    spark_duration: int,
    is_short_circuit: bool,
    current_voltage: float,
    target_voltage: float,
    peak_current: float,
    on_time: float,
    off_time: float,
    spark_voltage_factor: float,
    workpiece_height: float,
    ignition_probability: float,
    ignition_roll: float,
    spark_location_roll: float,
) -> tuple[int, float, int, float, float]:
    """Advance the ignition state machine using scalar compiled logic."""
    voltage = current_voltage
    current = 0.0

    if spark_state == 0:
        if is_short_circuit:
            return -1, math.nan, 0, voltage, peak_current

        voltage = target_voltage
        if ignition_roll < ignition_probability:
            return (
                1,
                spark_location_roll * workpiece_height,
                0,
                target_voltage * spark_voltage_factor,
                peak_current,
            )
        return 0, spark_location_mm, spark_duration, voltage, current

    if spark_state == 1:
        next_duration = spark_duration + 1
        if next_duration >= on_time:
            if not is_short_circuit:
                voltage = 0.0
            return -2, spark_location_mm, next_duration, voltage, 0.0

        if not is_short_circuit:
            voltage = target_voltage * spark_voltage_factor
        return 1, spark_location_mm, next_duration, voltage, peak_current

    if spark_state == -1:
        next_duration = spark_duration + 1
        if next_duration >= on_time:
            return -2, spark_location_mm, next_duration, voltage, 0.0
        return -1, spark_location_mm, next_duration, voltage, peak_current

    if spark_state == -2:
        next_duration = spark_duration + 1
        if next_duration >= (on_time + off_time):
            if not is_short_circuit:
                voltage = target_voltage
            return 0, math.nan, 0, voltage, 0.0

        if not is_short_circuit:
            voltage = 0.0
        return -2, spark_location_mm, next_duration, voltage, 0.0

    return spark_state, spark_location_mm, spark_duration, voltage, current


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
        self._ignition_prob_cache: dict[tuple[float, float], float] = {}  # (rounded_gap, dt) -> probability
        self.random_short_remaining = 0  # Remaining microseconds of random short
        self.debris_short_remaining = 0  # Remaining microseconds of debris short

        # Precompute constants
        self._log2 = math.log(2)
        self._dt_int = int(self.env.dt)
        self._hard_short_gap = float(self.params.hard_short_gap)
        self._base_critical_density = float(self.params.base_critical_density)
        self._gap_coefficient = float(self.params.gap_coefficient)
        self._max_critical_density = float(self.params.max_critical_density)
        self._sigmoid_steepness = float(self.params.sigmoid_steepness)
        self._debris_short_duration = int(self.params.debris_short_duration)
        self._random_short_duration = int(self.params.random_short_duration)
        self._random_short_min_gap = float(self.params.random_short_min_gap)
        self._random_short_max_gap = float(self.params.random_short_max_gap)
        self._random_short_max_probability = float(
            self.params.random_short_max_probability
        )
        self._random_short_enabled = self._random_short_max_probability > 0.0

        # ── Current Mapping Data ──
        self.currents_data = self._load_currents_data()
        self._peak_current_by_mode = {
            mode: float(info["Current"]) for mode, info in self.currents_data.items()
        }
        self._resolved_peak_current_lookup: dict[str, float] = {}
        self._default_peak_current = self._peak_current_by_mode[
            self.params.default_current_mode
        ]

        # ── Caching for Performance ──
        self._cached_current_mode: str | None = None
        self._cached_current_value: float = self._default_peak_current
        self._cached_generator_signature: tuple[object, ...] | None = None
        self._cached_generator_settings = (
            float(self.params.default_target_voltage),
            float(self._default_peak_current),
            float(self.params.default_on_time),
            float(self.params.default_off_time),
        )

    def reset(self, state: EDMState) -> None:
        """Clear episode-local discharge timers and caches."""
        self._ignition_prob_cache.clear()
        self.random_short_remaining = 0
        self.debris_short_remaining = 0
        self._refresh_current_mode_lut()
        self._cached_current_mode = None
        self._cached_current_value = self._default_peak_current
        self._cached_generator_signature = None
        self._cached_generator_settings = (
            float(self.params.default_target_voltage),
            float(self._default_peak_current),
            float(self.params.default_on_time),
            float(self.params.default_off_time),
        )
        state.current = 0.0
        state.is_short_circuit = False
        state.spark_status = [0, None, 0]

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
        """Get actual current value from current mode with a crater-backed LUT."""
        if not self._resolved_peak_current_lookup:
            self._refresh_current_mode_lut()

        resolved_current_mode = current_mode
        peak_current = self._resolved_peak_current_lookup.get(current_mode)
        if peak_current is None:
            resolved_current_mode = self.env.default_current_mode
            peak_current = self._default_peak_current

        if resolved_current_mode != self._cached_current_mode:
            self._cached_current_value = peak_current
            self._cached_current_mode = resolved_current_mode

        return self._cached_current_value

    def _resolve_generator_settings(
        self, state: EDMState
    ) -> tuple[float, float, float, float]:
        """Resolve generator settings once and reuse them until control values change."""
        signature = (
            state.target_voltage,
            state.current_mode,
            state.ON_time,
            state.OFF_time,
        )
        if signature != self._cached_generator_signature:
            target_voltage = self.params.default_target_voltage
            if state.target_voltage is not None:
                target_voltage = float(state.target_voltage)

            on_time = self.params.default_on_time
            if state.ON_time is not None:
                on_time = float(state.ON_time)

            off_time = self.params.default_off_time
            if state.OFF_time is not None:
                off_time = float(state.OFF_time)

            peak_current = self._get_current_from_mode(state.current_mode)

            self._cached_generator_signature = signature
            self._cached_generator_settings = (
                float(target_voltage),
                float(peak_current),
                float(on_time),
                float(off_time),
            )

        return self._cached_generator_settings

    def _refresh_current_mode_lut(self) -> None:
        """Refresh crater-backed peak-current lookup after env current modes are known."""
        valid_modes = getattr(self.env, "valid_current_modes", self.currents_data.keys())
        self._resolved_peak_current_lookup = {
            mode: self._peak_current_by_mode[mode]
            for mode in valid_modes
            if mode in self._peak_current_by_mode
        }
        self._default_peak_current = self._peak_current_by_mode[
            self.env.default_current_mode
        ]

    def _get_debris_short_probability(self, gap: float, debris_density: float) -> float:
        """Calculate debris-driven short probability for the current gap/density."""
        return _get_debris_short_probability_scalar(
            gap,
            debris_density,
            self.params.hard_short_gap,
            self.params.base_critical_density,
            self.params.gap_coefficient,
            self.params.max_critical_density,
            self.params.sigmoid_steepness,
        )

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #
    def update(self, state: EDMState) -> None:
        """Advance the ignition state machine with compiled scalar helpers."""
        self._update_short_circuit_detection(state)
        current_voltage = 0.0 if state.voltage is None else float(state.voltage)
        if state.is_short_circuit:
            current_voltage = 0.0

        target_voltage, peak_current, on_time, off_time = (
            self._resolve_generator_settings(state)
        )

        spark_state = int(state.spark_status[0])
        spark_location = (
            math.nan if state.spark_status[1] is None else float(state.spark_status[1])
        )
        spark_duration = int(state.spark_status[2])

        ignition_probability = 0.0
        ignition_roll = 1.0
        spark_location_roll = 0.0
        if spark_state == 0 and not state.is_short_circuit:
            gap = state.workpiece_position - state.wire_position
            rounded_gap = round(gap, 2)
            ignition_probability = _get_ignition_probability_scalar(
                gap,
                rounded_gap,
                int(self.env.dt),
                self._log2,
                self.params.ignition_a_coeff,
                self.params.ignition_b_coeff,
                self.params.ignition_c_coeff,
            )
            ignition_roll = float(self.env.np_random.random())
            if ignition_roll < ignition_probability:
                spark_location_roll = float(self.env.np_random.random())

        (
            next_spark_state,
            next_spark_location,
            next_spark_duration,
            next_voltage,
            next_current,
        ) = _advance_discharge_state(
            spark_state,
            spark_location,
            spark_duration,
            bool(state.is_short_circuit),
            current_voltage,
            target_voltage,
            peak_current,
            on_time,
            off_time,
            self.params.spark_voltage_factor,
            self.env.config.workpiece_height,
            ignition_probability,
            ignition_roll,
            spark_location_roll,
        )

        state.spark_status = [
            int(next_spark_state),
            None if math.isnan(next_spark_location) else float(next_spark_location),
            int(next_spark_duration),
        ]
        state.voltage = float(next_voltage)
        state.current = float(next_current)

    def _update_short_circuit_detection(self, state: EDMState) -> None:
        """Advance short-circuit timers and roll new short events when needed."""
        random_remaining = self.random_short_remaining
        if random_remaining > 0:
            random_remaining -= self._dt_int
            if random_remaining < 0:
                random_remaining = 0
            self.random_short_remaining = random_remaining
            state.is_short_circuit = True
            return

        debris_remaining = self.debris_short_remaining
        if debris_remaining > 0:
            debris_remaining -= self._dt_int
            if debris_remaining < 0:
                debris_remaining = 0
            self.debris_short_remaining = debris_remaining
            state.is_short_circuit = True
            return

        gap = state.workpiece_position - state.wire_position
        if gap < 0.0:
            gap = 0.0

        rolls = self.env.np_random.random(2)
        debris_roll = float(rolls[0])
        debris_density = float(state.debris_density)

        if self._random_short_enabled:
            outcome = _roll_new_short_circuit_state(
                gap,
                self._dt_int,
                debris_density,
                debris_roll,
                float(rolls[1]),
                self._hard_short_gap,
                self._base_critical_density,
                self._gap_coefficient,
                self._max_critical_density,
                self._sigmoid_steepness,
                self._random_short_min_gap,
                self._random_short_max_gap,
                self._random_short_max_probability,
            )
            if outcome == 1:
                self.debris_short_remaining = self._debris_short_duration
                state.is_short_circuit = True
                return
            if outcome == 2:
                self.random_short_remaining = self._random_short_duration
                state.is_short_circuit = True
                return
        else:
            is_short_circuit = _roll_new_debris_short_state(
                gap,
                self._dt_int,
                debris_density,
                debris_roll,
                self._hard_short_gap,
                self._base_critical_density,
                self._gap_coefficient,
                self._max_critical_density,
                self._sigmoid_steepness,
            )
            if is_short_circuit:
                self.debris_short_remaining = self._debris_short_duration
                state.is_short_circuit = True
                return

        state.is_short_circuit = False

    def _get_target_voltage(self, state: EDMState) -> float:
        """Get target voltage with default."""
        if state.target_voltage is None:
            return self.params.default_target_voltage
        return state.target_voltage

    def _get_peak_current(self, state: EDMState) -> float:
        """Get peak current for current mode."""
        return self._get_current_from_mode(state.current_mode)

    def _get_on_time(self, state: EDMState) -> float:
        """Get ON time with default."""
        if state.ON_time is None:
            return self.params.default_on_time
        return state.ON_time

    def _get_off_time(self, state: EDMState) -> float:
        """Get OFF time with default."""
        if state.OFF_time is None:
            return self.params.default_off_time
        return state.OFF_time

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _get_ignition_probability(self, state: EDMState) -> float:
        """Calculate ignition probability with rounded-gap caching."""
        dt = int(self.env.dt)
        gap = state.workpiece_position - state.wire_position

        if gap > 25.0:
            return 0.0

        rounded_gap = round(gap, 2)
        cache_key = (rounded_gap, dt)
        if cache_key in self._ignition_prob_cache:
            return self._ignition_prob_cache[cache_key]

        prob = _get_ignition_probability_scalar(
            gap,
            rounded_gap,
            dt,
            self._log2,
            self.params.ignition_a_coeff,
            self.params.ignition_b_coeff,
            self.params.ignition_c_coeff,
        )
        self._ignition_prob_cache[cache_key] = prob
        return prob

    def get_lambda(self, state: EDMState) -> float:
        """
        Calculate ignition probability based on gap.
        Kept for backward compatibility and analysis.
        """
        if state.is_short_circuit:
            raise ValueError("get_lambda called during short circuit condition.")

        gap = state.workpiece_position - state.wire_position
        
        # λ = ln(2) / (a*gap² + b*gap + c)
        denominator = (
            self.params.ignition_a_coeff * gap**2
            + self.params.ignition_b_coeff * gap
            + self.params.ignition_c_coeff
        )
        
        if denominator <= 1e-9:
            return float('inf')
            
        return self._log2 / denominator

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
