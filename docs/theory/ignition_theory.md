# Ignition Module: Stochastic Plasma-Channel Ignition Model

The `IgnitionModule` simulates the stochastic nature of discharge ignition in a Wire Electrical Discharge Machining (WEDM) process. It handles the spark generation process, including spark initiation, duration, extinction, and transitions between different spark states, with a particular focus on realistic short circuit modeling.

## Spark States

The process is modeled as a state machine with three primary states:

1.  **State 0 (Idle)**: Waiting to ignite. The gap is energized (open circuit voltage), but no current flows.
2.  **State 1 (ON period - Spark)**: Active discharge. High current, low voltage.
3.  **State -1 (ON period - Short Circuit)**: Physical contact or debris bridge. High current, zero voltage.
4.  **State -2 (OFF period)**: Rest period. No voltage or current.

## Ignition Probability Model (Normal Sparks)

For normal sparks (not short circuits), the probability of ignition during the idle state is calculated using a gap-dependent hazard rate $\lambda(gap)$.

$$
P(\text{ignite in } \text{dt}) = 1 - \exp(-\lambda(gap) \cdot dt)
$$

The hazard rate $\lambda(gap)$ is derived from empirical data:

$$
\lambda(gap) = \frac{\ln(2)}{0.48 \cdot gap^2 - 3.69 \cdot gap + 14.05}
$$

-   Ignition is highly probable for small gaps and unlikely for gaps $> 25 \mu m$.

## Short Circuit Models

The module implements a sophisticated dual-mechanism model for short circuits, which are critical for simulating process instability.

### 1. Hard Short (Physical Contact)
If the gap is below a threshold (default 2.0 $\mu m$), a short circuit is guaranteed.
$$
\text{If } gap < gap_{hard\_short} \implies \text{Short Circuit}
$$

### 2. Critical Debris Short Circuit
Debris accumulation in the gap can form bridges, causing short circuits even without wire contact. This is modeled using a sigmoid probability function centered around a "critical debris density".

**Critical Density Calculation:**
The density required to cause a short increases with gap size (easier to short a small gap).
$$
\rho_{crit}(gap) = \rho_{crit,base} + c_{gap} \cdot gap
$$

**Probability Calculation:**
The probability of a debris-induced short depends on how far the current debris density $\rho$ is above or below $\rho_{crit}$.
$$
P_{debris}(dt) = 1 - (1 - P_{step})^{dt}
$$
$$
P_{step} = \frac{1}{1 + \exp(-k (\rho - \rho_{crit}))}
$$
-   $k$: Sigmoid steepness (defines the sharpness of the transition).
-   If $\rho \gg \rho_{crit}$, probability approaches 1.
-   If $\rho \ll \rho_{crit}$, probability approaches 0.

### 3. Random Short Circuit
To account for stochastic instabilities not captured by the average debris model, a random short circuit mechanism is included.
-   **Probability**: Increases linearly as gap decreases from $50 \mu m$ down to $2 \mu m$.
-   **Rate**: Defined by `random_short_max_probability`.

## Electrical Parameters & Current Modes

The module loads electrical parameters based on standard machine codes (e.g., "I5", "I12").
-   **Data Source**: Mappings are loaded from `currents.json`.
-   **Current**:
    -   **Idle**: 0 A.
    -   **Spark (State 1)**: Peak current ($I_{peak}$) from look-up table.
    -   **Short (State -1)**: Peak current ($I_{peak}$).
-   **Voltage**:
    -   **Idle**: Target voltage (e.g., 80V).
    -   **Spark**: Working voltage (approx. $0.3 \times V_{target}$).
    -   **Short**: 0 V.

## Duration Control

-   **Normal Spark**: Duration defined by `ON_time`.
-   **Debris Short**: Fixed duration (e.g., 50 $\mu s$) representing the persistence of a debris bridge.
-   **Random Short**: Fixed duration (e.g., 100 $\mu s$).

## Key Parameters

| Parameter | Symbol | Description | Default |
| :--- | :--- | :--- | :--- |
| `base_critical_density` | $\rho_{crit,base}$ | Critical density at gap=0 | 0.3 |
| `gap_coefficient` | $c_{gap}$ | Slope of critical density line | 0.02 |
| `sigmoid_steepness` | $k$ | Sharpness of short probability | 500.0 |
| `debris_short_duration` | - | Duration of debris shorts | 50 $\mu s$ |