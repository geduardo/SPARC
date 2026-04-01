# Realtime Optimization Execution Results

Date: `2026-03-22`

This log records the work completed for the red canvas tasks that were advanced to cyan in this pass.

## Benchmark Contract

All performance measurements in this document use the same workload:

```bash
python scripts/profile_simulation.py --segment-len 0.2 --segment-len 0.05 --steps 1000000 --warmup 5000 --repeats 1 --current-mode 1 --hotspots module --json-out <candidate>.json
```

Why this baseline:

- The frozen repo baseline in `outputs/profiling/realtime_baseline_20260322_i1.json` uses `200000` timed steps.
- A `1M` candidate run cannot be compared directly to that `200k` report for fidelity/throughput deltas.
- `outputs/profiling/phaseA_pre_1m.json` was created first from the current tree and used as the local same-workload reference for this execution sequence.

## Validation

- Full test suite after the final change: `python -m pytest -q`
- Result: `92 passed in 46.15s`
- All `1M` comparison runs passed fidelity against the immediately previous same-workload report.

## Per-Task Results

| Task | Report | 0.20 mm steps/s | Delta vs prev | 0.05 mm steps/s | Delta vs prev | Fidelity | Assessment |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| Baseline | `outputs/profiling/phaseA_pre_1m.json` | `109519.06` | `-` | `85249.87` | `-` | n/a | Starting point for this execution pass |
| `PAM-02` scalar RNG in ignition | `outputs/profiling/pam02_scalar_rng_1m.json` | `108676.00` | `-0.8%` | `80465.08` | `-5.6%` | PASS | No reliable env-level gain; ignition-local change was smaller than run-to-run variance |
| `PAM-03` remove redundant `float()` casts | `outputs/profiling/pam03_cast_cleanup_1m.json` | `116116.66` | `+6.8%` | `90859.90` | `+12.9%` | PASS | Clear measured win; best standalone optimization in this pass |
| `PAM-04` non-optional `voltage/current` | `outputs/profiling/pam04_non_optional_current_voltage_1m.json` | `116979.09` | `+0.7%` | `90772.55` | `-0.1%` | PASS | Small coarse-mesh win, flat fine-mesh result; useful mainly as hot-path cleanup |
| `PAM-06` slots on module param dataclasses | `outputs/profiling/pam06_param_slots_1m.json` | `114555.14` | `-2.1%` | `88414.00` | `-2.6%` | PASS | No demonstrated steady-state throughput gain by itself |
| `PBC-01` flat numeric hot-state bundle | `outputs/profiling/pbc01_hot_state_bundle_1m.json` | `105329.47` | `-8.1%` | `91972.05` | `+4.0%` | PASS | Prerequisite infrastructure only; not on the execution path, so throughput movement is not attributable |

## Code Changes

### `PAM-02`

- Replaced `np_random.random(2)` in `src/wedm/modules/ignition.py` with two scalar draws.
- Preserved two-draw RNG consumption so fidelity stayed aligned with the reference path.

### `PAM-03`

- Removed redundant `float()` casts in:
  - `src/wedm/modules/ignition.py`
  - `src/wedm/modules/wire.py`
- This reduced cast churn in the hot loop without changing external semantics.

### `PAM-04`

- Changed `EDMState.voltage` and `EDMState.current` defaults from optional `None` to scalar `0.0` in `src/wedm/core/state.py`.
- Removed remaining hot-path `None` handling for those two fields in ignition/wire.
- Added regression coverage for direct state defaults in `tests/test_env_integration.py`.

### `PAM-06`

- Added `slots=True` to:
  - `src/wedm/modules/ignition.py`
  - `src/wedm/modules/wire.py`
  - `src/wedm/modules/dielectric.py`
  - `src/wedm/modules/mechanics.py`
- Added regression coverage for slotted parameter objects in `tests/test_env_integration.py`.
- Follow-up decision on `2026-03-23`: reverted because it showed no steady-state gain and added rigidity. See [`docs/realtime_optimization_non_wins.md`](./realtime_optimization_non_wins.md).

### `PBC-01`

- Added `src/wedm/core/hot_state.py` with `HotStateBundle`.
- Added `WireEDMEnv.build_hot_state_bundle()` and `WireEDMEnv.apply_hot_state_bundle()` in `src/wedm/envs/wire_edm.py`.
- Exported `HotStateBundle` via:
  - `src/wedm/core/__init__.py`
  - `src/wedm/__init__.py`
- Added `tests/test_hot_state_bundle.py` covering:
  - numeric sentinel encoding
  - round-trip restore into a compatible env
  - incompatible wire-shape rejection

