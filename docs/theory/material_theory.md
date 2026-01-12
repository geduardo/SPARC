# Material Removal Module: Empirical Crater-Based Material Removal Model

The `MaterialRemovalModule` simulates the material removal process in Wire Electrical Discharge Machining (WEDM) using empirical crater volume distributions derived from experimental data. This module models how each spark discharge removes material from the workpiece, advancing the workpiece position based on statistically sampled crater volumes.

## Overview

Material removal in WEDM occurs through discrete spark discharges that create small craters on the workpiece surface. Each spark removes a specific volume of material, which depends primarily on the discharge current. The module uses empirical data to model this stochastic process, providing realistic material removal rates that match experimental observations.

## Theoretical Foundation

### Material Removal Mechanism

In WEDM, material removal occurs through the following physical process:

1.  **Spark Ignition**: An electrical discharge creates a plasma channel between the wire and workpiece.
2.  **Material Melting/Vaporization**: The intense heat from the plasma melts and vaporizes workpiece material.
3.  **Crater Formation**: The molten material is expelled, creating a crater on the workpiece surface.
4.  **Workpiece Advancement**: The cumulative effect of multiple craters allows the workpiece to advance.

### Crater Volume Model

The module models crater volumes using empirical distributions based on discharge current. Each crater volume $V_c$ is sampled from a Gaussian distribution:

$$
V_c \sim \mathcal{N}(\mu_I, \sigma_I^2)
$$

Where:
-   $\mu_I$: Mean crater volume for current $I$ (μm³)
-   $\sigma_I$: Standard deviation of crater volume for current $I$ (μm³)
-   $I$: Discharge current (A)

The empirical parameters $\mu_I$ and $\sigma_I$ are loaded from `crater_data.json`.

### Workpiece Position Calculation

The workpiece position increment $\Delta X_w$ for each crater is calculated using the relationship:

$$
\Delta X_w = \frac{V_c}{k \cdot h_w}
$$

Where:
-   $V_c$: Crater volume (mm³)
-   $k$: Kerf width (mm)
-   $h_w$: Workpiece height (mm)

The kerf width $k$ is a critical parameter and is determined by the wire diameter, a base overcut, and the depth of the discharge crater. It is calculated as:

$$
k = D_w + k_{base} + \frac{d_{crater,μm}}{1000}
$$

Where:
-   $D_w$: Wire diameter (mm)
-   $k_{base}$: Base overcut (default: 0.026 mm). This represents the minimum discharge gap.
-   $d_{crater,μm}$: Crater depth for the current discharge setting (μm), obtained from empirical data.

## Current Mode Mapping

### Machine Current Modes

The WEDM machine operates with predefined current modes (e.g., I1 through I19) that correspond to specific current levels. These mappings are loaded from `currents.json`.

### Crater Data Current Mapping

The empirical crater data is available for specific current levels. If a machine current doesn't exactly match an available data point, the module maps it to the nearest available dataset or uses a standard mapping logic (as described in the implementation).

## Empirical Crater Data

### Data Structure

The crater volume data (`crater_data.json`) contains the following parameters for each current level:

-   **average_area_um2**: Mean crater area (μm²)
-   **area_std_um2**: Standard deviation of crater area (μm²)
-   **depth_um**: Mean crater depth (μm)
-   **volume_um3**: Mean crater volume (μm³), scaled to match experimental material removal rates
-   **volume_std_um3**: Standard deviation of crater volume (μm³)

### Volume Scaling

The crater volumes are scaled based on experimental validation.

## Implementation Details

-   **Data Sources**:
    -   `crater_data.json`: Contains crater geometry statistics (scaled to experimental removal rates).
    -   `currents.json`: Contains machine current mode definitions.
-   **Sampling**: Gaussian sampling is used for crater volumes.
-   **Caching**: To optimize performance, current mode lookups and crater data retrieval are cached.
-   **Unit Handling**: The system carefully handles conversions between $\mu m$ (micro-scale physics) and $mm$ (macro-scale geometry).

## Key Variables

-   `current_mode`: Current mode setting (I1-I19).
-   `workpiece_position`: Workpiece position (μm).
-   `wire_position`: Wire position (μm).
-   `spark_status`: Spark state information [state, location, duration].
-   `last_crater_volume`: The volume of the most recent crater, exposed for debris tracking.