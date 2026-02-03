# Wire module – Breakage mechanism

The wire breakage is modeled as a cumulative thermomechanical damage process based on the **CIRP-HPC 2026** paper.

**Damage Rate Model**
The damage rate $\dot{D}$ depends on the wire stress $\sigma$ and temperature $T$:

$$
\dot{D} = k \cdot \sigma^n \cdot \exp\left(-\frac{Q}{R \cdot T}\right)
$$

Where:
*   $k$: Damage rate constant
*   $\sigma$: Wire tension stress [MPa]
*   $n$: Stress exponent
*   $Q$: Activation energy
*   $R$: Gas constant
*   $T$: Segment temperature [K] (only if $T > 150^\circ\text{C}$)

**Damage Accumulation (Euler Step)**
For each segment $i$, damage accumulates over time step $\Delta t$:

$$
D_i(t + \Delta t) = D_i(t) + \dot{D}(T_i) \cdot \Delta t
$$

**Failure Condition**
The wire breaks if **any** segment reaches the critical damage threshold:

$$
\max(D_i) \ge 1.0 \implies \text{Wire Break}
$$