## Practical Readout

- The only clearly measured env-level throughput win in this sequence was `PAM-03`.
- `PAM-04` is worth keeping because it simplifies the hot-state contract for later compiled work.
- `PAM-02` and `PAM-06` did not show reliable standalone gains in `1M` full-environment runs.
- `PBC-01` should be treated as enabling infrastructure for `PBC-02` and `PBC-03`, not as a performance result.

## Canvas Outcome

The tasks that were ready/red at the start of this pass are now cyan/review:

- `PAM-02`
- `PAM-03`
- `PAM-04`
- `PAM-06`
- `PBC-01`

Remaining work on the board is still purple/proposed, including:

- `PAM-01`
- `PBC-02`
- `PBC-03`
- `PBC-04`
- `GU-01` / `GU-02` / `GU-03`
- `PCW-01` / `PCW-02`

## Recommended Next Step

The next meaningful optimization step is `PBC-02`, using the new hot-state bundle as the boundary for a compiled scheduler. Without that, the remaining path to `1,000,000 steps/s` is not available.

## Addendum — `2026-03-23` `PBC-02` Dashboard Candidate

The compiled scheduler is now wired into the standard profiling and verification flow:

- `scripts/profile_simulation.py` accepts `--engine modular|compiled`
- `scripts/verify_realtime_candidate.py` forwards that engine into a dashboard-compatible `perf_candidate_*.json`
- `scripts/build_perf_dashboard.py` now shows the engine in the latest snapshot and history table

### Verified Candidate

Command:

```bash
python scripts/verify_realtime_candidate.py --engine compiled
```

Output report:

- `outputs/profiling/perf_candidate_compiled_20260323_015424.json`

Frozen-baseline comparison (`outputs/profiling/realtime_baseline_20260322_i1.json`):

| Scenario | Baseline steps/s | Compiled candidate steps/s | Delta | Fidelity |
| --- | ---: | ---: | ---: | --- |
| `0.20 mm / 400 seg` | `38284.48` | `115924.26` | `+202.80%` | PASS |
| `0.05 mm / 1600 seg` | `34476.81` | `90135.24` | `+161.44%` | PASS |

The rebuilt dashboard now tracks this report as the latest snapshot:

- `outputs/profiling/performance_dashboard.html`
- Latest report path: `outputs/profiling/perf_candidate_compiled_20260323_015424.json`

### 1M-Step Sanity Check

Command:

```bash
python scripts/bench_compiled.py --steps 1000000 --warmup 5000 --repeats 1
```

Results:

| Scenario | Modular steps/s | Compiled steps/s | Speedup |
| --- | ---: | ---: | ---: |
| `0.20 mm / 400 seg` | `93337.18` | `117876.09` | `1.263x` |
| `0.05 mm / 1600 seg` | `69107.99` | `84588.56` | `1.224x` |

Readout:

- The dashboard candidate gain is real and survives a longer `1M`-step A/B run.
- The compiled path is still well short of realtime and remains behind the strongest modular coarse-mesh snapshot.
- The next practical target is not another small modular cleanup; it is further reduction of Python wrapper overhead around the compiled scheduler (`PBC-04`), then wire-side algorithmic reduction.

## Addendum — `2026-03-30` `PBC-04` Fast-Step Path

`PBC-04` tightened the env fast path without changing the public Gym API:

- Added `step_fast()` and `step_compiled_fast()` in `src/wedm/envs/wire_edm.py`
- `scripts/profile_simulation.py` now prefers the fast-step path when available
- `scripts/bench_compiled.py` now uses the same fast-step path for long A/B runs
- Compiled control-mode resolution now caches unchanged modes instead of recomputing peak current and crater geometry on every control step

### Verified Candidate

Command:

```bash
python scripts/verify_realtime_candidate.py --engine compiled
```

Output report:

- `outputs/profiling/perf_candidate_compiled_20260330_014515.json`

Frozen-baseline comparison (`outputs/profiling/realtime_baseline_20260322_i1.json`):

| Scenario | Baseline steps/s | `PBC-02` compiled candidate | `PBC-04` compiled candidate | Delta vs `PBC-02` | Fidelity |
| --- | ---: | ---: | ---: | ---: | --- |
| `0.20 mm / 400 seg` | `38284.48` | `115924.26` | `205800.12` | `+77.53%` | PASS |
| `0.05 mm / 1600 seg` | `34476.81` | `90135.24` | `154805.23` | `+71.75%` | PASS |

The dashboard now tracks this report as the latest snapshot:

- `outputs/profiling/performance_dashboard.html`
- Latest report path: `outputs/profiling/perf_candidate_compiled_20260330_014515.json`

