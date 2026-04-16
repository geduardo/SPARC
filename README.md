<p align="center">
  <img src="./visualization/img/sparc_logo.png" alt="SPARC Logo" width="400">
</p>

# SPARC - Wire EDM Learning Environment

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

SPARC (Simulation Platform for Advanced Rough-Cut Control) is a Python package that implements a simplified stochastic simulation of a 1D Wire Electrical Discharge Machining (Wire EDM) process, designed for reinforcement learning research.

This environment is compatible with the [Gymnasium](https://gymnasium.farama.org/) library (formerly OpenAI Gym), facilitating the efficient testing of reinforcement learning algorithms and various control strategies specific to the Wire EDM process.

## Features

- **Gymnasium-compatible environment** for Wire EDM simulation
- **Modular architecture** with separate physics modules (ignition, wire heating, material removal, etc.)
- **Configurable parameters** for different wire materials and cutting conditions
- **Real-time visualization** support
- **Comprehensive logging** capabilities for analysis

## Installation

### From Source
```bash
# Clone the repository
git clone https://github.com/geduardo/SPARC.git
cd SPARC

# Install in development mode
pip install -e .

# Or install with visualization support
pip install -e ".[visualization]"
```

## Quick Start

```python
import numpy as np
from wedm import WireEDMEnv, EnvironmentConfig

# Create environment with default configuration
env = WireEDMEnv()

# Or customize the configuration
config = EnvironmentConfig(
    workpiece_height=15.0,  # mm
    wire_diameter=0.25,     # mm
    wire_material="brass",
    target_cutting_distance=800.0,  # µm
)
env = WireEDMEnv(config=config)

# Reset environment
obs, info = env.reset()

# Run simulation with random actions
for _ in range(1000):
    # Sample random action
    action = env.action_space.sample()
    
    # Step environment
    obs, reward, terminated, truncated, info = env.step(action)
    
    if terminated:
        break

print(f"Simulation completed. Wire broken: {info.get('wire_broken', False)}")
```

## Advanced Usage

### Custom Control Strategy

```python
import numpy as np
from wedm import WireEDMEnv

# Create environment
env = WireEDMEnv(mechanics_control_mode="position")
obs, info = env.reset()

# Define a simple control strategy
def simple_controller(state):
    """Simple proportional controller."""
    gap = state.workpiece_position - state.wire_position
    target_gap = 25.0  # µm
    
    # Proportional control
    error = target_gap - gap
    servo_command = np.clip(0.1 * error, -1.0, 1.0)
    
    return {
        "servo": np.array([servo_command]),
        "generator_control": {
            "target_voltage": np.array([80.0]),
            "current_mode": np.array([5]),  # I5
            "ON_time": np.array([3.0]),
            "OFF_time": np.array([80.0]),
        }
    }

# Run simulation with custom controller
done = False
while not done:
    action = simple_controller(env.state)
    obs, reward, terminated, truncated, info = env.step(action)
    done = terminated or truncated
```

### Logging and Analysis

```python
from wedm import WireEDMEnv
from wedm.utils.logger import SimulationLogger

# Configure logger
logger_config = {
    "signals_to_log": ["wire_position", "workpiece_position", "voltage", "current"],
    "log_frequency": {"type": "every_step"},
    "backend": {"type": "json", "filepath": "simulation_data.json"}
}

# Create environment and logger
env = WireEDMEnv()
logger = SimulationLogger(logger_config, env)

# Run simulation
obs, info = env.reset()
for _ in range(10000):
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    logger.collect(env.state, info)  # Collect data each step

    if terminated:
        break

# Finalize and save logged data
logger.finalize()
```

## Visualization Dashboard

SPARC includes a web-based visualization dashboard for analyzing simulation results.

### Generate Data and Launch Dashboard

```bash
# 1. Run simulation to generate NPZ data
python examples/quickstart.py

# 2. Convert to JSON for dashboard
python scripts/npz_to_json.py quickstart_*.npz -o visualization/data/simulation_data.json

# 3. Open the dashboard
cd visualization
python -m http.server 8000
# Then open http://localhost:8000/dashboard.html
```

### Dashboard Features

- **Side View**: Wire, workpiece, and spark visualization
- **Virtual Oscilloscope**: Real-time voltage/current traces
- **Top View**: Debris concentration heatmap
- **Thermal Profile**: Wire temperature distribution
- **Timeline Controls**: Play, pause, and scrub through simulation

See [visualization/README.md](visualization/README.md) for detailed documentation.

## Realtime Mode

SPARC also includes a local realtime mode that runs one live simulation session,
serves the dashboard, and connects the browser over WebSocket.

### Launch Realtime Mode

```bash
python scripts/run_realtime.py --open-browser
```

Useful pace options:

```bash
# Request pace directly in simulated microseconds per wall second
python scripts/run_realtime.py --pace-us-per-s 10000

# Equivalent request in slowdown-factor form
python scripts/run_realtime.py --slowdown-factor 100

# Let the OS choose free ports and stop automatically after 30 seconds
python scripts/run_realtime.py --http-port 0 --ws-port 0 --run-seconds 30
```

You can also configure the environment directly from the CLI:

```bash
python scripts/run_realtime.py \
  --workpiece-height 15.0 \
  --wire-diameter 0.25 \
  --wire-material brass \
  --initial-gap 20 \
  --target-cutting-distance 800 \
  --mechanics-control-mode position
```

`dt` is intentionally fixed to `1 us` in realtime mode and is not exposed as a
launcher override.

Or load a JSON `EnvironmentConfig` and override selected fields:

```bash
python scripts/run_realtime.py --config my_env.json --wire-diameter 0.3
```

The canonical launcher is `scripts/run_realtime.py`. The older
`scripts/run_realtime_smoke.py` path is kept as a compatibility alias.

Implemented architecture, supported live parameters, pacing rules, and known
performance limits are documented in
[docs/realtime_mode_guide.md](docs/realtime_mode_guide.md). The original
design-stage contract remains in
[docs/realtime_mode_contract.md](docs/realtime_mode_contract.md).

## Documentation

For detailed documentation, please visit our [documentation page](https://github.com/geduardo/SPARC/wiki).

Runner usage, engine modes, logging modes, and recommended CLI workflows are
documented in [docs/simulation_runner_guide.md](docs/simulation_runner_guide.md).

## Examples

Check out the `examples/` directory for a quickstart example demonstrating basic environment usage.

## Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details.

## Citation

If you use this environment in your research, please cite:

```bibtex
@software{wedm_learning_environment,
  author = {Gonzalez Sanchez, Eduardo},
  title = {Wire EDM Learning Environment},
  year = {2025},
  url = {https://github.com/geduardo/SPARC}
}
```

## License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE.md) file for details.

## Acknowledgments

This work was developed as part of research on applying reinforcement learning during the PhD Thesis of Eduardo Gonzalez Sanchez at ETH Zurich.
