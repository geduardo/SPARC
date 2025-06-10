# Wire Module: 1-D Transient Heat Model

The `WireModule` simulates the temperature distribution along the travelling wire in a Wire Electrical Discharge Machining (WEDM) process. It employs a 1-D transient heat model, discretizing the wire into a series of segments and calculating the temperature change in each segment based on several heat transfer mechanisms.

## Discretization

The wire, with a total length $L_{total}$, is divided into $N$ segments, each of length $\delta h$.

$$
L_{total} = L_{buffer,bottom} + h_{workpiece} + L_{buffer,top}
$$
$$
N = \text{max}(1, \text{int}(L_{total} / \delta h))
$$

Where:
- $L_{buffer,bottom}$: Length of the wire buffer below the workpiece.
- $H_{workpiece}$: Height of the workpiece.
- $L_{buffer,top}$: Length of the wire buffer above the workpiece.
- $\delta h$: Length of each wire segment.

The lengths $L_{buffer,bottom}$ and $L_{buffer,top}$ define buffer zones at either end of the workpiece. While the primary interest is the temperature distribution within the workpiece section ($H_{workpiece}$), these buffer regions are essential for the accuracy of the simulation. They extend the modeled wire length beyond the workpiece itself, allowing for a more realistic calculation of heat transfer mechanisms such as conduction from adjacent segments and advection (due to wire travel). These mechanisms significantly influence the temperature profile within $H_{workpiece}$, and the buffers help to ensure that the thermal conditions at the entry and exit points of the workpiece are properly represented, avoiding inaccuracies that could arise from artificial boundary effects.

The temperature of each segment $i$ at time $t$ is denoted as $T_i(t)$.

## Heat Transfer Mechanisms

The change in temperature $\frac{dT_i}{dt}$ for each segment $i$ is determined by the net effect of the following heat transfer mechanisms:

$$
\rho c_p V_i \frac{dT_i}{dt} = \dot{Q}_{cond,i} + \dot{Q}_{joule,i} + \dot{Q}_{plasma,i} - \dot{Q}_{conv,i} + \dot{Q}_{adv,i}
$$

Where:
- $\rho$: Density of the wire material (kg/m³)
- $c_p$: Specific heat capacity of the wire material (J/kg·K)
- $V_i$: Volume of segment $i$ ($S \cdot \delta h$) (m³)
- $S$: Cross-sectional area of the wire ($\pi r_{wire}^2$) (m²)
- $r_{wire}$: Radius of the wire (m)
- $\delta h$: Length of the segment (m)

The terms on the right-hand side are:

### 1. Conduction ($\dot{Q}_{cond,i}$)

Heat transfer due to conduction between segment $i$ and its adjacent segments $i-1$ (upstream) and $i+1$ (downstream). The net heat conducted into segment $i$ is the sum of two components:

1.  **Heat flow from the upstream segment ($i-1$) to segment $i$:**
    This is driven by the temperature difference between segment $i-1$ and segment $i$.
    $$
    \dot{Q}_{cond, i \leftarrow i-1} = k S \frac{T_{i-1} - T_i}{\delta h}
    $$

2.  **Heat flow from the downstream segment ($i+1$) to segment $i$:**
    This is driven by the temperature difference between segment $i+1$ and segment $i$.
    $$
    \dot{Q}_{cond, i \leftarrow i+1} = k S \frac{T_{i+1} - T_i}{\delta h}
    $$

The total net conduction heat rate for segment $i$, $\dot{Q}_{cond,i}$, is the sum of these two flows:
$$
\dot{Q}_{cond,i} = \dot{Q}_{cond, i \leftarrow i-1} + \dot{Q}_{cond, i \leftarrow i+1} = k S \frac{(T_{i-1} - T_i) + (T_{i+1} - T_i)}{\delta h}
$$
This simplifies to the standard finite difference form for conduction, which is equivalent to using a central difference scheme for the second derivative of temperature with respect to position $y$:
$$
\dot{Q}_{cond,i} = k S \frac{T_{i-1} - 2T_i + T_{i+1}}{\delta h}
$$

