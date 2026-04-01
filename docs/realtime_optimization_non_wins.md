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

### `PBC-03` Staged RNG/discharge/finalize split

Files involved during the experiment:

- [`src/wedm/core/compiled_step.py`](../src/wedm/core/compiled_step.py)
- [`tests/test_compiled_step.py`](../tests/test_compiled_step.py)

Measured result:

- The staged split initially failed fidelity because `fastmath=True` on the staged finalize kernel interacted badly with the NaN-based flow-condition sentinel and drove early wire breakage.
- After removing that unsafe `fastmath` flag, fidelity returned to `PASS`, but the staged public path still did not beat the simpler `PBC-04` orchestrator on the long same-session benchmark.

Same-session `1M` compiled-only A/B (`staged` vs `legacy PBC-04`):

- `0.20 mm`: `150481.66 -> 172676.77 steps/s` (`legacy +14.7%`)
- `0.05 mm`: `114377.84 -> 121188.45 steps/s` (`legacy +6.0%`)

Additional verification on the staged path before rollback:

- `python scripts/verify_realtime_candidate.py --engine compiled --output outputs/profiling/pbc03_verify_tmp.json --skip-dashboard`
- Result before rollback: fidelity `PASS`, but verified throughput only `107965.16` steps/s (`0.20 mm`) and `66752.04` steps/s (`0.05 mm`), both below the existing `PBC-04` source-of-truth candidate.

Disposition:

- Reverted on `2026-03-30` by restoring the public `compiled_microstep()` path to the simpler `PBC-04` implementation.

Reason:

- The staged split added maintenance cost, required special handling around NaN sentinels, and still lost to the legacy path on the `1M` benchmark.
- The only part worth keeping was the explicit RNG-consumption parity test coverage.

### `PCW-02` SIMD-friendly wire-loop restructuring

Files involved during the experiment:

- [`src/wedm/modules/wire.py`](../src/wedm/modules/wire.py)
- [`tests/test_wire_kernels.py`](../tests/test_wire_kernels.py)
- [`tests/test_profile_fidelity.py`](../tests/test_profile_fidelity.py)

Measured result:

- The attempted split of the thermal wire kernel into derivative, temperature-update, and damage passes did not preserve the accepted thermal behavior.
- Candidate verification failed on mean wire temperature while leaving crater count and workpiece position effectively unchanged.

Failed verification snapshot:

- `0.20 mm`: `81346.49` steps/s, wire temperature mean `312.30 K -> 296.82 K`, fidelity `FAIL`
- `0.05 mm`: `52975.43` steps/s, wire temperature mean `312.30 K -> 296.86 K`, fidelity `FAIL`

Validation after rollback:

- `python -m pytest tests/test_wire_kernels.py tests/test_compiled_step.py tests/test_profile_fidelity.py -q` -> `38 passed`
- Restored-path verification returned to fidelity `PASS` at `104877.66` steps/s (`0.20 mm`) and `76622.92` steps/s (`0.05 mm`)

Disposition:

- Reverted on `2026-03-30` by restoring the original interleaved thermal kernel path.

Reason:

- This is exactly the kind of optimization that risks changing effective physics while only offering modest theoretical upside.
- The split-pass form was more complex, failed fidelity immediately, and did not beat the accepted `PBC-04` source-of-truth path.
