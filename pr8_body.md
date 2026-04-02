## Summary

This PR consolidates the recent simulation-engine work into a cleaner production branch.

It introduces the compiled stepping path, hardens state/logging behavior, unifies the simulation runner workflow, and cleans up repository/runtime surfaces that accumulated during the optimization pass.

## What changed

- Added a compiled scheduler path with `compiled` and `compiled-fast` engine modes.
- Added `HotStateBundle` for fast state marshalling between the environment and compiled stepping path.
- Refactored ignition, dielectric, material, mechanics, and wire modules to support the compiled path while keeping modular behavior aligned.
- Moved wire damage-model parameters into wire material data instead of hardcoding them in the wire module.
- Unified the simulation entrypoint around `scripts/run_simulation.py` and documented runner workflows in `docs/simulation_runner_guide.md`.
- Improved logger validation/export behavior and added clearer runtime performance summaries.
- Cleaned repo/runtime hygiene by removing stale scripts/artifacts and modernizing imports, docs, and test coverage.

## Breaking changes

- `EDMState.voltage` and `EDMState.current` are now mandatory floats rather than optional values.
- `EnvironmentConfig` no longer exposes `max_wire_temperature`, `min_gap_for_operation`, or `max_cutting_force`.
- Wire break-model parameters now live on `WireMaterial` data instead of `WireModuleParameters`.
- The old example runner path was removed; use `python SPARC\\scripts\\run_simulation.py ...`.

## Validation

- `python -m pytest -q` -> `125 passed`

## Notes

- This PR is large because it includes the compiled execution path plus the cleanup needed to leave the repo in a coherent state afterwards.
- The branch is currently mergeable and the local worktree is clean.