### 1M-Step Sanity Check

Command:

```bash
python scripts/bench_compiled.py --steps 1000000 --warmup 5000 --repeats 1
```

Results:

| Scenario | Modular steps/s | Compiled steps/s | Speedup |
| --- | ---: | ---: | ---: |
| `0.20 mm / 400 seg` | `159335.15` | `217061.46` | `1.362x` |
| `0.05 mm / 1600 seg` | `131774.00` | `153622.34` | `1.166x` |

### Validation

- `python -m pytest -q` -> `120 passed`
- Targeted parity/profiler tests added for:
  - `step_fast()` parity vs `step()`
  - `step_compiled_fast()` parity vs `step_compiled()`
  - profiler preference for fast-step methods
  - compiled mode-cache reuse across repeated control steps

Readout:

- `PBC-04` is a real measured win.
- The coarse mesh benefited more than the fine mesh, which is consistent with cutting Python overhead while leaving the wire thermal kernel untouched.
- The next likely step is still `PBC-03`, then wire algorithmic reduction (`PCW-01`).

## Addendum - `2026-03-30` `PBC-03` Staged RNG Architecture

`PBC-03` was implemented and validated, but it was not kept as the active compiled path.

What was attempted:

- Split the compiled orchestrator into staged helpers for:
  - short-circuit plus ignition-branch preparation
  - discharge-state advance
  - deterministic finalize work after RNG draws
- Added explicit RNG-consumption parity coverage in `tests/test_compiled_step.py`

What happened:

- The first staged version failed fidelity because `fastmath=True` on the staged finalize kernel interacted badly with the NaN flow-condition sentinel and caused early wire breakage.
- Removing `fastmath` fixed fidelity, but the staged public path still regressed against the shipped `PBC-04` path on long runs.

### Same-Session `1M` A/B: staged vs legacy `PBC-04`

Command basis:

```bash
python scripts/bench_compiled.py --steps 1000000 --warmup 5000 --repeats 1
```

Measured on a direct same-session compiled-only comparison:

| Scenario | Staged `PBC-03` | Legacy `PBC-04` | Winner |
| --- | ---: | ---: | --- |
| `0.20 mm / 400 seg` | `150481.66` | `172676.77` | legacy `+14.7%` |
| `0.05 mm / 1600 seg` | `114377.84` | `121188.45` | legacy `+6.0%` |

### Verification Outcome

- Staged candidate (before rollback): fidelity `PASS`, but only `107965.16` steps/s (`0.20 mm`) and `66752.04` steps/s (`0.05 mm`)
- Decision: restore the simpler `PBC-04` public path and record `PBC-03` as a non-win

### Final State After Rollback

- Public compiled scheduler path restored to the legacy `PBC-04` orchestration
- Dashboard rebuilt after removing the failed temporary candidate artifacts
- Validation:
  - `python -m pytest -q` -> `121 passed`
  - `python scripts/bench_compiled.py --steps 1000000 --warmup 5000 --repeats 1`

Final `1M` bench on the restored path:

| Scenario | Modular steps/s | Compiled steps/s | Speedup |
| --- | ---: | ---: | ---: |
| `0.20 mm / 400 seg` | `108544.86` | `148699.97` | `1.370x` |
| `0.05 mm / 1600 seg` | `88475.76` | `121287.48` | `1.371x` |

## Addendum - `2026-03-30` `PCW-02` SIMD-Friendly Wire-Loop Restructuring

`PCW-02` was attempted on the conservative path and then rolled back.

What was attempted:

- Split the interleaved wire thermal kernel into clearer passes for:
  - thermal derivative computation
  - temperature update
  - damage accumulation
- Routed the compiled wire step through those helpers to try to expose cleaner vectorizable loops inside `src/wedm/modules/wire.py`

What happened:

- The split-pass version did not preserve the accepted thermal behavior.
- The first candidate failed fidelity on mean wire temperature in both benchmark meshes while leaving crater count and workpiece position effectively unchanged.
- It also underperformed the already-shipped `PBC-04` compiled path, so there was no reason to keep carrying the extra kernel complexity.

### Failed Candidate Verification

Command:

```bash
python scripts/verify_realtime_candidate.py --engine compiled --skip-dashboard --output outputs/profiling/pcw02_verify_tmp.json
```

Result before rollback:

| Scenario | Verified steps/s | Fidelity | Key failure |
| --- | ---: | --- | --- |
| `0.20 mm / 400 seg` | `81346.49` | FAIL | wire temperature mean `312.30 K -> 296.82 K` |
| `0.05 mm / 1600 seg` | `52975.43` | FAIL | wire temperature mean `312.30 K -> 296.86 K` |

