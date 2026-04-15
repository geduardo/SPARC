# Realtime Mode Guide

This document describes the implemented SPARC realtime mode: how to launch it,
how the backend and dashboard fit together, which parameters are editable while
the session is running, and which limits are currently intentional.

The older [realtime mode contract](realtime_mode_contract.md) captures the MVP
design intent. This guide reflects the code as it exists now.

## Canonical Launcher

The canonical local entrypoint is:

```bash
python scripts/run_realtime.py --open-browser
```

That command:

- creates one deterministic demo `WireEDMEnv`
- starts one `RealtimeSessionServer` WebSocket session
- starts one static HTTP server for `visualization/dashboard.html`
- prints the dashboard and websocket URLs
- optionally opens the dashboard in the default browser

The previous `scripts/run_realtime_smoke.py` command is still available, but it
is now only a compatibility alias to the canonical launcher.

## CLI Options

Core options:

- `--host`: bind address for both HTTP and WebSocket servers
- `--http-port`: dashboard port, with `0` meaning OS-selected
- `--ws-port`: realtime WebSocket port, with `0` meaning OS-selected
- `--open-browser`: open the dashboard automatically
- `--seed`: deterministic reset seed for the demo session
- `--run-seconds`: auto-stop after a wall-clock duration
- `--max-control-steps`: optional server-side stop condition

Environment configuration options:

- `--config`: load an `EnvironmentConfig` JSON file first
- `--mechanics-control-mode`: `position` or `velocity`
- `--workpiece-height`
- `--wire-diameter`
- `--wire-material`
- `--servo-interval`
- `--initial-gap`
- `--target-cutting-distance`

Direct CLI overrides always win over values loaded from `--config`.
`dt` is intentionally fixed to `1 us` for realtime mode; non-default `dt`
values are rejected even if they appear in a config file.

Pacing can be specified in either of two equivalent forms:

- `--pace-us-per-s`: requested pace in simulated microseconds per wall second
- `--slowdown-factor`: requested wall-seconds per simulated second

Only one of those flags may be provided at a time.

Examples:

```bash
python scripts/run_realtime.py --pace-us-per-s 10000
python scripts/run_realtime.py --slowdown-factor 100
python scripts/run_realtime.py --http-port 0 --ws-port 0 --run-seconds 30
python scripts/run_realtime.py --config my_env.json --wire-material brass
python scripts/run_realtime.py --workpiece-height 15 --initial-gap 20 --target-cutting-distance 800
```

## Runtime Architecture

The implemented live stack is:

1. `WireEDMEnv` running through the compiled-fast scheduler
2. `RealtimeSession` for pacing, lifecycle control, pulse streaming, and
   process-frame snapshots
3. `RealtimeSessionServer` for the single-client WebSocket transport
4. `LiveDashboardDataSource` for bounded browser-side live buffers
5. `DashboardController` plus the existing panels for rendering and UI controls

The live stream uses two data tiers:

- `process_frame`: lower-rate process snapshots for thermal, side, top, and
  summary views
- `pulse_chunk`: pulse-resolution voltage/current/spark-state chunks for the
  oscilloscope

That split is deliberate: the oscilloscope needs pulse-resolution history,
while the process views only need control-boundary state.

## Session Model

The realtime session lifecycle is:

- `created`
- `running`
- `paused`
- `stopped`

The server currently supports one controlling dashboard client at a time. On
wire break or normal stop, the dashboard can issue `restart`, which rebuilds a
fresh session from the original environment snapshot and reconnects into that
new run.

## Supported Live Parameters

The transport-level live-editable parameters are defined in
`src/wedm/realtime/schema.py` and currently are:

- `controller_type`
- `target_gap`
- `target_avg_voltage`
- `fixed_servo`
- `generator_voltage`
- `current_mode`
- `off_time`
- `slowdown_factor`

The current browser UI exposes those parameters as:

- controller strategy selector
- active setpoint field
- generator voltage
- current mode
- `Toff`
- simulation pace
- pause / resume
- restart
- stop

Structural environment configuration is still restart-only. That includes wire
geometry, workpiece geometry, discretization, timing, and seed.

## Pacing Rules

Physics still advances at:

- `dt = 1 us`
- `servo_interval = 1000 us`

The browser-facing pace is a request, not a guarantee of physical realtime. The
current implementation enforces a hard backend ceiling of:

- `80,000 us/s`

Equivalently:

- minimum slowdown factor `12.5`

If a user requests a higher pace, both the backend and the dashboard clamp to
that ceiling. This is intentionally simpler and more stable than the previous
attempt at a continuously moving adaptive cap.

The process-frame stream targets roughly `60 FPS` for rendering. Pulse chunks
carry pulse-resolution samples and can arrive more frequently than the visible
frame cadence.

## Buffering And History

Live mode uses bounded browser buffers instead of full-history arrays.

Current behavior:

- process-frame history targets about `1.1x` wire transit time from inlet to
  outlet
- that history is capped by a `72 MiB` estimated process-frame memory budget
- pulse history uses its own rolling sample buffer
- if the browser falls behind, oldest live history is dropped instead of
  stalling the session

This means live mode is optimized for stable recent visibility, not perfect
infinite history retention.

## Known Performance Limits

Current intentional limits:

- no guarantee of physical `1x` realtime execution
- one controlling dashboard client per live session
- browser smoothness still depends on machine capability and visual load
- high spark density is more expensive to render than spark-free operation
- old live history is discarded once buffer limits are hit

Practical implications:

- very high requested paces may be accepted only up to the hard `80,000 us/s`
  ceiling
- the oscilloscope remains the most pulse-heavy view
- thermal and spark rendering costs still matter at the high end even though
  the transport and pacing path are bounded

## Recommended Workflow

For local live debugging:

```bash
python scripts/run_realtime.py --open-browser
```

For short smoke runs:

```bash
python scripts/run_realtime.py --run-seconds 30 --http-port 0 --ws-port 0
```

For pace experiments:

```bash
python scripts/run_realtime.py --pace-us-per-s 10000
python scripts/run_realtime.py --pace-us-per-s 80000
```
