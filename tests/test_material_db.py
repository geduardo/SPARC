from __future__ import annotations

import json

import pytest

from wedm import EnvironmentConfig, WireEDMEnv
from wedm.core.material_db import MaterialDatabase, WireMaterial


def test_material_db_backfills_legacy_brass_damage_model(tmp_path) -> None:
    legacy_payload = {
        "brass": {
            "density": 8400,
            "specific_heat": 377,
            "thermal_conductivity": 120,
            "electrical_resistivity": 6.4e-8,
            "temperature_coefficient": 0.0039,
            "melting_point": 1173,
            "breaking_temperature": 1500,
        }
    }
    (tmp_path / "wire_materials.json").write_text(
        json.dumps(legacy_payload), encoding="utf-8"
    )

    db = MaterialDatabase(data_dir=tmp_path)
    brass = db.get_wire_material("brass")

    assert brass.damage_temperature_threshold == pytest.approx(423.0)
    assert brass.damage_rate_constant == pytest.approx(7.168e-5)
    assert brass.damage_stress_exponent == pytest.approx(6.734)
    assert brass.damage_activation_energy == pytest.approx(143.1e3)


def test_wire_module_uses_wire_material_damage_model(monkeypatch) -> None:
    custom_material = WireMaterial(
        name="brass",
        density=8400,
        specific_heat=377,
        thermal_conductivity=120,
        electrical_resistivity=6.4e-8,
        temperature_coefficient=0.0039,
        melting_point=1173,
        breaking_temperature=1500,
        damage_temperature_threshold=460.0,
        damage_rate_constant=9.5e-5,
        damage_stress_exponent=4.25,
        damage_activation_energy=120.0e3,
    )

    class _StubMaterialDb:
        def get_wire_material(self, name: str) -> WireMaterial:
            assert name == "brass"
            return custom_material

    import wedm.modules.wire as wire_module

    monkeypatch.setattr(wire_module, "get_material_db", lambda: _StubMaterialDb())

    env = WireEDMEnv(config=EnvironmentConfig(wire_material="brass"))

    expected_stress_mpa = (env.wire.params.wire_tension_force / env.wire.S) / 1e6
    expected_rate = (
        custom_material.damage_rate_constant
        * (expected_stress_mpa ** custom_material.damage_stress_exponent)
        * env.wire.dt_sim
    )
    expected_activation_scale = -custom_material.damage_activation_energy / 8.314

    assert env.wire.wire_material is custom_material
    assert env.wire.damage_temperature_threshold_k == pytest.approx(
        custom_material.damage_temperature_threshold
    )
    assert env.wire.damage_stress_term_dt == pytest.approx(expected_rate)
    assert env.wire.damage_activation_scale == pytest.approx(
        expected_activation_scale
    )
