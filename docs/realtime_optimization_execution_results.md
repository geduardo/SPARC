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