Other fidelity signals on that failed candidate remained aligned:

- `termination_reason`: matched
- `crater_count`: matched
- `workpiece_position_um`: matched

### Restored-Path Validation

After restoring the original wire kernel path:

- `python -m pytest tests/test_wire_kernels.py tests/test_compiled_step.py tests/test_profile_fidelity.py -q` -> `38 passed`
- `python scripts/verify_realtime_candidate.py --engine compiled --skip-dashboard --output outputs/profiling/pcw02_restore_check.json`

Restored-path check:

| Scenario | Baseline steps/s | Restored compiled steps/s | Fidelity |
| --- | ---: | ---: | --- |
| `0.20 mm / 400 seg` | `38284.48` | `104877.66` | PASS |
| `0.05 mm / 1600 seg` | `34476.81` | `76622.92` | PASS |

Quick same-session `200k` A/B after the rollback:

| Scenario | Modular steps/s | Compiled steps/s | Speedup |
| --- | ---: | ---: | ---: |
| `0.20 mm / 400 seg` | `64057.49` | `92053.93` | `1.437x` |
| `0.05 mm / 1600 seg` | `54977.49` | `83074.70` | `1.511x` |

Decision:

- Revert `PCW-02` and record it as a conservative-track non-win.
- Do not keep the split-pass thermal kernel without a stronger physics argument and dedicated thermal-validation work.

## Addendum - `2026-04-01` `PBC-05` Numeric Action Packet + Compiled Env Bookkeeping

`PBC-05` tightened the compiled fast path without changing the physics kernels.

What changed:

- Added a pre-resolved `CompiledActionPacket` in `src/wedm/envs/wire_edm.py`
- Cached immutable `ScalarAction` inputs as resolved compiled packets, so repeated compiled stepping no longer re-decodes generator control or re-resolves crater/current settings every microstep
- Exposed `compile_action()` for callers that want to pre-resolve a compiled action explicitly
- Folded compiled-path termination status into `compiled_microstep()` in `src/wedm/core/compiled_step.py`, removing the extra Python-side termination comparisons from the hot path
- Updated `scripts/profile_simulation.py` and `scripts/bench_compiled.py` to precompile the action once per env run when the compiled engine is selected

### Verified Candidate

Official uncontended command:

```bash
python scripts/verify_realtime_candidate.py --engine compiled
```

Output report:

- `outputs/profiling/perf_candidate_compiled_20260401_152709.json`

Frozen-baseline comparison (`outputs/profiling/realtime_baseline_20260322_i1.json`):

| Scenario | Baseline steps/s | `PBC-05` compiled candidate | Fidelity |
| --- | ---: | ---: | --- |
| `0.20 mm / 400 seg` | `38284.48` | `213389.81` | PASS |
| `0.05 mm / 1600 seg` | `34476.81` | `158583.94` | PASS |

Relative to the best verified `PBC-04` candidate (`perf_candidate_compiled_20260330_014515.json`):

| Scenario | `PBC-04` best verified | `PBC-05` verified | Delta |
| --- | ---: | ---: | ---: |
| `0.20 mm / 400 seg` | `205800.12` | `213389.81` | `+3.69%` |
| `0.05 mm / 1600 seg` | `154805.23` | `158583.94` | `+2.44%` |

The dashboard now tracks this report as the latest snapshot:

- `outputs/profiling/performance_dashboard.html`
- Latest report path: `outputs/profiling/perf_candidate_compiled_20260401_152709.json`

### 1M-Step Sanity Check

Command:

```bash
python scripts/bench_compiled.py --steps 1000000 --warmup 5000 --repeats 1
```

Results:

| Scenario | Modular steps/s | Compiled steps/s | Speedup |
| --- | ---: | ---: | ---: |
| `0.20 mm / 400 seg` | `180709.05` | `226510.81` | `1.253x` |
| `0.05 mm / 1600 seg` | `136429.79` | `168103.65` | `1.232x` |

### Validation

- `python -m pytest -q` -> `124 passed`
- `python -m pytest tests/test_compiled_step.py tests/test_profile_fidelity.py tests/test_wire_kernels.py -q` -> `41 passed`
- Added regression coverage for:
  - precompiled action-packet parity vs scalar compiled stepping
  - packet stepping without `_decode_action()` calls
  - profiler precompiling compiled actions once per env run

Readout:

- `PBC-05` is a real but modest conservative win.
- The gain came from removing control-path overhead around the compiled scheduler, not from changing the thermal or discharge physics.
- We are still well short of realtime, but this cut keeps the conservative path moving without touching the solver contract.
