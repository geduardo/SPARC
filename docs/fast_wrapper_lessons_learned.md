# Fast Wrapper Lessons Learned

## Outcome

The first fast-wrapper attempt was not promoted.

The idea was to keep all physics inside the existing modules and add a batched wrapper around them. That preserved modularity, but the Python wrapper overhead was larger than the savings from batching.

## What Failed

### 1. State marshalling dominated runtime

The wrapper repeatedly converted between a hot-path bundle and `EDMState` on every microstep.

That made the wrapper spend most of its wall time in:

- `store_to_state`
- `load_from_state`
- optional-float decoding

Instead of removing Python overhead, the wrapper added more of it.

### 2. Batching collapsed when control cadence was 1 us

The frozen benchmark uses `servo_interval == dt == 1 us`.

That means the wrapper had to stop and reapply control every microstep, so the nominal batch size did not translate into a real reduction in Python round-trips.

### 3. Fixed draw pools drifted from the modular RNG path

The wrapper pre-generated random draws in a fixed layout.

The modular runner consumes randomness conditionally inside module logic. Once the branching pattern diverged, the random streams diverged too, which caused fidelity drift such as crater-count mismatch.

## Measured Result

On the validation benchmark, the wrapper was far slower than the modular path:

- `0.20 mm / 400 seg`: about `17.2k` vs `80.4k` steps/s
- `0.05 mm / 1600 seg`: about `16.8k` vs `73.5k` steps/s

It also failed fidelity against the modular baseline on crater count.

## What Still Matters

The experiment was still useful because it answered the important question:

`A Python wrapper around the current modular microstep path is not the right shape for realtime performance.`

It also clarified the constraints for any future fast path:

- physics should stay owned by the modules
- `EDMState` should remain the public and debug-facing state object
- the hot path cannot pay per-step pack/unpack costs
- batching must be an execution capability, not tied to `servo_interval`
- randomness must be consumed inside the hot loop with the same branch structure as the reference path

## Future Direction

If a faster backend is attempted later, it should be built around:

1. a hot numeric state representation used directly by the fast loop
2. shared module-owned physics kernels
3. action-boundary-aware batching
4. branch-consistent RNG handling inside the hot loop
5. parity checks against the modular reference path

The failed wrapper should be treated as a design experiment, not as a production path.
