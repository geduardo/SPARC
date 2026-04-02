# Simulation Runner Guide

Use the runner through the canonical CLI:

```powershell
python SPARC\scripts\run_simulation.py ...
```

This guide is organized by workflow first. The runner is simple once you keep
one distinction in mind:

- some runs are for **timing**
- some runs are for **data**
- some runs try to balance both

Those goals need different flags, and they produce very different runtimes.

## Quick Start

If you just want the right command quickly:

| Goal | Command |
| --- | --- |
| Fastest current timing run | `python SPARC\scripts\run_simulation.py --engine compiled-fast --no-log --steps 1000000` |
| Fair baseline timing run | `python SPARC\scripts\run_simulation.py --engine modular --no-log --steps 1000000` |
| Long compiled run with manageable output | `python SPARC\scripts\run_simulation.py --engine compiled --steps 1000000 --log-strategy zone_mean --output SPARC/visualization/data/compiled_zone_mean.npz` |
| Rich recorded run for post-analysis | `python SPARC\scripts\run_simulation.py --engine compiled --steps 100000 --log-strategy full_field --output SPARC/visualization/data/full_field_run.npz` |

## What The Current Performance Actually Looks Like

On the default workload:

- `workpiece_height = 20.0 mm`
- `segment_len = 200.0 um`
- `controller = gap`
- `mode = position`
- `generator_voltage = 80.0 V`
- `current_mode = 7`
- `on_time = 2.0 us`
- `off_time = 33.0 us`

the current observed timings are roughly:

- `modular --no-log`: about `12.9 s` per simulated second
- `compiled-fast --no-log`: about `8.3 s` per simulated second

So the fastest public CLI mode is currently about:

- `1.5x` to `1.6x` faster than modular on the default workload
- still about `8x` slower than realtime, not near realtime

That is the honest baseline to keep in mind when choosing modes.

## The Mental Model

There are three separate costs in a run:

1. Physics stepping
2. Python/state-sync/controller overhead
3. Logging and file writing

The engine choice mostly changes `1` and part of `2`.
The logging flags mostly change `3`.

That is why:

- `compiled-fast --no-log` is much faster than a recorded run
- `compiled` can still feel slow if you log every step
- `full_field` output can dominate total runtime and file size

## Engine Modes

### `--engine modular`

Use this when you want the reference public stepping path.

Typical use cases:

- baseline timing
- debugging surprising behavior
- checking whether a compiled result is actually worth it
- comparing modular and compiled under the same setup

What it does:

- uses the ordinary modular environment step path
- keeps normal Python orchestration and state handling
- works with or without logging

Good command:

```powershell
python SPARC\scripts\run_simulation.py --engine modular --no-log --steps 1000000
```

### `--engine compiled`

Use this when you want the compiled engine but still want a normal recorded run.

Typical use cases:

- generate NPZ files for analysis
- run the compiled scheduler and still keep regular logger output
- use the faster engine without giving up observability

What it does:

- uses the compiled scheduler internally
- synchronizes state back into Python every microstep
- still produces the normal info/state flow needed by the logger

Tradeoff:

This is a practical data-collection mode, not the lowest-overhead mode. If you
log a lot, the logger and state sync can dominate the runtime.

Good command:

```powershell
python SPARC\scripts\run_simulation.py --engine compiled --steps 1000000 --log-strategy zone_mean --output SPARC/visualization/data/compiled_zone_mean.npz
```

### `--engine compiled-fast`

Use this when you want the fastest current public CLI path.

Typical use cases:

- timing the compiled engine
- comparing modular vs compiled throughput
- long headless runs where you care about speed more than saved data

What it does:

- uses the lower-overhead compiled fast step path
- avoids the logger entirely
- only syncs back to Python when necessary

Restrictions:

- requires `--no-log`
- cannot be used with `--plot`
- does not produce an output file

Tradeoff:

This is the best mode for timing, but it is not a data-generation workflow.

Good command:

```powershell
python SPARC\scripts\run_simulation.py --engine compiled-fast --no-log --steps 1000000
```

## Logging And Output Flags

### `--no-log`

Use this for timing runs.

What it means:

- no NPZ file is written
- no logger finalization cost is paid
- the printed timing is much closer to engine/runtime cost

Best paired with:

- `--engine modular` for a baseline
- `--engine compiled-fast` for a fast timing run

### `--output`

Use this when logging is enabled and you care where the NPZ lands.

Important:

- output paths are resolved relative to the current working directory
- when `--no-log` is used, `--output` is ignored

Example:

If you run:

