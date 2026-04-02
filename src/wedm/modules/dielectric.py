from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numba import njit

from ..core.module import EDMModule
from ..core.state import EDMState


@dataclass
class DielectricModuleParameters:
    """Dielectric module specific parameters."""

    base_flow_rate: float = 100.0
    debris_removal_efficiency: float = 0.01
    debris_obstruction_coeff: float = 1.0
    reference_gap: float = 25.0
    dielectric_temperature: float = 293.15
    ion_channel_duration: int = 6


@njit(cache=True, fastmath=True)
def fast_exp(x: float) -> float:
    """Fast approximation of exp(-x) for x >= 0."""
    if x < 0.5:
        return (1.0 - 0.5 * x) / (1.0 + 0.5 * x)
    return np.exp(-x)


@njit(cache=True, fastmath=True)
def advance_dielectric_state(
    workpiece_position_um: float,
    wire_position_um: float,
    spark_state: int,
    spark_duration: int,
    spark_location_mm: float,
    last_crater_volume: float,
    debris_volume: float,
    cached_gap_um: float,
    cached_debris_density: float,
    cached_flow_condition: float,
    ionized_channel_location_mm: float,
    ionized_channel_duration: int,
    cavity_volume_coeff: float,
    reference_gap: float,
    debris_obstruction_coeff: float,
    debris_removal_per_us: float,
    ion_channel_duration_param: int,
) -> tuple:
    """Advance dielectric debris, flow, and ion-channel state."""
    gap_um = workpiece_position_um - wire_position_um
    if gap_um < 0.001:
        gap_um = 0.001

    gap_mm = gap_um * 0.001
    cavity_volume = cavity_volume_coeff * gap_mm

    is_fresh_discharge = (
        spark_state == 1 or spark_state == -1
    ) and spark_duration == 0
    if is_fresh_discharge and last_crater_volume > 0.0:
        debris_volume += last_crater_volume
        ionized_channel_location_mm = spark_location_mm
        ionized_channel_duration = ion_channel_duration_param

    if cavity_volume > 0.0:
        debris_density = debris_volume / cavity_volume
        if debris_density > 1.0:
            debris_density = 1.0
    else:
        debris_density = 0.0

    if (
        abs(gap_um - cached_gap_um) > 0.01
        or abs(debris_density - cached_debris_density) > 0.001
    ):
        gap_factor = (gap_um / reference_gap) ** 3
        if gap_factor > 1.0:
            gap_factor = 1.0

        debris_factor = fast_exp(debris_obstruction_coeff * debris_density)
        flow_condition = gap_factor * debris_factor
        cached_gap_um = gap_um
        cached_debris_density = debris_density
        cached_flow_condition = flow_condition
    else:
        flow_condition = cached_flow_condition

    if flow_condition > 0.001 and debris_volume > 0.001:
        debris_removed = debris_removal_per_us * flow_condition
        debris_volume -= debris_removed
        if debris_volume < 0.0:
            debris_volume = 0.0

    if ionized_channel_duration > 0:
        ionized_channel_duration -= 1

    return (
        debris_volume,
        debris_density,
        cavity_volume,
        flow_condition,
        cached_gap_um,
        cached_debris_density,
        cached_flow_condition,
        ionized_channel_location_mm,
        ionized_channel_duration,
    )


class DielectricModule(EDMModule):
    """Debris tracking and dielectric flow model for Wire EDM."""

    def __init__(
        self,
        env,
        parameters: DielectricModuleParameters = None,
    ):
        super().__init__(env)
        self.params = parameters or DielectricModuleParameters()

        self.wire_radius = env.config.wire_diameter / 2.0
        self.workpiece_height = env.config.workpiece_height

        self.cavity_volume_coeff = np.pi * self.wire_radius * self.workpiece_height
        self.debris_removal_per_us = (
            self.params.debris_removal_efficiency * self.params.base_flow_rate * 1e-6
        )

        self.debris_volume = 0.0
        self.cavity_volume = 0.0
        self.debris_density = 0.0
        self.flow_condition = 0.0

        self.ion_channel = None

        self._last_gap_um = -1.0
        self._last_debris_density = -1.0
        self._last_flow_condition = 0.0

    def reset(self, state: EDMState) -> None:
        """Clear episode-local debris state and caches."""
        self.reset_debris()
        state.dielectric_temperature = self.params.dielectric_temperature
        state.debris_volume = 0.0
        state.debris_density = 0.0
        state.cavity_volume = 0.0
        state.flow_rate = 0.0
        state.debris_concentration = 0.0
        state.dielectric_flow_rate = 0.0
        state.ionized_channel = None

    def update(self, state: EDMState) -> None:
        """Advance dielectric debris and flow state."""
        state.dielectric_temperature = self.params.dielectric_temperature

        ionized_channel_location_mm = (
            float("nan") if self.ion_channel is None else float(self.ion_channel[0])
        )
        ionized_channel_duration = (
            0 if self.ion_channel is None else int(self.ion_channel[1])
        )

        (
            self.debris_volume,
            self.debris_density,
            self.cavity_volume,
            self.flow_condition,
            self._last_gap_um,
            self._last_debris_density,
            self._last_flow_condition,
            ionized_channel_location_mm,
            ionized_channel_duration,
        ) = advance_dielectric_state(
            state.workpiece_position,
            state.wire_position,
            int(state.spark_status[0]),
            int(state.spark_status[2]),
            0.0 if state.spark_status[1] is None else float(state.spark_status[1]),
            float(state.last_crater_volume),
            self.debris_volume,
            self._last_gap_um,
            self._last_debris_density,
            self._last_flow_condition,
            ionized_channel_location_mm,
            ionized_channel_duration,
            self.cavity_volume_coeff,
            self.params.reference_gap,
            self.params.debris_obstruction_coeff,
            self.debris_removal_per_us,
            self.params.ion_channel_duration,
        )

        if ionized_channel_duration > 0:
            self.ion_channel = (ionized_channel_location_mm, ionized_channel_duration)
        else:
            self.ion_channel = None

        state.debris_volume = self.debris_volume
        state.debris_density = self.debris_density
        state.cavity_volume = self.cavity_volume
        state.flow_rate = self.flow_condition

        state.debris_concentration = self.debris_density
        state.dielectric_flow_rate = (
            self.flow_condition * self.params.base_flow_rate
        ) / 1e9
        state.ionized_channel = self.ion_channel

    def reset_debris(self) -> None:
        """Reset debris tracking."""
        self.debris_volume = 0.0
        self.debris_density = 0.0
        self.cavity_volume = 0.0
        self.flow_condition = 0.0
        self.ion_channel = None
        self._last_gap_um = -1.0
        self._last_debris_density = -1.0
        self._last_flow_condition = 0.0

    def get_debris_statistics(self) -> dict:
        """Get current debris tracking statistics."""
        return {
            "debris_volume_mm3": self.debris_volume,
            "debris_density": self.debris_density,
            "cavity_volume_mm3": self.cavity_volume,
            "flow_condition": self.flow_condition,
            "debris_fill_percentage": self.debris_density * 100.0,
        }
