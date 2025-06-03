# Mechanics Control Modes

The WEDM-Learning-Environment supports multiple mechanics control modes through a single configurable `MechanicsModule` class. You can choose between position control and velocity control for the wire servo system.

## Available Control Modes

The `MechanicsModule` class supports two control modes via the `control_mode` parameter:

### 1. Position Control (`control_mode="position"`)
- **Control Law**: 2nd-order servo system with damping
- **Target Interpretation**: `target_delta` represents a position increment [µm]
- **Use Case**: When you want to control the wire position directly

**Mathematical Model:**
```
a_nom = -2 * ζ * ωₙ * v - ωₙ² * (x - x_target)
```
where:
- `ζ = 0.55` (damping ratio)
- `ωₙ = 200 rad/s` (natural frequency)
- `x` is current position, `v` is current velocity
- `x_target = x + target_delta`

### 2. Velocity Control (`control_mode="velocity"`)
- **Control Law**: 1st-order velocity tracking
- **Target Interpretation**: `target_delta` represents target velocity [µm/s]
- **Use Case**: When you want to control the wire velocity directly

**Mathematical Model:**
```
a_nom = -ωₙ * (v - v_target)
```
where:
- `ωₙ = 200 rad/s` (bandwidth of velocity control loop)
- `v` is current velocity
- `v_target = target_delta`

## Usage

### Creating Environment with Specific Control Mode

```python
from src.wedm.envs import WireEDMEnv

# Position control (default)
env_pos = WireEDMEnv(mechanics_control_mode="position")

# Velocity control
env_vel = WireEDMEnv(mechanics_control_mode="velocity")
```

### Direct Module Usage

You can also create the mechanics module directly:

```python
from src.wedm.modules import MechanicsModule

# Create mechanics module with position control
mechanics_pos = MechanicsModule(env, control_mode="position")

# Create mechanics module with velocity control  
mechanics_vel = MechanicsModule(env, control_mode="velocity")
```

### Action Space Interpretation

The `servo` action in the action space has different meanings depending on the control mode:

```python
action = {
    "servo": np.array([value], dtype=np.float32),
    "generator_control": { ... }
}
```

- **Position Control**: `value` represents position increment [µm]
- **Velocity Control**: `value` represents target velocity [µm/s]

### Example Controllers

#### Position Controller
```python
def position_controller(env: WireEDMEnv, desired_gap: float = 17.0):
    gap = env.state.workpiece_position - env.state.wire_position
    error = desired_gap - gap
    position_increment = error * 0.1  # Proportional control
    return {
        "servo": np.array([position_increment], dtype=np.float32),
        # ... generator_control ...
    }
```

#### Velocity Controller
```python
def velocity_controller(env: WireEDMEnv, desired_gap: float = 17.0):
    gap = env.state.workpiece_position - env.state.wire_position
    error = desired_gap - gap
    target_velocity = error * 50.0  # Convert error to velocity
    target_velocity = np.clip(target_velocity, -1000.0, 1000.0)
    return {
        "servo": np.array([target_velocity], dtype=np.float32),
        # ... generator_control ...
    }
```

## Running the Comparison

To see the difference between control modes, run the comparison experiment:

```bash
python experiments/compare_mechanics_control.py --steps 50000 --plot
```

This will:
1. Run simulations with both position and velocity control
2. Compare their performance
3. Show plots comparing wire position, velocity, and gap control

## Technical Details

### Module Parameters

```python
class MechanicsModule(EDMModule):
    def __init__(self, env, control_mode: str = "position"):
        # Control mode: "position" or "velocity"
        self.control_mode = control_mode
        
        # Control parameters
        self.omega_n = 200      # rad/s (bandwidth)
        self.zeta = 0.55        # damping ratio (position control only)
        self.max_accel = 3e5    # µm/s² (acceleration limit)
        self.max_jerk = 1e8     # µm/s³ (jerk limit)
        self.max_speed = 3e4    # µm/s (speed limit)
```

### Saturation Limits (Same for Both Modes)
- **Max Acceleration**: 3×10⁵ µm/s²
- **Max Jerk**: 10×10⁷ µm/s³  
- **Max Speed**: 3×10⁴ µm/s

### Jerk Limiting
Both control modes implement jerk limiting to prevent unrealistic acceleration changes:
```python
da = a_nom - prev_accel
da = np.clip(da, -max_jerk * dt, max_jerk * dt)
a = prev_accel + da
```

### Checking Current Control Mode

You can check which control mode is active:

```python
# From environment
print(f"Control mode: {env.mechanics.control_mode}")

# From mechanics module directly
if mechanics.control_mode == "position":
    print("Using position control")
elif mechanics.control_mode == "velocity":
    print("Using velocity control")
```

### When to Use Each Mode

**Position Control** is better when:
- You need precise positioning
- The system has good position feedback
- You want inherent stability through damping

**Velocity Control** is better when:
- You need responsive velocity tracking
- The control system operates on velocity commands
- You want simpler control laws

Many real EDM machines use velocity control because:
1. It's more responsive to rapid changes
2. Simpler to implement and tune
3. More natural for feed-rate control
4. Better for adaptive control strategies 