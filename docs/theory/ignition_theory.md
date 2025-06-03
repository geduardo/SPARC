# Ignition Module: Stochastic Plasma-Channel Ignition Model

The `IgnitionModule` simulates the stochastic nature of discharge ignition in a Wire Electrical Discharge Machining (WEDM) process. It handles the spark generation process, including spark initiation, duration, and extinction, as well as the transitions between different spark states.

## Spark States

The ignition process is modeled as a state machine with three primary states:

1. **State 0 (Idle)**: Waiting to ignite. The gap is energized with an open circuit voltage, but no spark has occurred yet.
2. **State 1 (ON period)**: Active spark or short circuit. Current is flowing through the gap.
3. **State -2 (OFF period)**: Rest period after a spark. No voltage or current in the gap.

The state is stored in `state.spark_status` as a list of three values:
- `spark_status[0]`: Spark state (0, 1, or -2)
- `spark_status[1]`: Spark location along the workpiece height (or None when not sparking)
- `spark_status[2]`: Duration counter (time steps since the spark began)

## State Transitions

The state transitions follow this sequence:

1. **Idle → ON**: When a spark successfully ignites or a short circuit occurs
2. **ON → OFF**: After the ON time duration is reached
3. **OFF → Idle**: After the OFF time duration is reached

Mathematically, these transitions can be represented as:

For Idle to ON transition (stochastic ignition):
\[
P(\text{Idle} \rightarrow \text{ON}) = P_{ignite} = \lambda(gap)
\]

For ON to OFF transition (deterministic):
\[
\text{If } t_{spark} \geq t_{ON} \text{ then } \text{ON} \rightarrow \text{OFF}
\]

For OFF to Idle transition (deterministic):
\[
\text{If } t_{total} \geq (t_{ON} + t_{OFF}) \text{ then } \text{OFF} \rightarrow \text{Idle}
\]

Where:
- \(P_{ignite}\): Probability of ignition
- \(\lambda(gap)\): Gap-dependent ignition probability function
- \(t_{spark}\): Duration of the current spark
- \(t_{total}\): Total duration since spark initiation (ON + OFF time elapsed)
- \(t_{ON}\): ON time setting
- \(t_{OFF}\): OFF time setting

## Ignition Probability Model

The probability of a spark ignition during the idle state is calculated using a gap-dependent function \(\lambda(gap)\). This function represents the ignition probability per time step and is derived from empirical data.

\[
\lambda(gap) = \frac{\ln(2)}{0.48 \cdot gap^2 - 3.69 \cdot gap + 14.05}
\]

Where:
- \(gap\): Distance between the wire and workpiece (mm)
- \(\ln(2)\): Natural logarithm of 2, used to normalize the probability

For computational efficiency, the module caches the calculated \(\lambda\) values for different gap sizes.

## Short Circuit Handling

A short circuit occurs when the wire touches the workpiece (\(gap \leq 0\)). The module handles short circuits with special logic:

1. If the system is in the idle state (0) and a short circuit occurs, it immediately transitions to the ON state (1) with full current and zero voltage.
2. During short circuit conditions, the ignition probability calculation is skipped (returns 0) to prevent mathematical errors due to non-positive gap values.

## Electrical Parameters

During different states, the electrical parameters are set as follows:

### Idle State (0):
- Current: \(I = 0\)
- Voltage: \(V = V_{target}\) (if not shorted), \(V = 0\) (if shorted)

### ON State (1):
- Current: \(I = I_{peak}\)
- Voltage: \(V = 0.3 \cdot V_{target}\) (if not shorted), \(V = 0\) (if shorted)

### OFF State (-2):
- Current: \(I = 0\)
- Voltage: \(V = 0\)

Where:
- \(I_{peak}\): Peak current setting (default: 300A)
- \(V_{target}\): Target voltage setting (default: 80V)

## Stochastic Ignition Process

For each time step in the idle state, the module:

1. Calculates the ignition probability \(P_{ignite}\) based on the current gap
2. Generates a random number \(r \in [0,1]\)
3. If \(r < P_{ignite}\), a spark is initiated:
   - A random spark location along the workpiece height is chosen
   - The system transitions to the ON state
   - The electrical parameters are updated accordingly

Mathematically:
\[
\text{If } r < \lambda(gap) \text{ then initiate spark at random location}
\]

## Implementation Details

- The module caches \(\lambda\) values for efficiency using a dictionary `lambda_cache`
- The primary `update` method handles the state machine transitions and updates the electrical parameters
- The `_cond_prob` method calculates the conditional probability of ignition based on the current gap
- The `get_lambda` method computes the gap-dependent ignition probability function

## Key Variables in Code

- `state.spark_status`: List containing [spark_state, spark_location, duration]
- `state.target_voltage`: Target voltage setting (default: 80V)
- `state.peak_current`: Peak current setting (default: 300A)
- `state.ON_time`: Duration of ON period in time steps (default: 3)
- `state.OFF_time`: Duration of OFF period in time steps (default: 80)
- `state.wire_position`: Position of the wire
- `state.workpiece_position`: Position of the workpiece
- `gap`: Distance between wire and workpiece (workpiece_position - wire_position)
- `state.current`: Current flowing through the gap
- `state.voltage`: Voltage across the gap

The ignition module works in close cooperation with other modules like the wire module, which simulates the wire temperature, and the material removal module, which updates the workpiece position based on the machining process. 