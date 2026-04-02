# Fast Wrapper Kernel Boundaries

## Purpose

This document defines the shared per-microstep boundaries the modular runner and the future fast wrapper must use.

The goal is:

- one source of physics truth
- no separate fast-only formulas
- thin adapter/scheduler code outside the modules

The wrapper is allowed to batch calls and use compact state buffers. It is not allowed to introduce a second copy of the physics logic.

## Reference Microstep Contract

The current reference microstep order comes from [`WireEDMEnv.step`](../src/wedm/envs/wire_edm.py):

1. control action application when due
2. ignition
3. material
4. dielectric
5. wire
6. early exit on wire break
7. mechanics
8. time bookkeeping
9. termination checks

Shared boundaries must preserve that effective order.

## Design Rules

1. Each module owns its own microstep kernel contract.
2. The modular runner and fast wrapper must call the same module-owned logic.
3. Python objects may be adapted at the boundary, but not reinterpreted differently inside the wrapper.
4. Random draws must be an explicit input to module-owned step kernels when randomness is involved.

## Boundary Inventory

### Ignition

Current owner:
- [`ignition.py`](../src/wedm/modules/ignition.py)

Current module-level hot logic already exists:
- `_roll_new_short_circuit_state(...)`
- `_roll_new_debris_short_state(...)`
- `_advance_short_circuit_state(...)`
- `_get_ignition_probability_scalar(...)`
- `_advance_discharge_state(...)`

Boundary to preserve:

- Inputs:
  - `workpiece_position`
  - `wire_position`
  - `debris_density`
  - current `spark_status`
  - current `voltage`
  - generator settings: `target_voltage`, `current_mode`, `ON_time`, `OFF_time`
  - module-owned short timers
  - random draws for short-circuit and ignition rolls
- Outputs:
  - `is_short_circuit`
  - updated short timers
  - updated `spark_status`
  - updated `voltage`
  - updated `current`

Wrapper implication:
- the fast wrapper should not reimplement discharge-state transitions
- it should call an ignition-owned scalar/kernel boundary with explicit RNG inputs

### Material

Current owner:
- [`material.py`](../src/wedm/modules/material.py)

Current behavior:
- detects fresh discharge from `spark_status`
- samples crater volume from RNG using current mode
- updates `last_crater_volume`
- updates `workpiece_position`
- optionally appends crater history for analysis

Boundary to preserve:

- Inputs:
  - current `spark_status`
  - `current_mode`
  - geometry/config inputs needed by crater-position increment logic
  - random draw(s) for crater sampling
- Outputs:
  - `last_crater_volume`
  - `workpiece_position`
  - optional analysis-tracking side effects

Wrapper implication:
- crater sampling and position increment must still be owned by the material module
- the wrapper should supply RNG draws and compact state, not duplicate crater logic

### Dielectric

Current owner:
- [`dielectric.py`](../src/wedm/modules/dielectric.py)

Current behavior:
- computes gap and cavity volume
- injects debris from fresh discharge using `last_crater_volume`
- updates debris density and flow condition
- removes debris according to flow
- advances `ionized_channel`

Natural boundary:

- Inputs:
  - `workpiece_position`
  - `wire_position`
  - `spark_status`
  - `last_crater_volume`
  - previous dielectric internal state:
    - `debris_volume`
    - `ionized_channel`
    - cached flow-condition inputs if preserved
- Outputs:
  - `dielectric_temperature`
  - `debris_volume`
  - `debris_density`
  - `cavity_volume`
  - `flow_rate`
  - `debris_concentration`
  - `dielectric_flow_rate`
  - `ionized_channel`

Wrapper implication:
- dielectric does not need a separate fast formula
- it needs an explicit per-step state bundle and a callable step boundary

### Wire

Current owner:
- [`wire.py`](../src/wedm/modules/wire.py)

Current compiled hot logic already exists:
- `resolve_discharge_partition(...)`
- `apply_thermal_core_inplace(...)`
- `apply_thermal_damage_core_inplace(...)`
- `advance_wire_step_inplace(...)`

Current module-owned non-kernel work still matters:
- convection coefficient refresh
- buffer/state syncing
- optional zone-mean logic

Boundary to preserve:

- Inputs:
  - `current`
  - `voltage`
  - `spark_status`
  - `dielectric_temperature`
  - `flow_rate`
  - `wire_unwinding_velocity`
  - wire-owned arrays and caches:
    - `temperature`
    - `damage`
    - `dT_dt`
    - `conv_loss_coeff`
    - position offset/buffers
- Outputs:
  - updated wire arrays and transport offset
  - `wire_max_damage`
  - `is_wire_broken`
  - exported diagnostics when state sync is requested

Wrapper implication:
- the fast wrapper should route through the wire-owned compiled helpers
- state syncing/logging remains a boundary concern, not part of the hot loop

### Mechanics

Current owner:
- [`mechanics.py`](../src/wedm/modules/mechanics.py)

Current behavior:
- computes acceleration from `target_delta`
- applies jerk, acceleration, and speed limits
- updates `wire_velocity` and `wire_position`
- maintains `prev_accel` as module-owned controller state

Boundary to preserve:

- Inputs:
  - `target_delta`
  - `wire_position`
  - `wire_velocity`
  - module-owned `prev_accel`
- Outputs:
  - updated `wire_position`
  - updated `wire_velocity`
  - updated `prev_accel`

Wrapper implication:
- mechanics is already close to an isolated scalar kernel
- the wrapper should call mechanics-owned step logic, not inline its own copy

## Environment-Owned Boundaries

These remain wrapper/scheduler concerns rather than module-owned physics:

- action cadence and action application
- `time_since_servo` gating
- batched step counting and batch early exit
- simulation time bookkeeping
- top-level termination checks
- control-step observation/reward emission

These are allowed to differ between the modular runner and fast wrapper as long as they preserve the same externally visible semantics.

## Required Shared Interfaces

`FWP-02` does not force exact function names yet, but it freezes the required categories:

1. Module reset/load-store boundary
- initialize module-owned episodic state
- load from `EDMState` or hot buffers
- store back to `EDMState` or hot buffers

2. Module microstep boundary
- callable once per microstep
- explicit numeric inputs/outputs
- explicit RNG inputs where randomness is used

3. Optional diagnostic/export boundary
- only responsible for logging-facing state sync
- must stay outside the core hot loop where possible

## What FWB-01 Can Assume

The next task may assume:

- hot-path buffers can mirror the current public state as long as `EDMState` remains the external API
- `spark_status` and `ionized_channel` may use sentinel-based numeric encodings inside the wrapper
- module kernels should be extracted/refined around the boundaries above instead of being reauthored in a new wrapper-only codepath

## Non-Goals

- selecting exact final buffer layouts
- rewriting every module to Numba in this task
- changing the physical meaning of any state field
