# Mechanics Module: Servo Axis Control for WEDM

The `MechanicsModule` simulates the servo axis control system used in Wire Electrical Discharge Machining (WEDM) to control wire position or velocity. It provides a configurable implementation that supports both Position and Velocity control modes with realistic servo dynamics, including acceleration and jerk limiting to model mechanical constraints.

## Control System Overview

WEDM machines use servo, force, or velocity control strategies to optimize the gap conditions. This module consolidates these strategies into a single adaptable component.

1.  **Position Control**: Controls wire position relative to a target position. Used for standard movement.
2.  **Velocity Control**: Controls wire velocity to match a target velocity. Often used in adaptive control strategies (e.g., feed rate override based on gap voltage).

## Position Control Mode

Selected by initialization parameter `control_mode="position"`.

### Control Law

The system uses a 2nd-order servo model with Proportional-Derivative (PD) characteristics.

$$
a_{nom} = -2\zeta\omega_n v_{wire} - \omega_n^2(x_{wire} - x_{target})
$$

Where:
-   $a_{nom}$: Nominal acceleration command [µm/s²]
-   $\zeta$: Damping ratio (dimensionless, default 0.38)
-   $\omega_n$: Natural frequency [rad/s] (default 235.0)
-   $v_{wire}$: Current wire velocity [µm/s]
-   $x_{wire}$: Current wire position [µm]
-   $x_{target}$: Target wire position [µm] ($x_{current} + \Delta x_{command}$)

### System Dynamics

This represents a damped harmonic oscillator. The transfer function is:
$$
G(s) = \frac{\omega_n^2}{s^2 + 2\zeta\omega_n s + \omega_n^2}
$$

## Velocity Control Mode

Selected by parameter `control_mode="velocity"`.

### Control Law

The system uses a 1st-order servo model with Proportional (P) control on velocity error.

$$
a_{nom} = -\omega_n(v_{wire} - v_{target})
$$

Where:
-   $v_{target}$: Target wire velocity [µm/s] ($\Delta v_{command}$)

### System Dynamics

This represents a first-order lag system with time constant $\tau = 1/\omega_n$.
$$
G(s) = \frac{\omega_n}{s + \omega_n}
$$

## Physical Constraints and Limiting

The module applies realistic physical constraints after calculating the nominal acceleration.

### 1. Acceleration Limiting
$$
a_{constrained} = \text{clip}(a_{nom}, -a_{max}, a_{max})
$$
-   $a_{max}$: Maximum acceleration (e.g., $3.0 \times 10^5$ µm/s²).

### 2. Jerk Limiting
Prevents instantaneous changes in acceleration to model mechanical inertia and controller smoothing.
$$
\frac{da}{dt} \approx \frac{a_{constrained} - a_{prev}}{\Delta t}
$$
$$
a_{actual} = a_{prev} + \text{clip}(\Delta a, -j_{max} \Delta t, j_{max} \Delta t)
$$
-   $j_{max}$: Maximum jerk (e.g., $1.0 \times 10^8$ µm/s³).

### 3. Velocity Limiting
$$
v_{final} = \text{clip}(v_{integrated}, -v_{max}, v_{max})
$$
-   $v_{max}$: Maximum speed (e.g., $3.0 \times 10^4$ µm/s).

## Implementation Details

-   **Optimization**: Critical control coefficients (damping, stiffness) are pre-computed during initialization.
-   **Scalar Operations**: The update loop uses optimized scalar math and explicit Euler integration for maximum performance.
-   **State Integration**:
    1.  Compute nominal acceleration ($a_{nom}$).
    2.  Apply acceleration caps.
    3.  Apply jerk limits to get $a_{actual}$.
    4.  Update velocity: $v_{new} = v_{old} + a_{actual} \cdot \Delta t$.
    5.  Apply velocity caps.
    6.  Update position: $x_{new} = x_{old} + v_{new} \cdot \Delta t$.

## Key Parameters

| Parameter | Symbol | Description | Default |
| :--- | :--- | :--- | :--- |
| `omega_n` | $\omega_n$ | Natural frequency | 235.0 rad/s |
| `zeta` | $\zeta$ | Damping ratio | 0.38 |
| `max_acceleration` | $a_{max}$ | Max acceleration | $3.0 \times 10^5$ µm/s² |
| `max_jerk` | $j_{max}$ | Max jerk | $1.0 \times 10^8$ µm/s³ |
| `max_speed` | $v_{max}$ | Max speed | $3.0 \times 10^4$ µm/s |
