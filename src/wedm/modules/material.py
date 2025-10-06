# src/edm_env/modules/material.py
from __future__ import annotations

import json
import os
import numpy as np
from pathlib import Path
from dataclasses import dataclass

from ..core.module import EDMModule
from ..core.state import EDMState


# ──────────────────────────────────────────────────────────────────────────────
# Material Module Parameters - Defined within module
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class MaterialModuleParameters:
    """Material removal module specific parameters."""

    # ── Material Removal Model Parameters ──
    base_overcut: float = 0.026  # [mm] Base overcut (0.06mm per side)


class MaterialRemovalModule(EDMModule):
    """Material removal module using empirical crater volume distributions."""

    def __init__(
        self,
        env,
        parameters: MaterialModuleParameters = None,
    ):
        super().__init__(env)

        # ── Module Parameters ──
        self.params = parameters or MaterialModuleParameters()

        # ── Load Empirical Data ──
        # Load crater volume data from JSON file
        self.crater_data = self._load_crater_data()
        # Load machine current modes data
        self.currents_data = self._load_currents_data()

        # ── Caching for Performance ──
        # Cache for efficiency - avoid repeated current mode lookups
        self._cached_current_mode: str | None = None
        self._cached_crater_info: dict = self.crater_data["I1"]  # Default crater data

        # ── Analysis Tracking ──
        # Track crater volumes for analysis
        self.crater_volumes_um3 = []  # Store all crater volumes in μm³

    def _load_crater_data(self) -> dict:
        """Load crater volume distributions from area_corrected.json."""
        # Get the path relative to this module
        current_dir = Path(__file__).parent
        json_path = current_dir / "area_corrected.json"

        try:
            with open(json_path, "r") as f:
                data = json.load(f)
            return data
        except FileNotFoundError:
            raise FileNotFoundError(f"Could not find crater data file at {json_path}")

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

    def update(self, state: EDMState) -> None:
        """Update material removal based on spark events and crater volumes."""
        # Only remove material during fresh REAL sparks (state 1), not short circuits (state -1)
        # Skip material removal during short circuits (state -1)
        if state.spark_status[0] == 1 and state.spark_status[2] == 0:
            # Fresh real spark just ignited, calculate material removal
            crater_volume = self._sample_crater_volume(state)

            # Make crater volume available to dielectric module for debris tracking
            state.last_crater_volume = crater_volume

            if crater_volume > 0:
                # Calculate workpiece position increment
                delta_x = self._calculate_position_increment(crater_volume, state)
                state.workpiece_position += delta_x
        else:
            # No fresh real spark, reset crater volume
            state.last_crater_volume = 0.0

    def _sample_crater_volume(self, state: EDMState) -> float:
        """Sample crater volume from empirical distribution based on current mode."""
        current_mode = state.current_mode

        # Only recalculate if current_mode has changed
        if current_mode != self._cached_current_mode:
            if current_mode is None:
                current_mode = "I1"  # Default to I1 if not specified

            # Check if current mode has crater data available
            if current_mode not in self.crater_data:
                available_modes = list(self.crater_data.keys())
                raise ValueError(
                    f"Current mode {current_mode} is not available in crater data. "
                    f"Available modes: {available_modes}"
                )

            # Get distribution parameters directly from current mode
            self._cached_crater_info = self.crater_data[current_mode]
            self._cached_current_mode = current_mode

        # Use cached crater info
        mean_volume = self._cached_crater_info[
            "ellipsoid_volume_half"
        ]  # Using half volume as it's more realistic
        std_volume = self._cached_crater_info["ellipsoid_volume_std"]

        # Sample from Gaussian distribution
        # Convert from micrometers³ to mm³ (divide by 1e9)
        sampled_volume_um3 = self.env.np_random.normal(mean_volume, std_volume)

        # Ensure non-negative volume
        sampled_volume_um3 = max(0, sampled_volume_um3)

        # Store the crater volume for analysis
        self.crater_volumes_um3.append(sampled_volume_um3)

        # Convert to mm³
        sampled_volume_mm3 = sampled_volume_um3 / 1e9

        return sampled_volume_mm3

    def _calculate_position_increment(
        self, crater_volume: float, state: EDMState
    ) -> float:
        """Calculate workpiece position increment from crater volume.

        Args:
            crater_volume: Crater volume in mm³
            state: Current EDM state

        Returns:
            Position increment in μm (same units as state positions)
        """
        # Calculate kerf width: k = base_overcut + wire_diameter + crater_depth
        wire_diameter_mm = self.env.config.wire_diameter  # mm

        # Get crater depth from cached crater info (convert from μm to mm)
        crater_depth_um = self._cached_crater_info["depth"]  # μm
        crater_depth_mm = crater_depth_um / 1000.0  # Convert μm to mm

        kerf_width_mm = (
            self.params.base_overcut + wire_diameter_mm + crater_depth_mm
        )  # mm

        # Workpiece height
        workpiece_height_mm = self.env.config.workpiece_height  # mm

        # Calculate position increment: ΔXw = Vc / (k * hw)
        # Result will be in mm, then convert to μm
        if kerf_width_mm > 0 and workpiece_height_mm > 0:
            delta_x_mm = crater_volume / (kerf_width_mm * workpiece_height_mm)  # mm
            delta_x_um = delta_x_mm * 1000.0  # Convert mm to μm to match state units
        else:
            delta_x_um = 0.0

        return delta_x_um

    def get_crater_data_for_current_mode(self, current_mode: str) -> dict:
        """Get crater data for a specific current mode (for debugging/analysis)."""
        current_mode_key = current_mode
        if current_mode_key not in self.currents_data:
            current_mode_key = "I1"

        machine_current = self.currents_data[current_mode_key]["Current"]

        # Check if crater data is available for this current mode
        if current_mode_key not in self.crater_data:
            available_modes = list(self.crater_data.keys())
            return {
                "current_mode": current_mode_key,
                "machine_current": machine_current,
                "crater_data": None,
                "error": f"No crater data available for {current_mode_key}. Available: {available_modes}",
            }

        return {
            "current_mode": current_mode_key,
            "machine_current": machine_current,
            "crater_data": self.crater_data[current_mode_key],
        }

    def get_current_mapping_table(self) -> dict:
        """Get complete mapping table from current modes to crater data (for debugging)."""
        mapping = {}
        for i in range(19):  # I1 to I19 (0-18)
            mapping[f"I{i+1}"] = self.get_crater_data_for_current_mode(f"I{i+1}")
        return mapping

    def get_crater_statistics(self) -> dict:
        """Get statistics about generated craters."""
        if not self.crater_volumes_um3:
            return {
                "total_craters": 0,
                "mean_volume_um3": 0,
                "std_volume_um3": 0,
                "min_volume_um3": 0,
                "max_volume_um3": 0,
                "volumes_um3": [],
            }

        volumes = np.array(self.crater_volumes_um3)
        return {
            "total_craters": len(volumes),
            "mean_volume_um3": np.mean(volumes),
            "std_volume_um3": np.std(volumes),
            "min_volume_um3": np.min(volumes),
            "max_volume_um3": np.max(volumes),
            "volumes_um3": volumes,
        }

    def reset_crater_tracking(self):
        """Reset crater volume tracking (useful for new simulations)."""
        self.crater_volumes_um3 = []
