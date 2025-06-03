# Mechanics Module: Servo Axis Control for WEDM

The `MechanicsModule` family simulates the servo axis control systems used in Wire Electrical Discharge Machining (WEDM) to control wire position and velocity. These modules implement realistic servo dynamics with acceleration and jerk limiting to model the mechanical constraints of actual EDM machines.

## Control System Overview

WEDM machines use servo control systems to precisely position the wire relative to the workpiece. Two primary control strategies are commonly employed:

1. **Position Control**: Controls wire position relative to a target position
2. **Velocity Control**: Controls wire velocity to match a target velocity

Both control strategies must account for the mechanical limitations of the servo system, including maximum acceleration, jerk (rate of acceleration change), and velocity constraints.

## Position Control System (`MechanicsPositionModule`)

### Control Law

The position control system uses a 2nd-order servo model with proportional-derivative (PD) control characteristics:

\[
a_{nom} = -2\zeta\omega v_{wire} - \omega^2(x_{wire} - \color{blue}{x_{commanded}})
\]
\[
\ddot{x}_{wire} + 2\zeta\omega \dot{x}_{wire} + \omega^2 (x_{wire} - x_{commanded}) = 0
\]


Where:
- \(a_{nom}\): Nominal acceleration command [µm/s²]
- \(\zeta\): Damping ratio (dimensionless)
- \(\omega\): Natural frequency [rad/s]
- \(v\): Current wire velocity [µm/s]
- \(x\): Current wire position [µm]
- \(x_{tgt}\): Target wire position [µm]

### System Dynamics

This control law represents a critically damped 2nd-order system where:

- **Proportional term**: \(-\omega_n^2(x - x_{tgt})\) provides restoring force proportional to position error
- **Derivative term**: \(-2\zeta\omega_n v\) provides damping proportional to velocity

The transfer function of this system in the Laplace domain is:
\[
G(s) = \frac{\omega_n^2}{s^2 + 2\zeta\omega_n s + \omega_n^2}
\]

### Target Interpretation

In position control mode:
\[
x_{tgt} = x_{current} + \Delta x_{target}
\]

Where `state.target_delta` represents the desired position increment \(\Delta x_{target}\) [µm].

## Velocity Control System (`MechanicsVelocityModule`)

### Control Law

The velocity control system uses a 1st-order servo model with proportional control:

\[
a_{nom} = -\omega_n(v_{wire} - \color{blue}{v_{commanded}})
\]

Where:
- \(a_{nom}\): Nominal acceleration command [µm/s²]
- \(\omega_n\): Control bandwidth [rad/s]
- \(v\): Current wire velocity [µm/s]
- \(v_{tgt}\): Target wire velocity [µm/s]

### System Dynamics

This control law represents a 1st-order system where:

- **Proportional term**: \(-\omega_n(v - v_{tgt})\) provides acceleration proportional to velocity error

The transfer function of this system in the Laplace domain is:
\[
G(s) = \frac{\omega_n}{s + \omega_n}
\]

The time constant of the system is:
\[
\tau = \frac{1}{\omega_n}
\]

### Target Interpretation

In velocity control mode:
\[
v_{tgt} = \Delta v_{target}
\]

Where `state.target_delta` directly represents the desired target velocity \(\Delta v_{target}\) [µm/s].

## Physical Constraints and Limiting

Both control systems implement realistic physical constraints to model actual servo system limitations:

### Acceleration Limiting

The nominal acceleration is constrained to realistic values:
\[
a_{constrained} = \text{clip}(a_{nom}, -a_{max}, a_{max})
\]

Where \(a_{max}\) is the maximum acceleration capability [µm/s²].

### Jerk Limiting

To prevent unrealistic instantaneous acceleration changes, jerk limiting is applied:
\[
\frac{da}{dt} = \text{clip}\left(\frac{a_{constrained} - a_{prev}}{\Delta t}, -j_{max}, j_{max}\right)
\]

The actual acceleration becomes:
\[
a_{actual} = a_{prev} + \frac{da}{dt} \cdot \Delta t
\]

Where:
- \(a_{prev}\): Previous acceleration [µm/s²]
- \(j_{max}\): Maximum jerk [µm/s³]
- \(\Delta t\): Time step [s]

### Velocity Limiting

The velocity is constrained to maximum achievable values:
\[
v_{constrained} = \text{clip}(v_{updated}, -v_{max}, v_{max})
\]

Where \(v_{max}\) is the maximum velocity capability [µm/s].

## Integration and State Updates

Both systems use explicit Euler integration to update the state variables:

### Velocity Update
\[
v(t + \Delta t) = v_{wire}(t) + a_{actual} \cdot \Delta t
\]

### Position Update
\[
x(t + \Delta t) = x(t) + v_{constrained} \cdot \Delta t
\]

Where \(\Delta t = dt \times 10^{-6}\) converts the simulation time step from microseconds to seconds.

## Default Parameters

### Common Parameters (Both Systems)
- \(\omega_n = 200\) rad/s (Natural frequency/bandwidth)
- \(a_{max} = 3 \times 10^5\) µm/s² (Maximum acceleration)
- \(j_{max} = 10 \times 10^7\) µm/s³ (Maximum jerk)
- \(v_{max} = 3 \times 10^4\) µm/s (Maximum velocity)

### Position Control Specific
- \(\zeta = 0.55\) (Damping ratio for critically damped response)

## Performance Characteristics

### Position Control
- **Settling Time**: \(t_s \approx \frac{4}{\zeta\omega_n} = \frac{4}{0.55 \times 200} = 36.4\) ms
- **Overshoot**: Minimal due to \(\zeta = 0.55 > 0.5\) (overdamped)
- **Steady-State Error**: Zero for step position commands

### Velocity Control
- **Time Constant**: \(\tau = \frac{1}{\omega_n} = \frac{1}{200} = 5\) ms
- **Settling Time**: \(t_s \approx 4\tau = 20\) ms
- **Steady-State Error**: Zero for step velocity commands

## Implementation Details

### State Variables
- `state.wire_position`: Current wire position [µm]
- `state.wire_velocity`: Current wire velocity [µm/s]
- `state.target_delta`: Target increment (position [µm] or velocity [µm/s])
- `self.prev_accel`: Previous acceleration for jerk limiting [µm/s²]

### Time Conversion
The simulation uses microsecond time steps, requiring conversion:
\[
\Delta t_{seconds} = \frac{dt_{microseconds}}{10^6}
\]

### Numerical Stability
Both systems use explicit integration with small time steps to maintain numerical stability. The jerk limiting provides additional stability by preventing discontinuous acceleration changes.

The mechanics modules work in conjunction with other WEDM simulation modules:

- **Ignition Module**: Provides spark events that may influence target motion
- **Wire Module**: Wire temperature affects material properties
- **Material Module**: Workpiece geometry affects collision constraints
- **Dielectric Module**: Fluid dynamics may influence motion resistance

The servo control system responds to targets set by higher-level path planning algorithms, which consider the current machining conditions and desired cutting strategy.