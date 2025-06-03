# WEDM Parameter Organization

This document describes the reorganized parameter structure for the WEDM simulation environment.

## Overview

The simulation parameters have been reorganized into three distinct categories:

1. **EDM State Variables** - Process state that changes during simulation
2. **Environment Configuration** - Fixed environment parameters 
3. **Module Parameters** - Module-specific empirical values and settings

## 1. EDM State Variables (`EDMState`)

**Location**: `src/wedm/core/state.py`

Contains only variables that represent the current state of the EDM process and can change during simulation. These are accessed globally by all modules.

### Categories:
- **Time Tracking**: `time`, `time_since_servo`, `time_since_spark_ignition`, etc.
- **Electrical State**: `voltage`, `current`
- **Generator Settings**: `target_voltage`, `current_mode`, `ON_time`, `OFF_time`
- **Position and Motion**: `workpiece_position`, `wire_position`, `wire_velocity`
- **Wire Thermal State**: `wire_temperature`, `wire_average_temperature`
- **Spark/Discharge State**: `spark_status`
- **Dielectric State**: `dielectric_conductivity`, `dielectric_temperature`
- **Debris Tracking**: `debris_volume`, `debris_density`, `flow_rate`
- **Process Flags**: `is_short_circuit`, `is_wire_broken`, `is_target_distance_reached`
- **Servo Control**: `target_delta`, `target_position`

## 2. Environment Configuration (`EnvironmentConfig`)

**Location**: `src/wedm/core/env_config.py`

Fixed parameters that define the physical setup and constraints. These cannot change during simulation.

### Categories:
- **Workpiece Properties**: `workpiece_height`
- **Wire Properties**: `wire_diameter`, `wire_material`
- **Simulation Parameters**: `dt`, `servo_interval`
- **Cutting Parameters**: `initial_gap`, `target_cutting_distance`
- **Physical Constraints**: `max_wire_temperature`, `min_gap_for_operation`

### Features:
- JSON import/export: `from_json()`, `to_json()`
- Dictionary conversion: `from_dict()`, `to_dict()`
- Parameter validation: `validate()`

## 3. Module Parameters

**Location**: Within each module file (e.g., `src/wedm/modules/wire.py`)

Module-specific parameters like empirical values, probabilities, and computational settings. These are defined as dataclasses within each module.

### Wire Module (`WireModuleParameters`)
- **Thermal Model**: `buffer_len_bottom`, `buffer_len_top`, `segment_len`, `spool_T`
- **Heat Transfer**: `base_convection_coefficient`, `plasma_efficiency`, `convection_velocity_factor`, `convection_flow_enhancement`
- **Computational**: `compute_zone_mean`, `zone_mean_interval`
- **Critical Temperature**: `critical_temp_threshold`, `wire_breaking_temp_factor`

### Ignition Module (`IgnitionModuleParameters`)
- **Debris Model**: `base_critical_density`, `gap_coefficient`, `max_critical_density`, `hard_short_gap`
- **Random Shorts**: `random_short_duration`, `random_short_min_gap`, `random_short_max_gap`, `random_short_max_probability`
- **Ignition Probability**: `ignition_a_coeff`, `ignition_b_coeff`, `ignition_c_coeff`
- **Generator Defaults**: `default_target_voltage`, `default_on_time`, `default_off_time`, `default_current_mode`
- **Voltage Drop**: `spark_voltage_factor`

### Material Module (`MaterialModuleParameters`)
- **Material Removal Model**: `base_overcut`

### Dielectric Module (`DielectricModuleParameters`)
- **Debris Tracking**: `base_flow_rate`, `debris_removal_efficiency`, `debris_obstruction_coeff`, `reference_gap`
- **Physical Parameters**: `dielectric_temperature`, `ion_channel_duration`

### Mechanics Module (`MechanicsModuleParameters`)
- **Control System**: `omega_n`, `zeta`
- **Physical Limits**: `max_acceleration`, `max_jerk`, `max_speed`

## 4. Material Database

**Location**: `src/wedm/core/material_db.py`, `src/wedm/data/wire_materials.json`

Automatic loading of wire material properties based on material name in environment configuration.

