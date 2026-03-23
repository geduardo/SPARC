# Optimization Proposals for SPARC: The Path to Realtime

**Goal:** `1,000,000 steps/s` — 1 second wall time = 1 second simulated time at `dt = 1 µs`.

---

## Current State

### Frozen Baseline (fidelity contract)

From [`realtime_baseline_20260322_i1.json`](../outputs/profiling/realtime_baseline_20260322_i1.json):

| Scenario | Median steps/s | Wall / sim | Gap to target |
| :--- | ---: | ---: | ---: |
| `0.20 mm / 400 seg` | `38,284` | `26.12x` slower | `3.83%` of target |
| `0.05 mm / 1600 seg` | `34,477` | `29.01x` slower | `3.45%` of target |

The frozen baseline is the **fidelity contract** — every candidate must match its crater count, wire temperature, max damage, and workpiece position within tolerance. It is **not** the performance frontier.

### Best Balanced Candidate (performance frontier)

The dashboard tracks candidates beyond the frozen baseline. The best balanced result across both meshes is [`perf_candidate_ph13_verify.json`](../outputs/profiling/perf_candidate_ph13_verify.json), which outperforms the dashboard's latest archived snapshot (`perf_candidate_ph10_verify`) on the coarse mesh while being comparable on the fine mesh:

| Scenario | Median steps/s | µs/step | Vs baseline | Gap to target |
| :--- | ---: | ---: | ---: | ---: |
| `0.20 mm / 400 seg` | `109,638` | `9.12` | `+186%` | `10.96%` of target |
| `0.05 mm / 1600 seg` | `83,201` | `12.01` | `+141%` | `8.32%` of target |

For comparison, the dashboard's `perf_candidate_ph10_verify` shows `101,931` / `83,282` steps/s. PH-13 is used here because it is the best coarse-mesh result verified under the same fidelity contract.

A ~10x improvement is still needed from the frontier. A ~29x improvement is needed from the frozen baseline.

### Frontier Hotspot Breakdown (0.05mm / 1600 seg, PH-13)

| Module | Wall share | µs/step |
| :--- | ---: | ---: |
| `wire` | `53.24%` | `8.99` |
| — `thermal_core` | `30.06%` | `5.07` |
| — `state_sync` | `12.57%` | `2.12` |
| — `transport` | `2.44%` | `0.41` |
| `ignition` | `18.78%` | `3.17` |
| `dielectric` | `6.16%` | `1.04` |
| `mechanics` | `3.82%` | `0.64` |
| `material` | `2.46%` | `0.42` |
| `env.step` dispatch | ~`15%` | ~`1.8` |

Wire sub-bucket instrumentation already exists in the profiling pipeline and dashboard. No restoration needed.

### What The Numbers Imply

- Making `wire` free would give ~`2.1x` on the fine mesh (to ~175k). Not enough.
- Making `wire + ignition` free would give ~`3.6x` (to ~300k). Still not enough.
- Reaching `1,000,000 steps/s` requires **structural reduction** of total per-step work: eliminating Python dispatch from the hot loop AND reducing the wire thermal O(N) pass.

### Why The Previous Fast Wrapper Failed

The [fast-wrapper experiment](./fast_wrapper_lessons_learned.md) tried a Python wrapper around the modular microsteps. It failed because:

1. **State marshalling dominated** — `store_to_state`/`load_from_state` cost more than the physics.
2. **Batching collapsed** — with `servo_interval == dt == 1 µs`, the wrapper stopped every step anyway.
3. **RNG diverged** — fixed draw pools didn't match the conditional consumption pattern.

The lesson: the next attempt must be a **compiled loop**, not a Python orchestrator.

---

## Phase 1: Python Overhead Reduction

Low-risk, incremental wins that reduce per-step overhead while preserving the current modular architecture. Each is independently shippable and testable.

**Combined target: ~1.3–1.6x improvement** (frontier → ~110–135k steps/s on fine mesh).

### P1-01: `__slots__` on `EDMState`

**File:** [`core/state.py`](../src/wedm/core/state.py)

