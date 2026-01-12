# Wire Module: 1-D Transient Heat Model

The `WireModule` simulates the temperature distribution along the travelling wire in a Wire Electrical Discharge Machining (WEDM) process. It employs a 1-D transient heat model, discretizing the wire into a series of segments and updating their state using a Lagrangian approach (moving reference frame).

## Discretization and Geometry

The wire is modeled as a sequence of $N$ segments, covering a total length $L_{total}$ which includes the workpiece height and buffer zones above and below.

$$
L_{total} = L_{buffer,bottom} + H_{workpiece} + L_{buffer,top}
$$

-   $L_{buffer,bottom}$: Buffer length below the workpiece.
-   $H_{workpiece}$: Height of the workpiece.
-   $L_{buffer,top}$: Buffer length above the workpiece.

The wire travels upwards (from bottom to top in the simulation frame).

### Moving Reference Frame (Lagrangian Approach)

Instead of a fixed grid with an advection term, the module uses a **moving segment model**. Each segment represents a fixed mass of wire that moves physically through the domain.
-   **Movement**: In each time step $\Delta t$, all segments move by $\Delta y = v_{wire} \cdot \Delta t$.
-   **Rollover**: The implementation uses a circular buffer. When a segment moves beyond the top boundary ($L_{total}$), it is "recycled" to the bottom inlet ($y=0$).
    -   Its temperature is reset to the spool temperature ($T_{spool}$).
    -   Its accumulated damage is reset to 0.
-   This approach eliminates numerical diffusion associated with Eulerian advection schemes and naturally handles the transport of heat and damage.

## Heat Transfer Mechanisms

The temperature change for each segment is calculated using a finite difference method. Since the segments move with the wire, the explicit advection term is removed from the heat equation. The governing equation for a segment $i$ is:

$$
\rho c_p V_i \frac{dT_i}{dt} = \dot{Q}_{cond,i} + \dot{Q}_{joule,i} + \dot{Q}_{plasma,i} - \dot{Q}_{conv,i}
$$

### 1. Conduction ($\dot{Q}_{cond,i}$)

Heat conduction occurs between adjacent segments.
$$
\dot{Q}_{cond,i} = k S \frac{T_{i-1} - 2T_i + T_{i+1}}{\delta h}
$$
-   **Boundary Conditions**:
    -   **Inlet (Bottom)**: Fixed temperature $T=T_{spool}$ (Dirichlet).
    -   **Outlet (Top)**: Zero gradient $\frac{dT}{dy}=0$ (Neumann), approximated by $T_{last} = T_{second\_last}$.

### 2. Joule Heating ($\dot{Q}_{joule,i}$)

Joule heating is applied based on the current path driven by the spark location.
-   **Current Splitting**: When a spark occurs at location $y_{spark}$, the current $I$ splits between the path to the top contact and the path to the bottom contact.
    -   The split is inversely proportional to the path resistance (length).
    -   $I_{top} \propto L_{bottom}$ and $I_{bottom} \propto L_{top}$.
-   **Heating**: Calculated as $I^2 R$ for segments along the active path(s).
    $$
    \dot{Q}_{joule,i} = \frac{I_{path}^2 \rho_{elec}(T_i) \cdot \delta h}{S}
    $$
    -   $\rho_{elec}(T)$ includes temperature dependence: $\rho = \rho_{ref}[1 + \alpha(T - T_{ref})]$.

### 3. Plasma Heat Flux ($\dot{Q}_{plasma,i}$)

Heat from the discharge plasma is applied to the specific segment at the spark location ($y_{spark}$).
$$
\dot{Q}_{plasma} = \eta_{plasma} \cdot V \cdot I
$$
-   $\eta_{plasma}$: Plasma efficiency factor (fraction of power entering the wire).
-   This is a localized heat source applied only to the segment containing the spark.

### 4. Convection ($\dot{Q}_{conv,i}$)

Heat loss to the dielectric fluid.
$$
\dot{Q}_{conv,i} = h_{eff} A_{surf} (T_i - T_{dielectric})
$$
-   **$h_{eff}$**: Effective convection coefficient, enhanced by:
    -   **Wire Velocity**: $1 + c_v \cdot v_{wire}$
    -   **Flushing Flow**: Enhanced in the gap region based on flow rate.

## Damage Model (Wire Breakage)

The module implements a thermomechanical damage model based on the CIRP-HPC 2026 paper. Damage $D$ accumulates over time, leading to failure if $D \ge 1.0$.

$$
\dot{D} = k \cdot \sigma^n \cdot \exp\left(-\frac{Q}{R T}\right)
$$

-   **$\sigma$**: Tensile stress in the wire ($\sigma = F_{tension} / S$).
-   **$T$**: Temperature (K). Damage only accumulates if $T > T_{threshold}$ (150°C).
-   **Constants**:
    -   $k$: Rate constant.
    -   $n$: Stress exponent.
    -   $Q$: Activation energy.
    -   $R$: Gas constant.

## Implementation Details

-   **Numba Optimization**: The core thermal update loop (`compute_thermal_update`) is JIT-compiled using Numba for high performance.
-   **Data Structures**:
    -   Stores temperature, damage, and positions in NumPy arrays.
    -   Uses a `Segment` dataclass for high-level abstraction but relies on arrays for computation.
-   **Time Step**: Defaults to $\Delta t = 1 \mu s$.