```powershell
python SPARC\scripts\run_simulation.py --output SPARC/visualization/data/out.npz
```

from the parent directory, the file lands inside the repo as expected.

### `--log-strategy full_field`

Use this when you want the richest saved data.

Typical use cases:

- visualization
- per-segment thermal inspection
- detailed post-analysis

What it records:

- full wire temperature field
- full wire damage field
- material-position arrays and related visualization signals

Tradeoff:

- much larger files
- slower recorded runs
- not a good default for long simulations unless you really need the detail

### `--log-strategy zone_mean`

Use this when you want a practical compromise.

Typical use cases:

- long compiled runs with saved data
- performance-sensitive logging
- temperature trend monitoring without huge files

This is usually the best logging mode for long recorded runs.

### `--log-strategy both`

Use this only when you explicitly need the richer field data and supporting
signals together.

In practice, this is still a heavy logging mode and should not be treated as a
lightweight option.

## Controller Flags

The runner can generate actions internally in three ways.

### `--controller gap`

Use this when you want a simple physical servo target based on the inter-electrode gap.

Relevant flag:

- `--target-gap`

This is the easiest control mode to reason about and the default choice.

### `--controller voltage`

Use this when you want to regulate process behavior using average gap voltage.

Relevant flag:

- `--target-avg-voltage`

This is useful when you care more about electrical behavior than direct gap
closure.

### `--controller fixed-servo`

Use this when you want a constant command.

Relevant flag:

- `--servo`

Typical use cases:

- repeatable comparisons
- debugging
- isolating process behavior from closed-loop controller dynamics

## Mechanics Mode

### `--mode position`

The servo command is interpreted as a position increment.

Use this when you want direct positional adjustment behavior.

### `--mode velocity`

The servo command is interpreted as a target velocity.

Use this when you want a velocity-style servo model instead.

## Geometry And Process Flags

These flags materially change the workload, not just the output label.

### `--segment-len`

Wire segment length in micrometers.

Smaller values mean:

- finer discretization
- more segments
- more wire thermal work
- slower runtime

Larger values mean:

- coarser discretization
- fewer segments
- faster runtime

### `--workpiece-height`

Workpiece thickness in millimeters.

Larger values generally increase the active wire region and can increase runtime.

### `--generator-voltage`

Generator setpoint in volts.

### `--current-mode`

Discrete current mode index.

You can also pass:

```powershell
-I 17 15
```

which means:

- current mode `17`
- on-time `15 us`

### `--on-time`

Pulse ON duration in microseconds.

### `--off-time`

Pulse OFF duration in microseconds.

These settings change the physical process behavior, so do not treat them as
mere runtime knobs.

## Reading The Timing Summary

The runner prints three related numbers.

### `Simulation loop`

This is the time spent in the step loop itself.

Use this when you want to understand the cost of the simulation run, excluding
final output flush.

### `Recorded run`

This is the total end-to-end run time including final logger/file work.

Use this when you care about how long the whole workflow took.

### `Logging/finalization overhead`

This is the difference between the two.

If this number is large, you are mostly paying for output generation rather
than stepping.

## Recommended Workflows

### I want the fastest current number

```powershell
python SPARC\scripts\run_simulation.py --engine compiled-fast --no-log --steps 1000000
```

### I want a fair modular vs compiled comparison

```powershell
python SPARC\scripts\run_simulation.py --engine modular --no-log --steps 1000000
python SPARC\scripts\run_simulation.py --engine compiled-fast --no-log --steps 1000000
```

### I want saved data and acceptable runtime

```powershell
python SPARC\scripts\run_simulation.py --engine compiled --steps 1000000 --log-strategy zone_mean --output SPARC/visualization/data/compiled_zone_mean.npz
```

### I want rich data for visualization

```powershell
python SPARC\scripts\run_simulation.py --engine compiled --steps 100000 --log-strategy full_field --output SPARC/visualization/data/full_field_run.npz
```

### I want a constant-command debugging run

```powershell
python SPARC\scripts\run_simulation.py --engine compiled --controller fixed-servo --servo 0.25 --steps 200000 --log-strategy zone_mean
```

## Practical Advice

If your question is:

- "How fast is the current engine?" use `compiled-fast --no-log`
- "How fast is the reference path?" use `modular --no-log`
- "How do I save useful data without exploding runtime?" use `compiled + zone_mean`
- "Why is my run so slow?" check whether you are using `full_field` logging

If a timing number seems disappointing, first ask whether you are measuring:

- the engine itself
- or the engine plus logging, synchronization, and file writing

Those are different workloads, and the runner exposes different modes for that
reason.
