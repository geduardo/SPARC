# Realtime Optimization Non-Wins

Date: `2026-03-23`

This note records optimization attempts from the recent realtime pass that did not produce a reliable env-level throughput win on the `1M`-step benchmark, and the codebase decision taken afterward.

## Decision Rule

When a change does not show a meaningful performance gain, keep it only if it is clearly the simpler and lower-maintenance form of the same logic. Otherwise, revert it.

## Benchmark Basis

All numbers below come from the same `1M`-step workload used in the execution log:

```bash
python scripts/profile_simulation.py --segment-len 0.2 --segment-len 0.05 --steps 1000000 --warmup 5000 --repeats 1 --current-mode 1 --hotspots module --json-out <candidate>.json
```

The local same-workload baseline for that pass was:

- [`outputs/profiling/phaseA_pre_1m.json`](../outputs/profiling/phaseA_pre_1m.json)

## Findings

### `PAM-02` Scalar RNG in ignition

Files:

- [`src/wedm/modules/ignition.py`](../src/wedm/modules/ignition.py)
- [`outputs/profiling/pam02_scalar_rng_1m.json`](../outputs/profiling/pam02_scalar_rng_1m.json)

Measured result versus the immediately previous run:

- `0.20 mm`: `109519.06 -> 108676.00 steps/s` (`-0.8%`)
- `0.05 mm`: `85249.87 -> 80465.08 steps/s` (`-5.6%`)
- Fidelity: PASS

Conclusion:

- No reliable end-to-end throughput win was demonstrated.
- The scalar-draw version is still the simpler expression of the logic: no temporary 2-element array, no indexing, and clearer naming of the two rolls.

Disposition:

- Kept.

Reason:

- Even without a measured speedup, it is simpler and easier to read than `random(2)` plus indexing.

### `PAM-06` Slots on module parameter dataclasses

Files involved during the experiment:

- [`src/wedm/modules/ignition.py`](../src/wedm/modules/ignition.py)
- [`src/wedm/modules/wire.py`](../src/wedm/modules/wire.py)
- [`src/wedm/modules/dielectric.py`](../src/wedm/modules/dielectric.py)
- [`src/wedm/modules/mechanics.py`](../src/wedm/modules/mechanics.py)
- [`outputs/profiling/pam06_param_slots_1m.json`](../outputs/profiling/pam06_param_slots_1m.json)

Measured result versus the immediately previous run:

- `0.20 mm`: `116979.09 -> 114555.14 steps/s` (`-2.1%`)
- `0.05 mm`: `90772.55 -> 88414.00 steps/s` (`-2.6%`)
- Fidelity: PASS

Conclusion:

- No steady-state throughput win was demonstrated.
- `slots=True` makes these dataclasses slightly more rigid for little practical benefit in this codebase.

Disposition:

- Reverted on `2026-03-23`.

Reason:

- It did not help performance and it is not the simplest or lowest-maintenance form.

## Notes On Other Changes

### `PBC-01` Hot-state bundle

- [`src/wedm/core/hot_state.py`](../src/wedm/core/hot_state.py)

This did not show a standalone speedup, but it is not in the same category as the two items above.

Reason:

- It is prerequisite infrastructure for a compiled scheduler, not a standalone optimization expected to move the benchmark on its own.

Current decision:

- Kept for the Phase B path.

## Current Policy Outcome

- Keep measured winners.
- Keep non-winners only when they are simpler than the alternative.
- Remove non-winners that add rigidity or maintenance cost without a demonstrated benefit.

Applied here:

- `PAM-02`: kept
- `PAM-06`: reverted
