# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Support for different temperature logging strategies (full_field, zone_mean, both)
- Performance optimizations for wire temperature calculations
- Comprehensive repository audit script
- Contributing guidelines

### Changed
- Improved simulation performance with optimized Numba implementations
- Enhanced documentation and examples
- **BREAKING:** `EDMState.voltage` and `EDMState.current` are now `float` (default `0.0`) instead of `Optional[float]`. Downstream code must no longer treat these fields as optional or use `None`-checks to detect an "unset" state.
- **BREAKING:** `EnvironmentConfig` no longer has `max_wire_temperature`, `min_gap_for_operation`, or `max_cutting_force` fields. Wire failure is now determined by the accumulated damage model in `WireMaterial`, not a temperature threshold.
- `HotStateBundle.apply_to_env()` now copies array data into the target env's buffers via `np.copyto` instead of rebinding references, preventing shared-buffer aliasing across env instances.
- `_advance_discharge_state()` now enforces `voltage=0` for short circuits internally, removing a fragile caller precondition.

### Fixed
- Various bug fixes and performance improvements

## [0.2.0] - 2025-06-10

### Added
- Gymnasium-compatible environment for Wire EDM simulation
- Modular architecture with separate physics modules
- Real-time visualization using pygame
- Comprehensive logging capabilities
- Multiple control modes (position and velocity)
- Support for different wire materials
- Example scripts demonstrating various use cases

### Changed
- Refactored codebase for better modularity
- Improved numerical stability of simulations
- Enhanced parameter organization system

## [0.1.0] - 2025-06-03

### Added
- Initial implementation of Wire EDM simulation
- Basic physics models for spark ignition and material removal
- Simple control interface
