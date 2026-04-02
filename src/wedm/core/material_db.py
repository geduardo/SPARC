from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


_BRASS_WIRE_MATERIAL_DEFAULTS: dict[str, float] = {
    "density": 8400,
    "specific_heat": 377,
    "thermal_conductivity": 120,
    "electrical_resistivity": 6.4e-8,
    "temperature_coefficient": 0.0039,
    "melting_point": 1173,
    "breaking_temperature": 1500,
    "damage_temperature_threshold": 423.0,
    "damage_rate_constant": 7.168e-5,
    "damage_stress_exponent": 6.734,
    "damage_activation_energy": 143.1e3,
}

_WIRE_MATERIAL_FIELDS = (
    "density",
    "specific_heat",
    "thermal_conductivity",
    "electrical_resistivity",
    "temperature_coefficient",
    "melting_point",
    "breaking_temperature",
    "damage_temperature_threshold",
    "damage_rate_constant",
    "damage_stress_exponent",
    "damage_activation_energy",
)


@dataclass
class WireMaterial:
    """Wire material properties for automatic parameter loading."""

    name: str
    density: float  # [kg/m^3]
    specific_heat: float  # [J/kg*K]
    thermal_conductivity: float  # [W/m*K]
    electrical_resistivity: float  # [Ohm*m]
    temperature_coefficient: float  # [1/K]
    melting_point: float  # [K]
    breaking_temperature: float  # [K]
    damage_temperature_threshold: float  # [K]
    damage_rate_constant: float  # [s^-1 * MPa^-n]
    damage_stress_exponent: float  # [-]
    damage_activation_energy: float  # [J/mol]


class MaterialDatabase:
    """Central database for material properties with automatic loading."""

    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize material database."""
        if data_dir is None:
            data_dir = Path(__file__).parent.parent / "data"

        self.data_dir = Path(data_dir)
        self._wire_materials: Dict[str, WireMaterial] = {}
        self._load_wire_materials()

    def _normalize_wire_material_props(
        self, name: str, props: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Backfill legacy brass data and validate the current schema."""
        normalized = dict(props)
        if name == "brass":
            for key, value in _BRASS_WIRE_MATERIAL_DEFAULTS.items():
                normalized.setdefault(key, value)

        missing = [field for field in _WIRE_MATERIAL_FIELDS if field not in normalized]
        if missing:
            missing_csv = ", ".join(missing)
            raise ValueError(
                f"Wire material '{name}' is missing required properties: {missing_csv}"
            )
        return normalized

    def _load_wire_materials(self) -> None:
        """Load wire material properties."""
        wire_file = self.data_dir / "wire_materials.json"
        if wire_file.exists():
            with open(wire_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for name, props in data.items():
                normalized_props = self._normalize_wire_material_props(name, props)
                self._wire_materials[name] = WireMaterial(
                    name=name, **normalized_props
                )
            return

        self._create_default_wire_materials()

    def _create_default_wire_materials(self) -> None:
        """Create the default wire material database."""
        self._wire_materials = {
            "brass": WireMaterial(
                name="brass",
                **_BRASS_WIRE_MATERIAL_DEFAULTS,
            )
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
        self.data_dir.mkdir(parents=True, exist_ok=True)

        wire_data = {
            name: {
                "density": mat.density,
                "specific_heat": mat.specific_heat,
                "thermal_conductivity": mat.thermal_conductivity,
                "electrical_resistivity": mat.electrical_resistivity,
                "temperature_coefficient": mat.temperature_coefficient,
                "melting_point": mat.melting_point,
                "breaking_temperature": mat.breaking_temperature,
                "damage_temperature_threshold": mat.damage_temperature_threshold,
                "damage_rate_constant": mat.damage_rate_constant,
                "damage_stress_exponent": mat.damage_stress_exponent,
                "damage_activation_energy": mat.damage_activation_energy,
            }
            for name, mat in self._wire_materials.items()
        }

        with open(self.data_dir / "wire_materials.json", "w", encoding="utf-8") as f:
            json.dump(wire_data, f, indent=2)


_material_db: Optional[MaterialDatabase] = None


def get_material_db() -> MaterialDatabase:
    """Get global material database instance."""
    global _material_db
    if _material_db is None:
        _material_db = MaterialDatabase()
    return _material_db
