# Fast Wrapper Principles

## Goal

Add a faster execution wrapper around the existing simulation without creating a second source of physics truth.

The wrapper is allowed to change scheduling, batching, data layout, and state adapters. It is not allowed to introduce separate formulas or separate process logic that diverges from the existing modules.

## Current Reference Order

The modular reference path is [`WireEDMEnv.step`](../src/wedm/envs/wire_edm.py), which currently advances one microstep in this order:

1. Apply control action when `time_since_servo >= servo_interval`
2. `ignition.update(state)`
3. `material.update(state)`
4. `dielectric.update(state)`
5. `wire.update(state)`
6. Early exit if wire breaks
7. `mechanics.update(state)`
8. Time bookkeeping and termination checks
9. Observation/reward on control steps only

Any fast wrapper must preserve that effective per-step ordering unless a later task proves that a reordered path is exactly equivalent.

## Non-Negotiable Rules

1. Physics stays in the existing modules.
The source of truth for ignition, wire, dielectric, material, and mechanics logic remains in:
- [`ignition.py`](../src/wedm/modules/ignition.py)
- [`wire.py`](../src/wedm/modules/wire.py)
- [`dielectric.py`](../src/wedm/modules/dielectric.py)
- [`material.py`](../src/wedm/modules/material.py)
- [`mechanics.py`](../src/wedm/modules/mechanics.py)

2. The wrapper may only change execution strategy.
Allowed changes:
- batching multiple microsteps per Python call
- compact hot-path state buffers
- adapter layers between `EDMState` and wrapper buffers
- deterministic RNG pools for batched execution
- thin orchestration code that calls shared module kernels

Not allowed:
- duplicate physics formulas in a separate "fast simulator"
- duplicate state-transition rules maintained in parallel with the modules
- benchmark-only approximations that skip real per-step feedback

3. The modular environment remains the reference path.
The standard Gymnasium-facing path in [`wire_edm.py`](../src/wedm/envs/wire_edm.py) stays available for debugging, experimentation, visualization, and parity checks.

4. `batch_size` is explicit and independent of `servo_interval`.
`batch_size` is the wrapper's execution upper bound, not a control assumption. The wrapper may run up to `N` microsteps per internal call, but it must stop at any boundary where a new action could legally change the physics. In practice, the effective batch is clamped by the next action boundary, early termination, and any other required handoff to Python. This keeps the door open to policies that can act every microsecond while still allowing large batches for fixed-action benchmarks or slower controllers.

5. Public state/API compatibility must be preserved.
[`EDMState`](../src/wedm/core/state.py) remains the public state object seen by the environment, logger, and dashboard workflows. The wrapper may use compact internal buffers, but it must load from and store back to `EDMState` cleanly.

## Wrapper Architecture Constraints

The intended shape is:

- module files own the physics kernels and state-transition logic
- a hot-path adapter layer maps `EDMState` to compact wrapper buffers
- a batched wrapper loop schedules shared module kernels repeatedly
- control-step observations, rewards, and logging stay at the environment boundary

This means the project keeps:
- one modular reference runner
- one fast execution wrapper
- one source of physics truth

## State and Randomness Rules

1. Python-shaped state may be adapted, not replaced publicly.
Examples from the current code:
- `spark_status = [state, location_or_None, duration]`
- `ionized_channel = (location, duration) | None`

The wrapper may encode these as numeric buffers with sentinels, but only inside the hot path.

2. Batched randomness must be deterministic.
For batched execution, the wrapper may not call Python RNG inside the per-microstep hot loop. Random values for a batch must be pre-generated from `env.np_random` and consumed through a documented cursor/layout so same-seed modular-vs-wrapper comparisons remain possible. The current per-step compiled scheduler path may still draw scalar values from `env.np_random` each microstep to preserve branch-consumption parity with the modular reference path.

## Success Criteria

`FWP-01` is complete when these rules are frozen for the new board:

1. The wrapper is explicitly defined as a scheduler/adaptor layer, not a second simulator.
2. The current modular microstep order is documented as the reference contract.
3. `batch_size` is defined as an explicit wrapper parameter independent of `servo_interval`.
4. Promotion gates are measurable:
- fidelity must pass against the existing modular benchmark workflow
- wrapper and modular runs must support same-seed comparison
- the wrapper cannot become the primary performance path unless it matches fidelity and outperforms the modular path on both canonical meshes

## Promotion Gates

The wrapper may be considered valid for experimentation when:
- same-seed parity tests pass against the modular path
- the existing fidelity verification workflow reports `PASS`

The wrapper may be promoted to the primary performance path only when:
- parity remains green
- the frozen benchmark workflow shows throughput at least as good as the modular path on both canonical meshes (`0.20 mm` and `0.05 mm`)
- dashboard/reporting workflows still work on wrapper-produced outputs

## Non-Goals

- Replacing the modular env path
- Rewriting the simulator into a separate fast-only architecture
- Weakening fidelity rules to gain speed
- Removing rich state needed for plotting, logging, or debugging
