# Realtime Mode Contract

This document defines the MVP contract for SPARC realtime mode before any
implementation work begins.

For the implemented launcher, runtime architecture, supported live parameters,
and current performance limits, see
[docs/realtime_mode_guide.md](realtime_mode_guide.md).

The goal is not true wall-clock realtime physics. The goal is a stable,
interactive live session where the simulation runs continuously, the dashboard
renders the process as it happens, and selected process parameters can be
changed while the session is running.

## Ground Truth Constraints

- The physical microstep remains `dt = 1 us`.
- The control boundary remains `servo_interval = 1000 us`.
- The compiled engine is the only viable base for live mode; the MVP must build
  on `compiled-fast`.
- The current fastest documented baseline is still slower than physical
  realtime, so the MVP targets paced slow playback, not `1x` wall-clock
  physics.
- The current oscilloscope implementation assumes one global time-indexed
  voltage/current history, so live mode must preserve pulse-resolution data
  separately from low-rate process frames.

## MVP Scope

Realtime mode means:

- a long-lived simulation session instead of a batch run
- a live dashboard connection instead of file-only playback
- bounded in-memory streaming buffers instead of complete history arrays
- runtime updates for selected process and controller parameters
- pause, resume, and speed control for the live session

Realtime mode does not mean:

- guaranteed physical `1x` wall-clock execution
- arbitrary mutation of structural environment configuration mid-session
- multiple independent control clients in the same session
- replacing the existing offline `.npz` dashboard workflow

## Session Model

The MVP session lifecycle is:

- `created`
- `running`
- `paused`
- `stopped`

A session owns:

- one environment instance
- one pacing loop based on `compiled-fast`
- one mutable runtime-control state
- one outgoing live-data stream

The MVP assumes one controlling dashboard client per session. Additional
read-only viewers can be added later if needed.

## Timing And Pacing Contract

- Physics always advances in `1 us` microsteps.
- Live command application happens only on control boundaries, i.e. once per
  `1000 us` of simulated time.
- The server may internally run many microsteps between browser updates, but it
  must publish a process-frame snapshot at each control boundary.
- The user-facing speed control is a slowdown factor relative to simulated
  process time, not a promise of physical `1x` execution.
- The default target slowdown factor for the MVP is `100x` slower than
  simulated process time.
- Recommended supported range is `10x` to `100x` slower than simulated process
  time.
- If the requested speed exceeds what the solver can sustain, the server falls
  back to best-effort solver-limited execution and exposes that status to the
  client.

## Parameter Mutability Contract

### Live-editable at runtime

The following values are supported for live updates during a running session:

- servo command or servo setpoint
- generator target voltage
- current mode
- `ON_time`
- `OFF_time`
- controller setpoint for the selected control strategy:
  - target gap for gap control
  - target average voltage for voltage control
  - fixed servo value for fixed-servo control
- playback slowdown factor
- pause and resume commands

### Session-level, restart-only

The following values are fixed at session creation time for the MVP:

- workpiece height
- wire diameter
- wire material
- segment length / wire discretization
- initial gap
- target cutting distance
- mechanics control mode (`position` vs `velocity`)
- controller strategy selection (`gap`, `voltage`, `fixed-servo`)
- environment timing (`dt`, `servo_interval`)
- random seed

These values remain restart-only because the current environment and compiled
scheduler treat them as structural configuration, not command inputs.

## Stream Contract

The MVP uses a single WebSocket connection.

### Message classes

Client to server:

- `set_param`
- `set_speed`
- `pause`
- `resume`
- `stop`

Server to client:

- `session_header`
- `process_frame`
- `pulse_chunk`
- `session_state`
- `error`

Control and session messages use JSON.

For data messages:

- JSON is acceptable for the first implementation if profiling shows it is fast
  enough.
- Binary encoding is allowed only for heavy data payloads and must keep the
  same logical message types.
- The schema must be versioned from the start.

## Two-Tier Data Model

### `process_frame`

`process_frame` is emitted once per control boundary and drives the non-scope
views.

Required fields:

- `time_us`
- `wire_position_um`
- `wire_velocity_um_s`
- `workpiece_position_um`
- `target_delta`
- `target_voltage`
- `current_mode`
- `on_time_us`
- `off_time_us`
- `voltage`
- `current`
- `spark_status`
- `is_short_circuit`
- `debris_density`
- `flow_rate`
- `wire_temperature`
- `wire_damage`
- `wire_material_positions_mm`
- `wire_head_idx`
- `wire_offset_mm`

This message is the live equivalent of the dashboard-oriented process-state data
already exported for offline playback, except that it is bounded in memory and
published incrementally.

### `pulse_chunk`

`pulse_chunk` is emitted at pulse resolution for the oscilloscope.

Default chunk shape:

- one control interval per chunk
- `1000` samples per chunk
- `dt_us = 1`

Required fields:

- `base_time_us`
- `voltage`
- `current`
- `spark_state`

The oscilloscope consumes `pulse_chunk` data from its own rolling history and
must not assume the global dashboard frame index maps directly to microseconds.

## Session Header Contract

`session_header` contains metadata needed to initialize live views without
re-sending static configuration on every frame.

Required metadata:

- schema version
- workpiece height
- wire diameter
- buffer lengths and contact offsets needed by the thermal/profile views
- segment length
- control mode
- controller strategy
- supported live-editable parameters
- current solver timing (`dt`, `servo_interval`)

## Responsibility Split

### Server responsibilities

- own the environment and pacing loop
- apply queued commands at the next control boundary
- publish `process_frame` and `pulse_chunk` data
- report session state and solver-limited conditions
- reject unsupported runtime changes cleanly

### Browser responsibilities

- maintain bounded live buffers
- preserve the existing offline file-based mode
- render process panels from `process_frame`
- render the oscilloscope from `pulse_chunk`
- debounce user edits before sending `set_param`
- surface connection state and applied values

## Dashboard Buffering Contract

- The dashboard must support both file-backed history and live streaming through
  a common data-source abstraction.
- Live mode uses append-only ring buffers rather than unbounded arrays.
- Process panels consume the latest bounded history only.
- The oscilloscope maintains its own rolling pulse-history buffer.
- If the client falls behind, the MVP drops oldest live data rather than
  stalling the session.

## Explicit Non-Goals For The MVP

- multi-machine or distributed execution
- deterministic replay of a live interactive session
- live editing of structural geometry or discretization
- full parity between offline complete-history tooling and bounded live-history
  tooling on day one

## Acceptance Criteria For AR-01

This contract is complete when:

- backend tasks can implement against a fixed live-editable parameter set
- dashboard tasks can implement against a fixed two-tier stream model
- validation tasks have a concrete definition of expected session behavior
- later tasks do not need to reopen the basic questions of:
  - what can change live
  - what the server must emit
  - what the browser must buffer
  - what realtime means for this codebase