### Wire Materials (`wire_materials.json`)
Currently supports only **brass** wire with the following properties:
- **density**: 8400 kg/m³
- **specific_heat**: 377 J/kg·K
- **thermal_conductivity**: 120 W/m·K
- **electrical_resistivity**: 6.4e-8 Ω·m
- **temperature_coefficient**: 0.0039 1/K
- **melting_point**: 1173 K
- **breaking_temperature**: 1500 K

### Usage:
```python
from wedm import get_material_db

material_db = get_material_db()
wire_material = material_db.get_wire_material("brass")
```

### Notes:
- **Workpiece materials**: Not currently used by material removal module
- **Dielectric properties**: Not currently used by dielectric module
- Only wire material properties are actually used in the simulation

## 5. Usage Example

```python
from wedm import (
    WireEDMEnv,
    EnvironmentConfig,
    IgnitionModuleParameters,
    WireModuleParameters,
    MaterialModuleParameters,
    DielectricModuleParameters,
    MechanicsModuleParameters,
)

# 1. Environment Configuration
config = EnvironmentConfig(
    workpiece_height=15.0,
    wire_diameter=0.25,
    wire_material="brass",  # Only brass currently supported
    target_cutting_distance=800.0,
)

# 2. Module Parameters
ignition_params = IgnitionModuleParameters(
    base_critical_density=0.3,
    default_target_voltage=80.0,
)

wire_params = WireModuleParameters(
    buffer_len_bottom=30.0,
    base_convection_coefficient=14000,
    compute_zone_mean=True,
)

material_params = MaterialModuleParameters(
    base_overcut=0.12,
)

dielectric_params = DielectricModuleParameters(
    base_flow_rate=100.0,
    debris_removal_efficiency=0.01,
)

mechanics_params = MechanicsModuleParameters(
    omega_n=200.0,
    zeta=0.55,
)

# 3. Create Environment
env = WireEDMEnv(
    config=config,
    ignition_params=ignition_params,
    wire_params=wire_params,
    material_params=material_params,
    dielectric_params=dielectric_params,
    mechanics_params=mechanics_params,
)
```

## 6. Benefits

### Clear Separation of Concerns
- **State variables**: What changes during simulation
- **Configuration**: Fixed environment setup
- **Module parameters**: Empirical values and settings

### Automatic Material Loading
- Wire material properties loaded automatically from database
- Consistent material properties across simulations
- Easy to extend with new wire materials when needed

### Type Safety and Validation
- Dataclasses provide type hints and validation
- Environment configuration validation
- Clear parameter documentation

### Maintainability
- Parameters are defined where they're used
- No unused parameter files
- Easy to understand parameter relationships

### Efficiency
- Only loads and stores what's actually used
- No unnecessary material properties or databases
- Smaller memory footprint

### Complete Organization
- All modules now use the same parameter organization pattern
- Consistent interface across the entire simulation
- Easy to extend with new modules

## 7. Migration Guide

### Old Way:
```python
env = WireEDMEnv(
    workpiece_height=10.0,
    wire_diameter=0.2,
    ignition_params={
        "base_critical_density": 0.3,
        "default_target_voltage": 80.0,
    },
    wire_params={
        "buffer_len_bottom": 30.0,
        "base_convection_coefficient": 14000,
    },
    dielectric_params={
        "base_flow_rate": 100.0,
        "debris_removal_efficiency": 0.01,
    },
    mechanics_params={
        "omega_n": 200.0,
        "zeta": 0.55,
    }
)
```

### New Way:
```python
config = EnvironmentConfig(
    workpiece_height=10.0,
    wire_diameter=0.2,
    wire_material="brass",
)

ignition_params = IgnitionModuleParameters(
    base_critical_density=0.3,
    default_target_voltage=80.0,
)

wire_params = WireModuleParameters(
    buffer_len_bottom=30.0,
    base_convection_coefficient=14000,
)

material_params = MaterialModuleParameters(
    base_overcut=0.12,
)

dielectric_params = DielectricModuleParameters(
    base_flow_rate=100.0,
    debris_removal_efficiency=0.01,
)

mechanics_params = MechanicsModuleParameters(
    omega_n=200.0,
    zeta=0.55,
)

env = WireEDMEnv(
    config=config,
    ignition_params=ignition_params,
    wire_params=wire_params,
    material_params=material_params,
    dielectric_params=dielectric_params,
    mechanics_params=mechanics_params,
)
``` 