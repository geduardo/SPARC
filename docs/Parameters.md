# WEDM Simulation Parameters and Variables - Technical Annex

## Table of Contents

1. [Overview](#1-overview)
2. [EDM State Variables](#2-edm-state-variables)
3. [Environment Configuration](#3-environment-configuration)
4. [Module Parameters](#4-module-parameters)
   - 4.1 [Wire Module Parameters](#41-wire-module-parameters)
   - 4.2 [Ignition Module Parameters](#42-ignition-module-parameters)
   - 4.3 [Material Module Parameters](#43-material-module-parameters)
   - 4.4 [Dielectric Module Parameters](#44-dielectric-module-parameters)
   - 4.5 [Mechanics Module Parameters](#45-mechanics-module-parameters)
5. [Material Database](#5-material-database)

---

## 1. Overview

The Wire EDM (WEDM) simulation environment parameters are organized into three distinct categories:

1. **EDM State Variables**: Dynamic process state that changes during simulation
2. **Environment Configuration**: Fixed parameters defining the physical setup
3. **Module Parameters**: Module-specific empirical values and computational settings

This annex provides a comprehensive reference of all parameters used in the WEDM simulation system.

---

## 2. EDM State Variables

State variables represent the current process state and are accessible globally by all modules. These variables change during simulation execution.

### 2.1 Time Tracking Variables

| # | Variable Name | Type | Units | Description |
|---|--------------|------|-------|-------------|
| 2.1.1 | `time` | float | μs | Total simulation time elapsed |
| 2.1.2 | `time_since_servo` | float | μs | Time since last servo control update |
| 2.1.3 | `time_since_spark_ignition` | float | μs | Time since spark ignition event |
| 2.1.4 | `time_since_spark_end` | float | μs | Time since last spark extinction |
| 2.1.5 | `time_since_open_voltage` | float | μs | Time since open circuit voltage detection |
| 2.1.6 | `time_in_critical_temp` | int | steps | Number of steps wire temperature exceeded critical threshold |

### 2.2 Electrical State Variables

| # | Variable Name | Type | Units | Description |
|---|--------------|------|-------|-------------|
| 2.2.1 | `voltage` | float | V | Current gap voltage |
| 2.2.2 | `current` | float | A | Current discharge current |

### 2.3 Generator Settings

| # | Variable Name | Type | Units | Description |
|---|--------------|------|-------|-------------|
| 2.3.1 | `target_voltage` | float | V | Target generator voltage |
| 2.3.2 | `current_mode` | str | - | Current mode setting (I1-I19) |
| 2.3.3 | `ON_time` | float | μs | Pulse ON time duration |
| 2.3.4 | `OFF_time` | float | μs | Pulse OFF time duration |

### 2.4 Position and Motion Variables

| # | Variable Name | Type | Units | Description |
|---|--------------|------|-------|-------------|
| 2.4.1 | `workpiece_position` | float | μm | Current workpiece position |
| 2.4.2 | `wire_position` | float | μm | Current wire position |
| 2.4.3 | `wire_velocity` | float | μm/s | Wire feed velocity |
| 2.4.4 | `wire_unwinding_velocity` | float | mm/s | Wire unwinding velocity |

### 2.5 Wire Thermal State

| # | Variable Name | Type | Units | Description |
|---|--------------|------|-------|-------------|
| 2.5.1 | `wire_temperature` | np.ndarray | K | Temperature distribution along wire |
| 2.5.2 | `wire_average_temperature` | float | K | Average temperature in cutting zone |

### 2.6 Spark/Discharge State

| # | Variable Name | Type | Units | Description |
|---|--------------|------|-------|-------------|
| 2.6.1 | `spark_status` | tuple | - | (state, y_location, is_fresh) |
| 2.6.2 | `last_crater_volume` | float | mm³ | Volume of last crater created |

### 2.7 Dielectric State

| # | Variable Name | Type | Units | Description |
|---|--------------|------|-------|-------------|
| 2.7.1 | `dielectric_conductivity` | float | S/m | Dielectric electrical conductivity |
| 2.7.2 | `dielectric_temperature` | float | K | Dielectric temperature |
| 2.7.3 | `ionized_channel` | tuple/None | - | (y_location, remaining_time) |

### 2.8 Debris Tracking

| # | Variable Name | Type | Units | Description |
|---|--------------|------|-------|-------------|
| 2.8.1 | `debris_volume` | float | mm³ | Total debris volume in gap |
| 2.8.2 | `debris_density` | float | - | Debris density (0-1) |
| 2.8.3 | `cavity_volume` | float | mm³ | Gap cavity volume |
| 2.8.4 | `flow_rate` | float | - | Effective flow condition (0-1) |
| 2.8.5 | `debris_concentration` | float | - | Legacy: same as debris_density |
| 2.8.6 | `dielectric_flow_rate` | float | m³/s | Legacy: volumetric flow rate |

### 2.9 Process Flags

| # | Variable Name | Type | Units | Description |
|---|--------------|------|-------|-------------|
| 2.9.1 | `is_short_circuit` | bool | - | Short circuit detection flag |
| 2.9.2 | `is_wire_broken` | bool | - | Wire breakage flag |
| 2.9.3 | `is_target_distance_reached` | bool | - | Target distance reached flag |

### 2.10 Servo Control

| # | Variable Name | Type | Units | Description |
|---|--------------|------|-------|-------------|
| 2.10.1 | `target_delta` | float | μm or μm/s | Control target (position/velocity) |
| 2.10.2 | `target_position` | float | μm | Target cutting distance |

---

## 3. Environment Configuration

Fixed parameters that define the physical setup and constraints of the EDM process.

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 3.1 | `workpiece_height` | float | mm | 10.0 | Height of the workpiece |
| 3.2 | `wire_diameter` | float | mm | 0.2 | Diameter of the EDM wire |
| 3.3 | `wire_material` | str | - | "brass" | Wire material type |
| 3.4 | `dt` | int | μs | 1 | Simulation time step |
| 3.5 | `servo_interval` | int | μs | 1000 | Servo control update interval |
| 3.6 | `initial_gap` | float | μm | 50.0 | Initial gap between wire and workpiece |
| 3.7 | `target_cutting_distance` | float | μm | 1000.0 | Target distance to cut |
| 3.8 | `max_wire_temperature` | float | K | 1500.0 | Maximum allowable wire temperature |
| 3.9 | `min_gap_for_operation` | float | μm | 5.0 | Minimum gap for stable operation |
| 3.10 | `max_cutting_force` | float | N | 10.0 | Maximum cutting force (reserved) |

---

## 4. Module Parameters

### 4.1 Wire Module Parameters

Parameters for the 1-D transient heat model of the travelling wire.

#### 4.1.1 Thermal Model Parameters

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.1.1.1 | `buffer_len_bottom` | float | mm | 30.0 | Buffer length below workpiece |
| 4.1.1.2 | `buffer_len_top` | float | mm | 30.0 | Buffer length above workpiece |
| 4.1.1.3 | `segment_len` | float | mm | 0.2 | Length of each wire segment |
| 4.1.1.4 | `spool_T` | float | K | 293.15 | Temperature of wire spool |

#### 4.1.2 Heat Transfer Parameters

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.1.2.1 | `base_convection_coefficient` | float | W/m²·K | 14000 | Base convection coefficient |
| 4.1.2.2 | `plasma_efficiency` | float | - | 0.1 | Fraction of electrical power to heat |
| 4.1.2.3 | `convection_velocity_factor` | float | - | 0.5 | Velocity enhancement factor |
| 4.1.2.4 | `convection_flow_enhancement` | float | - | 1.0 | Flow enhancement factor |

#### 4.1.3 Computational Parameters

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.1.3.1 | `compute_zone_mean` | bool | - | False | Enable zone mean computation |
| 4.1.3.2 | `zone_mean_interval` | int | steps | 100 | Zone mean update frequency |

#### 4.1.4 Critical Temperature Parameters

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.1.4.1 | `critical_temp_threshold` | float | - | 0.9 | Fraction of melting point |
| 4.1.4.2 | `wire_breaking_temp_factor` | float | - | 1.1 | Breaking temperature factor |

### 4.2 Ignition Module Parameters

Parameters for spark ignition and short circuit detection.

#### 4.2.1 Critical Debris Model

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.2.1.1 | `base_critical_density` | float | - | 0.3 | Base critical debris density |
| 4.2.1.2 | `gap_coefficient` | float | μm⁻¹ | 0.02 | Gap-dependent coefficient |
| 4.2.1.3 | `max_critical_density` | float | - | 0.9 | Maximum critical density |
| 4.2.1.4 | `hard_short_gap` | float | μm | 2.0 | Gap for guaranteed short |

#### 4.2.2 Random Short Circuit Model

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.2.2.1 | `random_short_duration` | int | μs | 100 | Random short duration |
| 4.2.2.2 | `random_short_min_gap` | float | μm | 5.0 | Minimum gap for random shorts |
| 4.2.2.3 | `random_short_max_gap` | float | μm | 30.0 | Maximum gap for random shorts |
| 4.2.2.4 | `random_short_max_probability` | float | - | 0.001 | Maximum probability |

#### 4.2.3 Ignition Probability Model

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.2.3.1 | `ignition_a_coeff` | float | - | 0.48 | Coefficient a |
| 4.2.3.2 | `ignition_b_coeff` | float | V⁻¹ | -3.69 | Coefficient b |
| 4.2.3.3 | `ignition_c_coeff` | float | μm·V⁻¹ | 14.05 | Coefficient c |

#### 4.2.4 Generator Defaults

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.2.4.1 | `default_target_voltage` | float | V | 80.0 | Default voltage |
| 4.2.4.2 | `default_on_time` | float | μs | 3.0 | Default ON time |
| 4.2.4.3 | `default_off_time` | float | μs | 80.0 | Default OFF time |
| 4.2.4.4 | `default_current_mode` | str | - | "I5" | Default current mode |

#### 4.2.5 Voltage Drop

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.2.5.1 | `spark_voltage_factor` | float | - | 0.3 | Voltage drop factor during spark |

### 4.3 Material Module Parameters

Parameters for material removal using empirical crater volume distributions.

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.3.1 | `base_overcut` | float | mm | 0.12 | Base overcut (0.06mm per side) |

### 4.4 Dielectric Module Parameters

Parameters for debris tracking and flow modeling.

#### 4.4.1 Debris Tracking Parameters

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.4.1.1 | `base_flow_rate` | float | mm³/s | 100.0 | Base pump/nozzle capacity |
| 4.4.1.2 | `debris_removal_efficiency` | float | - | 0.01 | Debris removal efficiency (β) |
| 4.4.1.3 | `debris_obstruction_coeff` | float | - | 1.0 | Debris obstruction coefficient |
| 4.4.1.4 | `reference_gap` | float | μm | 25.0 | Reference gap for flow |

#### 4.4.2 Physical Parameters

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.4.2.1 | `dielectric_temperature` | float | K | 293.15 | Dielectric temperature |
| 4.4.2.2 | `ion_channel_duration` | int | μs | 6 | Ionized channel deionization time |

### 4.5 Mechanics Module Parameters

Parameters for servo axis control system.

#### 4.5.1 Control System Parameters

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.5.1.1 | `omega_n` | float | rad/s | 200.0 | Natural frequency |
| 4.5.1.2 | `zeta` | float | - | 0.55 | Damping ratio |

#### 4.5.2 Physical Limits

| # | Parameter Name | Type | Units | Default | Description |
|---|---------------|------|-------|---------|-------------|
| 4.5.2.1 | `max_acceleration` | float | μm/s² | 3.0e5 | Maximum acceleration |
| 4.5.2.2 | `max_jerk` | float | μm/s³ | 1.0e8 | Maximum jerk |
| 4.5.2.3 | `max_speed` | float | μm/s | 3.0e4 | Maximum speed |

---

## 5. Material Database

### 5.1 Wire Materials

Currently, only brass wire material is supported in the material database.

#### 5.1.1 Brass Wire Properties

| # | Property Name | Type | Units | Value | Description |
|---|--------------|------|-------|-------|-------------|
| 5.1.1.1 | `name` | str | - | "brass" | Material identifier |
| 5.1.1.2 | `density` | float | kg/m³ | 8400 | Material density |
| 5.1.1.3 | `specific_heat` | float | J/kg·K | 377 | Specific heat capacity |
| 5.1.1.4 | `thermal_conductivity` | float | W/m·K | 120 | Thermal conductivity |
| 5.1.1.5 | `electrical_resistivity` | float | Ω·m | 6.4e-8 | Electrical resistivity |
| 5.1.1.6 | `temperature_coefficient` | float | 1/K | 0.0039 | Temperature coefficient |
| 5.1.1.7 | `melting_point` | float | K | 1173 | Melting temperature |
| 5.1.1.8 | `breaking_temperature` | float | K | 1500 | Wire breaking temperature |

---

## Notes

1. **Units Convention**: All position-related parameters use micrometers (μm) except wire diameter and workpiece height which use millimeters (mm).

2. **Time Units**: All time-related parameters use microseconds (μs) for consistency with the simulation time step.

3. **Temperature Units**: All temperatures are in Kelvin (K).

4. **Material Properties**: Only brass wire is currently supported. The system is designed to allow future expansion with additional wire materials.

5. **Legacy Compatibility**: Some state variables (marked as "Legacy") are maintained for backward compatibility but may be deprecated in future versions.

6. **Module Independence**: Each module's parameters are self-contained and can be configured independently, promoting modularity and maintainability.

---

*Document Version: 1.0*  
*Last Updated: 2025* 