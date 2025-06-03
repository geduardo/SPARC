# src/wedm/core/env_config.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any
import json
from pathlib import Path


@dataclass
class EnvironmentConfig:
    """
    Fixed environment configuration parameters that don't change during simulation.
    These define the physical setup and constraints of the EDM environment.
    """

    # ── Workpiece Properties ──
    workpiece_height: float = 20.0  # [mm] Height/thickness of workpiece to cut

    # ── Wire Properties ──
    wire_diameter: float = 0.2  # [mm] Diameter of the wire electrode
    wire_material: str = "brass"  # Wire material for automatic parameter loading

    # ── Simulation Parameters ──
    dt: int = 1  # [µs] Base simulation timestep
    servo_interval: int = 1000  # [µs] Control timestep interval

    # ── Cutting Parameters ──
    initial_gap: float = 50.0  # [µm] Initial gap between wire and workpiece
    target_cutting_distance: float = 500.0  # [µm] Target distance to cut

    # ── Physical Constraints ──
    max_wire_temperature: float = 1500.0  # [K] Temperature at which wire breaks
    min_gap_for_operation: float = 2.0  # [µm] Minimum gap before collision
    max_cutting_force: float = 100.0  # [N] Maximum allowable cutting force

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "EnvironmentConfig":
        """Create EnvironmentConfig from dictionary."""
        return cls(
            **{k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__}
        )

    @classmethod
    def from_json(cls, json_path: str | Path) -> "EnvironmentConfig":
        """Load EnvironmentConfig from JSON file."""
        json_path = Path(json_path)
        with open(json_path, "r") as f:
            config_dict = json.load(f)
        return cls.from_dict(config_dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert EnvironmentConfig to dictionary."""
        return {
            "workpiece_height": self.workpiece_height,
            "wire_diameter": self.wire_diameter,
            "wire_material": self.wire_material,
            "dt": self.dt,
            "servo_interval": self.servo_interval,
            "initial_gap": self.initial_gap,
            "target_cutting_distance": self.target_cutting_distance,
            "max_wire_temperature": self.max_wire_temperature,
            "min_gap_for_operation": self.min_gap_for_operation,
            "max_cutting_force": self.max_cutting_force,
        }

    def to_json(self, json_path: str | Path) -> None:
        """Save EnvironmentConfig to JSON file."""
        json_path = Path(json_path)
        with open(json_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def validate(self) -> None:
        """Validate configuration parameters."""
        if self.workpiece_height <= 0:
            raise ValueError("workpiece_height must be positive")
        if self.wire_diameter <= 0:
            raise ValueError("wire_diameter must be positive")
        if self.initial_gap <= 0:
            raise ValueError("initial_gap must be positive")
        if self.target_cutting_distance <= 0:
            raise ValueError("target_cutting_distance must be positive")
        if self.dt <= 0:
            raise ValueError("dt must be positive")
        if self.servo_interval <= 0:
            raise ValueError("servo_interval must be positive")
        if self.max_wire_temperature <= 293.15:
            raise ValueError(
                "max_wire_temperature must be greater than room temperature"
            )