`EDMState` is a plain `@dataclass` without `__slots__`. Every attribute access goes through `__dict__` lookup. With ~50+ attribute reads/writes per step across all modules, this adds measurable overhead.

**Change:** Add `slots=True` to the `@dataclass` decorator (Python 3.10+).

**Expected gain:** 0.5–1.5 µs/step. **Risk:** Low.

### P1-02: Batched/Scalar RNG in Ignition

**File:** [`modules/ignition.py:581`](../src/wedm/modules/ignition.py#L581)

`_update_short_circuit_detection` calls `self.env.np_random.random(2)` every step, allocating a 2-element NumPy array, crossing the C-API boundary, then boxing each element with `float(rolls[0])`.

**Change:** Replace with two scalar `self.env.np_random.random()` calls (returns a Python float directly, no array allocation).

**Expected gain:** 0.5–1.0 µs/step. **Risk:** Very low. RNG stream order preserved.

### P1-03: Remove Redundant `float()` Casts

**Files:** [`modules/wire.py:812–842`](../src/wedm/modules/wire.py#L812-L842), [`modules/ignition.py:493`](../src/wedm/modules/ignition.py#L493)

`wire.update()` has 28 explicit `float()` casts on values that are already floats (module constants like `self.k_cond_coeff`, `self.params.spool_T`). Each `float()` call costs ~30–50ns × 28 ≈ ~1 µs/step. Similarly `ignition.update()` has redundant casts in generator settings resolution.

**Change:** Remove casts where the source is already a `float`. Keep only where the source is `Optional` or `int`.

**Expected gain:** 0.5–1.0 µs/step. **Risk:** Very low.

### P1-04: Non-Optional Voltage/Current on `EDMState`

**File:** [`core/state.py:40–41`](../src/wedm/core/state.py#L40-L41)

`voltage: Optional[float] = None` and `current: Optional[float] = None` force every consumer to check for `None` before use. On the hot path, both `ignition.update()` and `wire.update()` test `state.voltage is not None` every step.

**Change:** Default both to `0.0` instead of `None`. Verify no consumer relies on `None` semantics.

**Expected gain:** 0.3–0.5 µs/step. **Risk:** Low.

### P1-05: `__slots__` on Module Parameter Dataclasses

**Files:** [`modules/wire.py`](../src/wedm/modules/wire.py), [`modules/ignition.py`](../src/wedm/modules/ignition.py), [`modules/dielectric.py`](../src/wedm/modules/dielectric.py), [`modules/mechanics.py`](../src/wedm/modules/mechanics.py)

Each module reads its parameter dataclass (`WireModuleParameters`, `IgnitionModuleParameters`, etc.) dozens of times per step via `self.params.<field>`. These dataclasses also lack `__slots__`, paying the same `__dict__` lookup cost as `EDMState` but with more frequent reads in the wire and ignition hot paths.

**Change:** Add `slots=True` to all module parameter dataclasses. Complements P1-01 — together they cover the two main attribute-access hotspots.

**Expected gain:** 0.3–0.8 µs/step. **Risk:** Low.

> **Note on convection coefficient pre-computation:** An earlier draft proposed moving `_update_convection_coefficients` to control boundaries. This is ineffective for the current benchmark because `servo_interval == dt == 1 µs` — "control boundaries" means every microstep. The idea may become relevant if the benchmark contract changes to a longer servo interval, but it is not actionable now.

### Phase 1 — What We Deliberately Leave Alone

- **`spark_status` flattening** — Directionally correct, but too many consumers assume a 3-item list ([`state.py:73`](../src/wedm/core/state.py#L73), logger, integration tests). This encoding change belongs inside the hot-state bundle (P2-01), not as a public API break first.
- **`wire_material_positions_mm` deferral** — The repo intentionally keeps this aliased/live, and tests assert that behavior. This is a boundary/export redesign that fits in the P2 scope, not a simple `@property` swap.
- **`math.exp` vs `np.exp` in Numba** — Inside `@njit(fastmath=True)`, Numba lowers `np.exp(scalar)` to the same LLVM intrinsic as `math.exp`. Unverified gain; profile before claiming.

---

## Phase 2: Compiled Scheduler Over Module-Owned Kernels

This is the critical inflection point. The goal is to eliminate Python dispatch from the 1 µs tick while keeping module-owned physics kernels as the single source of truth.

**This is NOT "merge all 5 modules into one monolith."** It is a compiled scheduler that calls the same numeric kernels the modules already own, operating on a flat numeric state bundle, with `EDMState` sync only at boundaries.

**Combined target: ~3–5x total improvement** (frontier → ~250–420k steps/s on fine mesh).

### P2-01: Flat Numeric Hot-State Bundle

**Scope:** Define a pure-numeric representation for the ~30 scalar state variables and 4 wire arrays (`temperature`, `damage`, `dT_dt`, `conv_loss_coeff`) that the inner loop needs. No Python objects, no `Optional`, no lists.

Inside the hot path:
- `spark_status` becomes three numeric scalars with NaN sentinel (matching what the Numba kernels already use internally in `_advance_discharge_state`)
- `ionized_channel` becomes `(float, int)` with sentinel
- All module constants are pre-packed into a frozen tuple or `@jitclass`

`EDMState` remains the public API. The hot-state bundle is private to the compiled scheduler.

**Expected gain:** Prerequisite for P2-02. **Risk:** Medium.

### P2-02: Compiled Inner Loop (`@njit` Scheduler)

**Scope:** A single `@njit` function that executes the full microstep: ignition → material → dielectric → wire → mechanics → time bookkeeping — in the reference order defined by [`fast_wrapper_kernel_boundaries.md`](./fast_wrapper_kernel_boundaries.md).

The function body is NOT a rewrite. Each section calls (or inlines) the existing Numba kernels:
- Ignition: `_advance_short_circuit_state`, `_get_ignition_probability_scalar`, `_advance_discharge_state`
- Wire: `advance_wire_step_inplace` (transport + thermal + damage)
- Dielectric: scalar arithmetic (currently Python, promoted to Numba)
- Mechanics: scalar arithmetic (currently Python, promoted to Numba)
- Material: conditional crater increment (scalar)

This eliminates per-step: Python method dispatch (~1.8 µs), attribute access overhead, list/tuple construction, and all `float()` boxing.

**Expected gain:** 4–7 µs/step. **Risk:** High — largest single change, must be validated step-by-step against reference.

### P2-03: Branch-Consistent RNG Architecture

The hardest sub-problem of P2-02. The current RNG consumption pattern is **inherently branch-dependent**:

1. **Always:** 2 uniform draws (short-circuit detection)
2. **If idle and not short:** 1 uniform draw (ignition roll)
3. **If ignition succeeds:** 1 uniform draw (spark location)
4. **If fresh discharge:** 1 normal draw (crater volume)

The failed wrapper attempted fixed-layout draw pools, which diverged from this pattern.

**Safe first step (parity scaffold):** Keep RNG draws in Python, call the compiled kernel in stages:

```
# Per microstep (intermediate architecture):
rng_short = (np_random.random(), np_random.random())  # always 2 draws
result = compiled_step_part1(hot_state, rng_short, constants)
if result.needs_ignition_roll:
    rng_ign = np_random.random()
    if result.needs_location_roll:
        rng_loc = np_random.random()
    compiled_step_ignition(hot_state, rng_ign, rng_loc)
if result.is_fresh_discharge:
    rng_crater = np_random.normal(mean, std)
    compiled_step_material(hot_state, rng_crater)
```

This is 2–4 Numba transitions per step instead of 5+ module calls, with RNG consumed in the exact same branch pattern as the reference path. It is **not the final architecture** — Python still sits in the 1 µs loop for RNG dispatch. But it establishes bit-exact parity with the modular reference path, which is the hardest constraint to meet. Once parity is proven, a follow-up can explore moving RNG into Numba (e.g., via `numba.extending` wrapping of the `numpy.random.Generator` state) to eliminate the remaining Python transitions.

**Expected gain:** Part of P2-02 estimate. **Risk:** Medium-high — RNG fidelity is the hardest constraint.

### P2-04: Tighten Existing `step()` Fast Path

**File:** [`envs/wire_edm.py:184–268`](../src/wedm/envs/wire_edm.py#L184-L268)

The env already has fast-path machinery: `ScalarAction` dataclass ([line 30](../src/wedm/envs/wire_edm.py#L30)), `_uses_default_*` bypass flags ([lines 136–145](../src/wedm/envs/wire_edm.py#L136-L145)), inlined action application ([line 190](../src/wedm/envs/wire_edm.py#L190)). This is not greenfield.

Remaining overhead on the common benchmark path:
- `info` dict construction every step ([line 261](../src/wedm/envs/wire_edm.py#L261)) — ~0.3 µs/step
- `spark_status[0] == 1` check for time bookkeeping ([line 236](../src/wedm/envs/wire_edm.py#L236))
- Return tuple construction every step

**Change:** Add a `step_fast()` method or `__step_inner()` that skips info/obs/reward construction on non-control steps. Return only `(terminated, truncated)`.

**Expected gain:** 0.5–1.0 µs/step. **Risk:** Low-medium. New method, does not break existing API.

---

## Phase 3: Wire Thermal Algorithmic Reduction

If Phase 2 lands at ~250–420k steps/s, the remaining ~2.5–4x gap is almost entirely the wire thermal kernel. The O(N) conduction solve runs for **all N segments every microstep** — this is the hard barrier to realtime.

**Combined target: ~2–6x on top of Phase 2** (→ 500k–1M+ steps/s).

### P3-01: Active Thermal Window

The thermal diffusion timescale at 0.2mm segment length is:

```
τ = Δx² / (2α)    where α = k/(ρ·c) for brass
  = (2e-4)² / (2 × 3.59e-5)
  ≈ 560 µs
```

This means conduction propagates ~1 segment per ~560 µs. Over a 3 µs ON-time discharge, heat only spreads ~1 segment from the source. Yet the solver computes conduction across **all 400–1600 segments** every 1 µs step.

**Change:** Compute the full conduction-convection-damage update only for segments within an "active window" around:
- The spark/plasma location (±5–10 segments)
- The electrical contact zones (Joule heating regions)

Outside this window, temperature changes negligibly per step. Update cold tails every K steps (e.g., every 100–500 µs) or only when the window moves.

**Expected gain:** Cost drops from O(N) to O(W) where W ≈ 30–60 segments vs N = 400–1600. That's a **7–50x reduction** in wire thermal work per step. **Risk:** High — requires careful fidelity validation. Boundary conditions between active and inactive regions must be handled correctly.

### P3-02: SIMD-Friendly Loop Restructuring

**File:** [`modules/wire.py:462–498`](../src/wedm/modules/wire.py#L462-L498)

The wire thermal core loop currently interleaves: conduction computation, dT_dt accumulation, Joule heating, temperature update, and damage accumulation in a single pass. This mixed read-write pattern can inhibit LLVM autovectorization.

**Change:** Split into separate passes — one for `dT_dt` computation (read-only on `temperature`), one for temperature update, one for damage. Each becomes a clean vectorizable loop over a contiguous array.

Verify SIMD is actually achieved with `numba --annotate-html` or `NUMBA_DUMP_OPTIMIZED=1`.

**Expected gain:** 0.1–0.5 µs/step (small absolute, but helps at the margin). **Risk:** Low.

### P3-03: Enable Numba `cache=True` + AOT Compilation

Currently all Numba functions use `cache=False`. Enable caching to eliminate JIT recompilation on every startup. Consider `numba.pycc` AOT compilation for the fused kernel.

**Expected gain:** Startup time only — no per-step improvement. **Risk:** Low. Important for usability.

---

## GPU Assessment

**Verdict: Not recommended.**

- GPU kernel launch overhead is ~5–10 µs per dispatch — that alone exceeds the entire 1 µs/step budget.
- The workload is sequential: step N depends on step N-1.
- Arrays are small (400–1600 elements) — no parallelism to exploit.
- GPU would only help for **embarrassingly parallel** workloads like 1000+ independent episodes. That's a different axis (throughput, not latency).

The target is achievable on CPU with a compiled inner loop and algorithmic wire reduction.

---

## Fidelity Validation Strategy

Every candidate must pass:

| Check | Source | Tolerance | Harness constant |
| :--- | :--- | :--- | :--- |
| Crater count | Fidelity signature | Exact match (0 absolute) | `crater_count_abs = 0.0` |
| Wire temperature mean | Fidelity signature | < 0.5 K absolute | `wire_temperature_mean_abs = 0.5` |
| Wire max damage | Fidelity signature | < 1e-4 absolute | `wire_max_damage_abs = 1e-4` |
| Workpiece position | Fidelity signature | < 0.1 µm absolute | `workpiece_position_um_abs = 0.1` |
| Dashboard signals | `wire_temperature`, `wire_material_positions_mm`, `wire_head_idx`, `wire_offset_mm` | Present with correct shape | — |

These are the `DEFAULT_FIDELITY_TOLERANCES` from [`scripts/profile_simulation.py:476`](../scripts/profile_simulation.py#L476). All tolerances are **absolute**, not relative.

For Phase 2, the compiled path should be validated by **lockstep single-step comparison** against the modular reference path before running the full 200k-step benchmark.

References:
- [`tests/test_profile_fidelity.py`](../tests/test_profile_fidelity.py)
- [`tests/test_perf_verification_workflow.py`](../tests/test_perf_verification_workflow.py)
- [`scripts/verify_realtime_candidate.py`](../scripts/verify_realtime_candidate.py)

---

## Recommended Execution Order

### Guardrails Lane (runs throughout all phases)

Every phase produces candidates. Each candidate must be verified before promotion:

1. **Same-session reprofile** — Run the candidate under `scripts/profile_simulation.py` in the same session as the previous candidate to eliminate thermal/frequency drift.
2. **Fidelity lockstep check** — For Phase 2 (compiled path), run single-step comparison against the modular reference path before the full 200k-step benchmark.
3. **Dashboard refresh** — Update `performance_dashboard.html` after each verified candidate so the progress tracker stays current.

These are not optional post-hoc checks — they gate promotion.

### Phase A: Conservative modular pass (P1-01 through P1-05)

- Expected result: ~1.3–1.6x (frontier → ~110–135k steps/s on fine mesh)
- Each change is independently shippable and testable
- Re-profile after each to confirm gains stack

### Phase B: Compiled inner loop (P2-01 through P2-04)

- Expected result: ~3–5x total vs frontier (→ ~250–420k steps/s)
- P2-01 (hot-state bundle) is prerequisite for P2-02
- P2-03 (RNG parity scaffold) co-developed with P2-02 — establishes fidelity before further RNG migration
- P2-04 can be done in parallel with P2-01

### Phase C: Wire thermal reduction (P3-01, P3-02)

- Expected result: ~8–30x total vs frontier (→ ~500k–1M+ steps/s)
- Only pursue if the realtime target is a hard requirement
- P3-01 (active window) is the highest-impact item in the entire plan
- **Without Phase C, reaching 1,000,000 steps/s is unlikely**

### Non-critical (land anytime)

- **P3-03 (Numba `cache=True` + AOT)** — Startup time only, no per-step improvement. Useful for usability but not on the realtime critical path. Can land independently at any point.

### Summary

| Phase | Target range | Key risk | Prerequisite |
| :--- | :--- | :--- | :--- |
| Guardrails | — | Low | None (runs throughout) |
| A (modular cleanup) | 110–135k steps/s | Low | None |
| B (compiled scheduler) | 250–420k steps/s | Medium-high | Phase A recommended |
| C (wire algorithmic) | 500k–1M+ steps/s | High | Phase B required |
| Non-critical | Startup time | Low | None |
