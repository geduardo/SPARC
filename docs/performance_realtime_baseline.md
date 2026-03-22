# Conservative Realtime Benchmark

This is the baseline benchmark for the conservative performance program on this
PC. The goal of this phase is simple: improve throughput without losing physics
outputs, exported data, or simulation quality.

## Target

- Realtime target: `1,000,000 steps/s`
- Interpretation: `1 s wall / 1 s simulated` at `dt = 1 us`
- Secondary metric: `wall seconds per simulated second`
- Success direction: higher `steps/s`, lower `wall s / sim s`

## Benchmark Contract

Use the local profiling harness against the local `src` tree:

```bash
python scripts/profile_simulation.py --segment-len 0.2 --segment-len 0.05 --steps 200000 --warmup 5000 --repeats 2 --current-mode 1 --hotspots both --json-out outputs/profiling/realtime_baseline_20260322_i1.json
```

Or run the frozen preset wrapper that keeps the same workload and refreshes the
HTML dashboard automatically:

```bash
python scripts/profile_realtime_baseline.py
```

Benchmark settings:

- `seed=123`
- `initial_gap=12 um`
- `servo_interval=1 us`
- `workpiece_height=20 mm`
- action: `servo=0.25`
- generator target voltage: `90 V`
- current mode: `I1`
- pulse timing: `ON=3 us`, `OFF=20 us`
- meshes:
  - `0.20 mm` segments, `400` wire segments
  - `0.05 mm` segments, `1600` wire segments

This benchmark is intentionally conservative:

- it uses the existing physics and data paths
- it includes hotspot capture
- it records machine and power context for comparability checks
- it does not use approximation shortcuts or reduced logging contracts

## Baseline Snapshot

Source report:

- [`realtime_baseline_20260322_i1.json`](../outputs/profiling/realtime_baseline_20260322_i1.json)

Current baseline on this PC, collected on March 22, 2026:

| Scenario | Median steps/s | Wall s / sim s | % of target | Termination | Top hotspot |
| --- | ---: | ---: | ---: | --- | --- |
| `0.20 mm / 400 seg` | `38,284.48` | `26.12x` slower | `3.83%` | `completed` | `wire` `53.28%` |
| `0.05 mm / 1600 seg` | `34,476.81` | `29.01x` slower | `3.45%` | `completed` | `wire` `59.79%` |

Latest leading bottlenecks from the same report:

- wire update path dominates both meshes
- ignition remains the second major bucket at roughly `16%` to `19%`
- the lower-current contract now completes the full step budget on both meshes
- crater count now reflects fresh crater-forming discharges directly, even when
  long-run analysis history is disabled
- the current conservative program should attack wire and ignition before
  smaller environment bookkeeping costs

## Fidelity Guardrails

The profiling harness now records a `fidelity_signature` per scenario and can
compare a candidate run against a baseline report.

Guardrail fields:

- termination reason
- crater count
- mean wire temperature
- max wire damage
- final workpiece position
- dashboard-required signals:
  - `wire_temperature`
  - `wire_material_positions_mm`
  - `wire_head_idx`
  - `wire_offset_mm`

Example comparison run:

```bash
python scripts/profile_simulation.py --segment-len 0.2 --segment-len 0.05 --steps 200000 --warmup 5000 --repeats 2 --current-mode 1 --hotspots both --compare-to outputs/profiling/realtime_baseline_20260322_i1.json --json-out outputs/profiling/candidate_report.json
```

Or use the verification wrapper that reuses the frozen preset, archives the
candidate as `outputs/profiling/perf_candidate_<timestamp>.json`, writes a
throughput delta summary back into the report, and refreshes the dashboard:

```bash
python scripts/verify_realtime_candidate.py
```

## Tracking Artifacts

- HTML dashboard:
  - [`performance_dashboard.html`](../outputs/profiling/performance_dashboard.html)
- dashboard generator:
  - [`build_perf_dashboard.py`](../scripts/build_perf_dashboard.py)
- frozen preset runner:
  - [`profile_realtime_baseline.py`](../scripts/profile_realtime_baseline.py)
- candidate verification runner:
  - [`verify_realtime_candidate.py`](../scripts/verify_realtime_candidate.py)
- optimization board:
  - [`optimization-plan.canvas`](../optimization-plan.canvas)

## Notes

- The benchmark is valid only when compared under roughly the same machine
  power state. Battery or thermal throttling will skew absolute throughput.
- `PB-02` owns the stricter machine-context capture and preset hardening.
- `PG-01` owns the explicit no-regression fidelity checks that must accompany
  future speedups.
- `PG-02` owns the one-command candidate verification workflow against the
  canonical baseline.
- `PR-02` owns the archived progress view in the standalone dashboard.
