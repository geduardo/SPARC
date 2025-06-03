![Wire EDM Simulation](https://github.com/geduardo/WEDM-minimal-simulation/assets/48300381/042f8ab7-87b2-430e-9d5a-143c95bf69e3)

# SPARC - Wire EDM Learning Environment

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

SPARC (Simulation Platform for Advanced Rough-Cut Control) is a Python package that implements a simplified stochastic simulation of a 1D Wire Electrical Discharge Machining (Wire EDM) process, designed for reinforcement learning research.

This environment is compatible with the [Gymnasium](https://gymnasium.farama.org/) library (formerly OpenAI Gym), facilitating the efficient testing of reinforcement learning algorithms and various control strategies specific to the Wire EDM process.

## Features

- **Gymnasium-compatible environment** for Wire EDM simulation
- **Modular architecture** with separate physics modules (ignition, wire heating, material removal, etc.)
- **Configurable parameters** for different wire materials and cutting conditions
- **Real-time visualization** using pygame (coming soon)
- **Comprehensive logging** capabilities for analysis

## Installation

### From PyPI (coming soon)
```bash
pip install wedm-learning-environment
```

### From Source
```bash
# Clone the repository
git clone https://github.com/geduardo/SPARC.git
cd WEDM-Learning-Environment

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
from wedm import WireEDMEnv, EnvironmentConfig

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
from wedm.utils.logger import SimulationLogger, LoggerConfig

# Configure logger
logger_config = LoggerConfig(
    signals_to_log=["wire_position", "workpiece_position", "spark_status"],
    log_frequency={"type": "interval", "interval": 100},  # Log every 100 µs
    backend={"type": "numpy", "filepath": "simulation_data.npz"}
)

# Create environment with logger
env = WireEDMEnv()
logger = SimulationLogger(logger_config, env)

# Run simulation
obs, info = env.reset()
for _ in range(10000):
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    logger.log()  # Log current state
    
    if terminated:
        break

# Save logged data
logger.save()
```

## Documentation

For detailed documentation, please visit our [documentation page](https://github.com/geduardo/SPARC/wiki) (coming soon).

## Examples

Check out the `examples/` directory for more comprehensive examples:
- `organized_parameter_example.py` - Demonstrates the parameter organization system
- `temperature_logging_strategies.py` - Shows different logging strategies

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

This work was developed as part of research on applying reinforcement learning to manufacturing processes.
