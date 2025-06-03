# src/wedm/core/material_db.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional


@dataclass
class WireMaterial:
    """Wire material properties for automatic parameter loading."""

    name: str
    density: float  # [kg/m³]
    specific_heat: float  # [J/kg·K]
    thermal_conductivity: float  # [W/m·K]
    electrical_resistivity: float  # [Ω·m]
    temperature_coefficient: float  # [1/K]
    melting_point: float  # [K]
    breaking_temperature: float  # [K] Temperature at which wire breaks


class MaterialDatabase:
    """Central database for material properties with automatic loading."""

    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize material database."""
        if data_dir is None:
            # Default to data directory relative to this module
            data_dir = Path(__file__).parent.parent / "data"

        self.data_dir = Path(data_dir)
        self._wire_materials: Dict[str, WireMaterial] = {}

        # Load wire material data
        self._load_wire_materials()

    def _load_wire_materials(self) -> None:
        """Load wire material properties."""
        wire_file = self.data_dir / "wire_materials.json"
        if wire_file.exists():
            with open(wire_file, "r") as f:
                data = json.load(f)

            for name, props in data.items():
                self._wire_materials[name] = WireMaterial(name=name, **props)
        else:
            # Create default wire materials if file doesn't exist
            self._create_default_wire_materials()

    def _create_default_wire_materials(self) -> None:
        """Create default wire material database."""
        self._wire_materials = {
            "brass": WireMaterial(
                name="brass",
                density=8400,  # kg/m³
                specific_heat=377,  # J/kg·K
                thermal_conductivity=120,  # W/m·K
                electrical_resistivity=6.4e-8,  # Ω·m
                temperature_coefficient=0.0039,  # 1/K
                melting_point=1173,  # K
                breaking_temperature=1500,  # K
            ),
        }

    def get_wire_material(self, name: str) -> WireMaterial:
        """Get wire material properties by name."""
        if name not in self._wire_materials:
            raise ValueError(
                f"Unknown wire material: {name}. Available: {list(self._wire_materials.keys())}"
            )
        return self._wire_materials[name]

    def save_materials(self) -> None:
        """Save wire material data to JSON file."""
        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Save wire materials
        wire_data = {
            name: {
                "density": mat.density,
                "specific_heat": mat.specific_heat,
                "thermal_conductivity": mat.thermal_conductivity,
                "electrical_resistivity": mat.electrical_resistivity,
                "temperature_coefficient": mat.temperature_coefficient,
                "melting_point": mat.melting_point,
                "breaking_temperature": mat.breaking_temperature,
            }
            for name, mat in self._wire_materials.items()
        }

        with open(self.data_dir / "wire_materials.json", "w") as f:
            json.dump(wire_data, f, indent=2)


# Global material database instance
_material_db: Optional[MaterialDatabase] = None


def get_material_db() -> MaterialDatabase:
    """Get global material database instance."""
    global _material_db
    if _material_db is None:
        _material_db = MaterialDatabase()
    return _material_db
