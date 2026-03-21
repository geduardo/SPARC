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
python scripts/profile_simulation.py --segment-len 0.2 --segment-len 0.05 --steps 200000 --warmup 5000 --repeats 2 --hotspots both --json-out outputs/profiling/realtime_baseline_20260321.json
```

Benchmark settings:

- `seed=123`
- `initial_gap=12 um`
- `servo_interval=1 us`
- `workpiece_height=20 mm`
- action: `servo=0.25`
- generator target voltage: `90 V`
- current mode: `I5`
- pulse timing: `ON=3 us`, `OFF=20 us`
- meshes:
  - `0.20 mm` segments, `400` wire segments
  - `0.05 mm` segments, `1600` wire segments

This benchmark is intentionally conservative:

- it uses the existing physics and data paths
- it includes hotspot capture
- it does not use approximation shortcuts or reduced logging contracts

## Baseline Snapshot

Source report:

- [`realtime_baseline_20260321.json`](../outputs/profiling/realtime_baseline_20260321.json)

Current baseline on this PC, collected on March 21, 2026:

| Scenario | Median steps/s | Wall s / sim s | % of target | Termination | Top hotspot |
| --- | ---: | ---: | ---: | --- | --- |
| `0.20 mm / 400 seg` | `37,714.66` | `26.51x` slower | `3.77%` | `wire_broken` | `wire` `50.77%` |
| `0.05 mm / 1600 seg` | `24,372.43` | `41.03x` slower | `2.44%` | `wire_broken` | `wire` `55.51%` |

Latest leading bottlenecks from the same report:

- wire update path dominates both meshes
- ignition remains the second major bucket at roughly `23%`
- the current conservative program should attack wire and ignition before
  smaller environment bookkeeping costs

## Tracking Artifacts

- HTML dashboard:
  - [`performance_dashboard.html`](../outputs/profiling/performance_dashboard.html)
- dashboard generator:
  - [`build_perf_dashboard.py`](../scripts/build_perf_dashboard.py)
- optimization board:
  - [`optimization-plan.canvas`](../optimization-plan.canvas)

## Notes

- The benchmark is valid only when compared under roughly the same machine
  power state. Battery or thermal throttling will skew absolute throughput.
- `PB-02` owns the stricter machine-context capture and preset hardening.
- `PG-01` owns the explicit no-regression fidelity checks that must accompany
  future speedups.