Where:
- $k$: Thermal conductivity of the wire material (W/m·K)
- $S$: Cross-sectional area of the wire (m²)
- $\delta h$: Length of the segment (m)
- $T_{i-1}$, $T_i$, $T_{i+1}$: Temperatures of the upstream, current, and downstream segments, respectively.

The module uses a coefficient `k_cond_coeff` = $k S / \delta h$. Using this coefficient, the individual flows and the total net conduction can be expressed as:
$$
\dot{Q}_{cond, i \leftarrow i-1} = \text{k\_cond\_coeff} \cdot (T_{i-1} - T_i)
$$
$$
\dot{Q}_{cond, i \leftarrow i+1} = \text{k\_cond\_coeff} \cdot (T_{i+1} - T_i)
$$
And the total net conduction:
$$
\dot{Q}_{cond,i} = \text{k\_cond\_coeff} \cdot (T_{i-1} - 2T_i + T_{i+1})
$$

**Boundary Conditions for Conduction:**
-   At the wire entry (top, $i=0$): Dirichlet boundary condition, $T_0 = T_{spool}$.
-   At the wire exit (bottom, $i=N-1$): Neumann boundary condition, $\frac{dT}{dy} = 0$. This is approximated as:
    $$
    \dot{Q}_{cond,N-1} = k S \frac{T_{N-2} - T_{N-1}}{\delta h}
    $$

### 2. Joule Heating ($\dot{Q}_{joule,i}$)

Heat generated within the segment due to the electrical current passing through it.

$$
\dot{Q}_{joule,i} = I^2 R_i = I^2 \rho_{elec}(T_i) \frac{\delta h}{S}
$$

Where:
- $I$: Electrical current (A)
- $R_i$: Electrical resistance of segment $i$ ($\Omega$)
- $\rho_{elec}(T_i)$: Electrical resistivity of the wire material at temperature $T_i$ ($\Omega \cdot m$). This is temperature-dependent:
  $$
  \rho_{elec}(T_i) = \rho_{elec,ref} (1 + \alpha_{\rho} (T_i - T_{ref}))
  $$
  - $\rho_{elec,ref}$: Electrical resistivity at a reference temperature $T_{ref}$ (e.g., 293.15 K).
  - $\alpha_{\rho}$: Temperature coefficient of resistivity (K⁻¹).

The implementation uses `0.5 * (I**2)` likely due to how power is distributed or a specific model assumption (e.g. average power over a cycle if current is AC, or a factor related to the simulation time step or energy deposition efficiency). The code uses: `0.5 * (I**2) * rho_T * (delta_y / S)`, where `rho_T` is $\rho_{elec}(T_i)$.

### 3. Plasma Spot Heating ($\dot{Q}_{plasma,i}$)

Heat input from the plasma discharge (spark) occurring at a specific location on the wire within the machining zone. This heating is applied only to the segment where the spark occurs.

$$
\dot{Q}_{plasma,i} = \eta_{plasma} V_{spark} I \delta_i
$$

Where:
- $idx$: Index of the segment where the spark occurs.
- $\eta_{plasma}$: Efficiency of plasma heating (fraction of total spark energy transferred to the wire).
- $V_{spark}$: Spark voltage (V).

This term is non-zero only for the segment `idx` corresponding to the spark location `y_spark`.

### 4. Convection ($\dot{Q}_{conv,i}$)

Heat loss from the wire segment to the surrounding dielectric fluid.

$$
\dot{Q}_{conv,i} = h_{eff} A_i (T_i - T_{dielectric})
$$

Where:
- $h_{eff}$: Effective heat transfer coefficient (W/m²·K). This can be dependent on the wire unwinding velocity $v_{wire}$:
  $$
  h_{eff} = h_{conv} (1 + c_v \cdot v_{wire} + c_f \cdot f)
  $$
  (The code uses $c=0.5$).
- $A_i$: Surface area of the segment available for convection ($2 \pi r_{wire} \delta h$) (m²).
- $T_{dielectric}$: Temperature of the dielectric fluid (K).

