# Dielectric Module: Debris and Flow Model

The `DielectricModule` simulates the state of the dielectric fluid within the machining gap. Its primary responsibility is tracking debris concentration (contamination) and calculating the effective flow condition, which influences discharge stability and debris flushing.

## Debris Tracking Model

The module tracks the volume of debris (eroded material) accumulated in the machining gap.

### 1. Debris Generation
Debris is added to the gap whenever a successful spark occurs.
$$
V_{debris}(t + \Delta t) = V_{debris}(t) + V_{crater}
$$
-   $V_{crater}$: Volume of the crater formed by the discharge (provided by the Material module).
-   Debris is only added for valid sparks (`spark_status == 1`), not for short circuits or open circuits.

### 2. Gap Volume Calculation
The available volume in the gap (cavity volume) is dynamic, primarily determined by the gap width.
$$
V_{cavity} = (\pi r_{wire} H_{workpiece}) \cdot g
$$
-   $r_{wire}$: Wire radius.
-   $H_{workpiece}$: Workpiece height.
-   $g$: Instantaneous gap width ($x_{workpiece} - x_{wire}$).

### 3. Debris Density
Debris density (contamination level) is the ratio of debris volume to cavity volume.
$$
\rho_{debris} = \min\left(1.0, \frac{V_{debris}}{V_{cavity}}\right)
$$
-   This dimensionless value ranges from 0 (clean dielectric) to 1 (fully clogged).

## Flow Dynamics Model

The module calculates a `flow_condition` factor (0 to 1) representing the efficiency of dielectric flushing through the gap. This factor is influenced by two main physical effects:

### 1. Gap Size Effect (Poiseuille Flow)
Flow rate through a narrow channel is highly sensitive to the gap width.
$$
f_{gap} = \min\left(1.0, \left(\frac{g}{g_{ref}}\right)^3\right)
$$
-   $g_{ref}$: Reference gap width (typically 25 $\mu m$).
-   The cubic relationship mimics Poiseuille flow characteristics for laminar flow between parallel plates.

### 2. Debris Obstruction Effect
High concentration of debris hinders fluid flow.
$$
f_{debris} = \exp(-k_{debris} \cdot \rho_{debris})
$$
-   $k_{debris}$: Debris obstruction coefficient.
-   Higher debris density exponentially reduces the effective flow.

### Combined Flow Condition
The total flow condition is the product of these factors:
$$
\text{flow\_condition} = f_{gap} \cdot f_{debris}
$$

## Debris Removal

Debris is continuously flushed out of the gap based on the flow condition.
$$
\frac{dV_{removed}}{dt} = \beta \cdot Q_{base} \cdot \text{flow\_condition}
$$
$$
V_{debris}(t + \Delta t) = V_{debris}(t) - \frac{dV_{removed}}{dt} \Delta t
$$

-   $\beta$: Debris removal efficiency.
-   $Q_{base}$: Base flow capacity of the flushing system.

## Ionized Channel Tracking

For compatibility with legacy systems or simpler discharge models, the module also tracks the presence and duration of ionized channels.
-   When a spark occurs, an ion channel is registered with a duration (e.g., 6 $\mu s$).
-   The channel persists until the duration expires, representing the time required for deionization.

## Key Parameters

| Parameter | Symbol | Description | Default |
| :--- | :--- | :--- | :--- |
| `base_flow_rate` | $Q_{base}$ | Base flushing capacity | 100 mm³/s |
| `debris_removal_efficiency` | $\beta$ | Efficiency of debris flushing | 0.01 |
| `debris_obstruction_coeff` | $k_{debris}$ | Impact of debris on flow | 1.0 |
| `reference_gap` | $g_{ref}$ | Reference gap for flow calc | 25.0 $\mu m$ |
| `ion_channel_duration` | $t_{ion}$ | Deionization time | 6 $\mu s$ |
