#!/usr/bin/env python3
"""
Example demonstrating the new organized parameter structure for WEDM simulation.

This example shows how to:
1. Configure the environment with EnvironmentConfig
2. Set module-specific parameters
3. Use automatic material loading from the database
4. Run a simulation with the organized structure
"""

import numpy as np
from wedm import (
    WireEDMEnv,
    EnvironmentConfig,
    IgnitionModuleParameters,
    WireModuleParameters,
    MaterialModuleParameters,
    DielectricModuleParameters,
    MechanicsModuleParameters,
    get_material_db,
)


def main():
    print("=== WEDM Organized Parameter Example ===\n")

    # ──────────────────────────────────────────────────────────────────
    # 1. Environment Configuration (Fixed parameters)
    # ──────────────────────────────────────────────────────────────────
    print("1. Setting up Environment Configuration...")

    env_config = EnvironmentConfig(
        # Workpiece properties
        workpiece_height=15.0,  # [mm]
        # Wire properties
        wire_diameter=0.25,  # [mm]
        wire_material="brass",  # Will auto-load material properties
        # Simulation parameters
        dt=1,  # [µs]
        servo_interval=1000,  # [µs]
        # Cutting parameters
        initial_gap=75.0,  # [µm]
        target_cutting_distance=800.0,  # [µm]
        # Physical constraints
        max_wire_temperature=1400.0,  # [K] - below brass melting point
        min_gap_for_operation=3.0,  # [µm]
    )

    print(f"  - Workpiece: {env_config.workpiece_height} mm height")
    print(f"  - Wire: {env_config.wire_material} ({env_config.wire_diameter} mm)")
    print(f"  - Target distance: {env_config.target_cutting_distance} µm\n")

    # ──────────────────────────────────────────────────────────────────
    # 2. Module Parameters (Module-specific empirical values)
    # ──────────────────────────────────────────────────────────────────
    print("2. Setting up Module Parameters...")

    # Ignition module parameters
    ignition_params = IgnitionModuleParameters(
        # Critical debris model
        base_critical_density=0.3,  # Standard debris threshold
        gap_coefficient=0.02,  # Standard gap behavior
        hard_short_gap=2.0,  # Standard tolerance
        # Random short circuit model
        random_short_max_probability=0.001,  # Standard probability
        random_short_duration=100,  # Standard duration
        # Ignition probability coefficients (default values)
        ignition_a_coeff=0.48,
        ignition_b_coeff=-3.69,
        ignition_c_coeff=14.05,
        # Default generator settings
        default_target_voltage=80.0,  # Standard voltage for brass
        default_on_time=3.0,  # Standard pulses
        default_off_time=80.0,  # Standard rest
    )

    # Wire module parameters
    wire_params = WireModuleParameters(
        # Thermal model
        buffer_len_bottom=30.0,  # [mm] Standard buffer for brass
        buffer_len_top=30.0,  # [mm]
        segment_len=0.2,  # [mm] Standard discretization
        spool_T=293.15,  # [K] Room temperature spool
        # Heat transfer
        base_convection_coefficient=14000,  # Standard for water dielectric
        plasma_efficiency=0.1,  # Standard for brass
        convection_velocity_factor=0.5,
        convection_flow_enhancement=1.0,
        # Computational
        compute_zone_mean=True,  # Enable zone mean computation
        zone_mean_interval=100,  # Standard update frequency
        # Critical temperature
        critical_temp_threshold=0.9,  # Conservative for brass
    )

    # Material removal module parameters
    material_params = MaterialModuleParameters(
        base_overcut=0.12,  # [mm] Standard overcut
    )

    # Dielectric module parameters
    dielectric_params = DielectricModuleParameters(
        base_flow_rate=100.0,  # [mm³/s] Standard flow rate
        debris_removal_efficiency=0.01,  # Standard removal efficiency
        debris_obstruction_coeff=1.0,  # Standard obstruction coefficient
        reference_gap=25.0,  # [μm] Standard reference gap
        dielectric_temperature=293.15,  # [K] Room temperature
        ion_channel_duration=6,  # [μs] Standard deionization time
    )

    # Mechanics module parameters
    mechanics_params = MechanicsModuleParameters(
        omega_n=200.0,  # [rad/s] Standard natural frequency
        zeta=0.55,  # Standard damping ratio
        max_acceleration=3.0e5,  # [µm/s²] Standard max acceleration
        max_jerk=1.0e8,  # [µm/s³] Standard max jerk
        max_speed=3.0e4,  # [µm/s] Standard max speed
    )

    print(
        f"  - Ignition: Critical density {ignition_params.base_critical_density}, voltage {ignition_params.default_target_voltage}V"
    )
    print(
        f"  - Wire: Buffer {wire_params.buffer_len_bottom}mm, segments {wire_params.segment_len}mm"
    )
    print(f"  - Material: Base overcut {material_params.base_overcut}mm")
    print(f"  - Dielectric: Flow rate {dielectric_params.base_flow_rate} mm³/s")
    print(
        f"  - Mechanics: ωn={mechanics_params.omega_n} rad/s, ζ={mechanics_params.zeta}\n"
    )

    # ──────────────────────────────────────────────────────────────────
    # 3. Material Database Inspection
    # ──────────────────────────────────────────────────────────────────
    print("3. Inspecting Material Database...")

    material_db = get_material_db()

    # Get wire material properties
    wire_material = material_db.get_wire_material(env_config.wire_material)
    print(f"  - Wire ({wire_material.name}):")
    print(f"    * Density: {wire_material.density} kg/m³")
    print(f"    * Thermal conductivity: {wire_material.thermal_conductivity} W/m·K")
    print(f"    * Melting point: {wire_material.melting_point} K")
    print(f"    * Breaking temperature: {wire_material.breaking_temperature} K\n")

    # ──────────────────────────────────────────────────────────────────
    # 4. Create Environment with Organized Parameters
    # ──────────────────────────────────────────────────────────────────
    print("4. Creating Environment...")

    env = WireEDMEnv(
        config=env_config,
        ignition_params=ignition_params,
        wire_params=wire_params,
        material_params=material_params,
        dielectric_params=dielectric_params,
        mechanics_params=mechanics_params,
        mechanics_control_mode="position",
    )

    print(f"  - Environment created successfully")
    print(f"  - Wire segments: {env.wire.n_segments}")
    print(f"  - Zone boundaries: {env.wire.zone_start} to {env.wire.zone_end}")
    print(f"  - Critical temperature: {env.wire.critical_temperature:.1f} K")
    print(f"  - Dielectric temp: {env.dielectric.params.dielectric_temperature:.1f} K")
    print(f"  - Material overcut: {env.material.params.base_overcut} mm")
    print(f"  - Mechanics ωn: {env.mechanics.params.omega_n} rad/s\n")

    # ──────────────────────────────────────────────────────────────────
    # 5. Run Short Simulation
    # ──────────────────────────────────────────────────────────────────
    print("5. Running Short Simulation...")

    obs, info = env.reset()

    # Simple control strategy: maintain small positive feed
    action = {
        "servo": np.array([0.1]),  # Small positive feed
        "generator_control": {
            "target_voltage": np.array([80.0]),
            "current_mode": np.array([5]),  # I5
            "ON_time": np.array([3.0]),
            "OFF_time": np.array([80.0]),
        },
    }

    print(f"  - Initial gap: {env.state.workpiece_position:.1f} µm")
    print(f"  - Target position: {env.state.target_position:.1f} µm")

    # Run for 10 control steps
    for step in range(10):
        obs, reward, terminated, truncated, info = env.step(action)

        if info.get("control_step", False):
            gap = env.state.workpiece_position - env.state.wire_position
            print(
                f"    Step {step+1}: Gap={gap:.1f}µm, Spark={info['spark_state']}, "
                f"Wire temp={env.state.wire_average_temperature:.1f}K"
            )

        if terminated:
            print(f"    Simulation terminated: {info}")
            break

    print(
        f"\n  - Final gap: {env.state.workpiece_position - env.state.wire_position:.1f} µm"
    )
    print(f"  - Wire broken: {env.state.is_wire_broken}")
    print(f"  - Target reached: {env.state.is_target_distance_reached}")

    # ──────────────────────────────────────────────────────────────────
    # 6. Configuration Export/Import Example
    # ──────────────────────────────────────────────────────────────────
    print("\n6. Configuration Export/Import Example...")

    # Export configuration to dictionary
    config_dict = env_config.to_dict()
    print(f"  - Exported config keys: {list(config_dict.keys())}")

    # Create new config from dictionary
    new_config = EnvironmentConfig.from_dict(config_dict)
    print(f"  - Imported config wire material: {new_config.wire_material}")

    print("\n=== Example Complete ===")


if __name__ == "__main__":
    main()