### 5. Advection ($\dot{Q}_{adv,i}$)

Heat is transported through segment $i$ due to the physical movement (advection) of the wire. This process involves two components for segment $i$, modeled using an upwind scheme:

1.  **Heat Advected INTO Segment $i$ ($\dot{Q}_{adv,in,i}$):**
    This is the thermal energy carried into segment $i$ by the wire material moving from the adjacent upstream segment ($i-1$).
    $$
    \dot{Q}_{adv,in,i} = \dot{m} c_p T_{i-1}
    $$
    Where $\dot{m} = \rho S v_{wire}$ is the mass flow rate of the wire, $\rho$ is the density, $S$ is the cross-sectional area, $v_{wire}$ is the wire velocity, $c_p$ is the specific heat capacity, and $T_{i-1}$ is the temperature of the upstream segment.

2.  **Heat Advected OUT OF Segment $i$ ($\dot{Q}_{adv,out,i}$):**
    This is the thermal energy carried out of segment $i$ by its own material as it moves downstream.
    $$
    \dot{Q}_{adv,out,i} = \dot{m} c_p T_i
    $$
    Where $T_i$ is the temperature of the current segment $i$.

The net rate of heat gain by segment $i$ due to advection, $\dot{Q}_{adv,i}$, which appears in the main heat balance equation, is the difference between the heat advected in and the heat advected out:
$$
\dot{Q}_{adv,i} = \dot{Q}_{adv,in,i} - \dot{Q}_{adv,out,i} = \dot{m} c_p (T_{i-1} - T_i)
$$
This can also be expressed as:
$$
\dot{Q}_{adv,i} = (\rho_{wire} S c_p) (T_{i-1} - T_i)v_{wire}
$$

Where:
- $v_{wire}$: Wire unwinding velocity (m/s).
- $T_{i-1}$ represents the temperature of the material entering segment $i$.

## Update Equation

The temperature $T_i$ of each segment is updated at each simulation time step $\Delta t$ using the calculated total rate of change $\frac{dT_i}{dt}$:

$$
T_i(t + \Delta t) = T_i(t) + \left( \frac{\dot{Q}_{cond,i} + \dot{Q}_{joule,i} + \dot{Q}_{plasma,i} - \dot{Q}_{conv,i} + \dot{Q}_{adv,i}}{\rho c_p S \delta h} \right) \Delta t
$$

The denominator `self.denominator` = $\rho c_p S \delta h$.

## Initialization and State

-   **Initial Wire Temperature**: The wire temperature is initialized to `spool_T` for all segments.
-   **Material Properties**: Default material properties for brass are used (density, specific heat, thermal conductivity, electrical resistivity, temperature coefficient of resistivity).
-   **Geometric Properties**: Wire radius, segment length, buffer lengths are configurable.

## Key Variables in Code

-   `state.wire_temperature`: NumPy array holding the temperature of each segment.
-   `self.spool_T`: Temperature of the wire on the spool (Dirichlet BC).
-   `self.seg_L`: Length of each segment ($\delta h$).
-   `self.delta_y`: Segment length in meters.
-   `self.S`: Wire cross-sectional area.
-   `self.A`: Segment surface area for convection.
-   `self.k_cond_coeff`: Pre-calculated coefficient for conduction term.
-   `self.denominator`: Pre-calculated denominator for the $\frac{dT}{dt}$ calculation ($\rho c_p S \delta h$).
-   `dt_sim`: Simulation timestep (assumed 1 µs).
-   `state.current`: Machining current $I$.
-   `state.voltage`: Machining voltage $V_{spark}$.
-   `state.spark_status`: Array indicating if a spark is active (`[1, y_spark_pos, 0]`).
-   `state.dielectric_temperature`: Temperature of the dielectric fluid.
-   `state.wire_unwinding_velocity`: Speed of the wire.

The module uses pre-allocated NumPy arrays for intermediate calculations to optimize performance within the `update` loop. The order of calculation is: Conduction, Joule Heating, Plasma Heating, Convection, Advection, and finally the temperature update. 