# Material Removal Module: Empirical Crater-Based Material Removal Model

The `MaterialRemovalModule` simulates the material removal process in Wire Electrical Discharge Machining (WEDM) using empirical crater volume distributions derived from experimental data. This module models how each spark discharge removes material from the workpiece, advancing the workpiece position based on statistically sampled crater volumes.

## Overview

Material removal in WEDM occurs through discrete spark discharges that create small craters on the workpiece surface. Each spark removes a specific volume of material, which depends primarily on the discharge current. The module uses empirical data to model this stochastic process, providing realistic material removal rates that match experimental observations.

## Theoretical Foundation

### Material Removal Mechanism

In WEDM, material removal occurs through the following physical process:

1. **Spark Ignition**: An electrical discharge creates a plasma channel between the wire and workpiece
2. **Material Melting/Vaporization**: The intense heat from the plasma melts and vaporizes workpiece material
3. **Crater Formation**: The molten material is expelled, creating a crater on the workpiece surface
4. **Workpiece Advancement**: The cumulative effect of multiple craters allows the workpiece to advance

### Crater Volume Model

The module models crater volumes using empirical distributions based on discharge current. Each crater volume \(V_c\) is sampled from a Gaussian distribution:

\[
V_c \sim \mathcal{N}(\mu_I, \sigma_I^2)
\]

Where:
- \(\mu_I\): Mean crater volume for current \(I\) (μm³)
- \(\sigma_I\): Standard deviation of crater volume for current \(I\) (μm³)
- \(I\): Discharge current (A)

The empirical parameters \(\mu_I\) and \(\sigma_I\) are derived from experimental measurements and stored in the crater volume database.

### Workpiece Position Calculation

The workpiece position increment \(\Delta X_w\) for each crater is calculated using the relationship:

\[
\Delta X_w = \frac{V_c}{k \cdot h_w}
\]

Where:
- \(V_c\): Crater volume (mm³)
- \(k\): Kerf width (mm)
- \(h_w\): Workpiece height (mm)

The kerf width \(k\) is a critical parameter and is determined by the wire diameter, a base overcut, and the depth of the discharge crater. It is calculated as:

\[
k = D_w + k_{base} + \frac{d_{crater,μm}}{1000}
\]

Where:
- \(D_w\): Wire diameter (mm)
- \(k_{base} = 0.12\) mm: Base overcut, representing the minimum symmetrical discharge gap around the wire (0.06 mm per side)
- \(d_{crater,μm}\): Crater depth for the current discharge setting (μm), obtained from empirical data

This formulation provides a physically grounded kerf width that incorporates the fixed dimension of the wire, a minimum operational overcut, and a dynamic component related to the discharge energy (via crater depth).

## Current Mode Mapping

### Machine Current Modes

The WEDM machine operates with predefined current modes (I1 through I19) that correspond to specific current levels:

| Mode | Current (A) | Mode | Current (A) | Mode | Current (A) |
|------|-------------|------|-------------|------|-------------|
| I1   | 30          | I8   | 95          | I15  | 305         |
| I2   | 35          | I9   | 110         | I16  | 360         |
| I3   | 40          | I10  | 130         | I17  | 425         |
| I4   | 50          | I11  | 155         | I18  | 500         |
| I5   | 60          | I12  | 180         | I19  | 600         |
| I6   | 68          | I13  | 215         |      |             |
| I7   | 80          | I14  | 255         |      |             |

### Crater Data Current Mapping

The empirical crater data is available for specific current levels: [1, 3, 5, 7, 9, 11, 13, 15, 17] A. To map machine currents to available crater data, the module uses a scaling approach:

\[
I_{crater} = I_{available}[\lfloor r \cdot (N-1) \rfloor]
\]

Where:
- \(r = \frac{I_{machine} - I_{min}}{I_{max} - I_{min}}\): Relative position in machine current range
- \(I_{min} = 30\) A, \(I_{max} = 600\) A: Machine current range
- \(I_{available}\): Array of available crater data currents
- \(N = 9\): Number of available crater data points

## Empirical Crater Data

### Data Structure

The crater volume data contains the following parameters for each current level:

- **average**: Mean crater area (μm²)
- **std**: Standard deviation of crater area (μm²)
- **depth**: Mean crater depth (μm)
- **ellipsoid_volume_half**: Mean crater volume using half-ellipsoid model (μm³)
- **ellipsoid_volume_std**: Standard deviation of crater volume (μm³)

### Volume Calculation

The module uses the half-ellipsoid volume model, which provides realistic crater volumes based on experimental observations:

\[
V_{ellipsoid\_half} = \frac{2}{3} \pi \cdot a \cdot b \cdot c
\]

Where \(a\), \(b\), and \(c\) are the semi-axes of the ellipsoid derived from the crater area and depth measurements.

### Current-Volume Relationship

The empirical data demonstrates a clear relationship between discharge current and crater volume:

| Current (A) | Mean Volume (μm³) | Std Volume (μm³) |
|-------------|-------------------|------------------|
| 1           | 2,164             | 448              |
| 3           | 2,377             | 524              |
| 5           | 4,867             | 899              |
| 7           | 5,557             | 1,167            |
| 9           | 6,219             | 1,284            |
| 11          | 6,030             | 1,006            |
| 13          | 8,914             | 2,949            |
| 15          | 26,469            | 6,472            |
| 17          | 59,550            | 8,998            |

## Implementation Details

### Spark-Triggered Material Removal

Material removal occurs during fresh spark events, identified by the spark state transition to active status with zero duration counter. This ensures that material is removed exactly once per spark, at the moment of ignition.

### Computational Efficiency

The module implements a caching system to optimize performance:

- **Current Mode Cache**: Stores the last processed current mode
- **Machine Current Cache**: Stores the corresponding machine current value
- **Mapped Current Cache**: Stores the mapped crater data current
- **Crater Info Cache**: Stores the crater distribution parameters

The cache is invalidated only when the current mode changes, improving computational efficiency.

### Unit Conversions

The module handles multiple unit systems with appropriate conversion factors:

- **Crater volumes**: Converted from μm³ (empirical data) to mm³ (calculation)
- **Crater depths**: Converted from μm (empirical data) to mm (calculation)
- **Position increments**: Converted from mm (calculation) to μm (state)

The conversion factors are:
- μm³ to mm³: divide by \(10^9\)
- μm to mm: divide by \(10^3\)
- mm to μm: multiply by \(10^3\)

## Mathematical Formulation Summary

The complete material removal process can be summarized as:

1. **Current Mapping**:
   \[
   I_{crater} = f_{map}(I_{machine})
   \]

2. **Crater Volume Sampling**:
   \[
   V_c \sim \mathcal{N}(\mu_{I_{crater}}, \sigma_{I_{crater}}^2)
   \]

3. **Kerf Width Calculation**:
   \[
   k = D_w + k_{base} + \frac{d_{crater,μm}}{1000}
   \]

4. **Position Increment**:
   \[
   \Delta X_w = \frac{V_c \cdot 10^{-9}}{k \cdot h_w} \cdot 1000
   \]

5. **Workpiece Position Update**:
   \[
   X_{w,new} = X_{w,old} + \Delta X_w
   \]

## Key Variables

- `current_mode`: Current mode setting (I1-I19)
- `workpiece_position`: Workpiece position (μm)
- `wire_position`: Wire position (μm)
- `spark_status`: Spark state information [state, location, duration]
- `wire_diameter`: Wire diameter (mm)
- `workpiece_height`: Workpiece height (mm)
- `crater_data`: Empirical crater volume distributions
- `currents_data`: Current mode to amperage mapping

## Integration with System Modules

The material removal module operates in coordination with other simulation modules:

- **Ignition Module**: Provides spark events that trigger material removal
- **Wire Module**: Responds to gap changes resulting from material removal
- **Control Module**: Provides current mode settings that determine crater characteristics

The module updates the workpiece position, which directly affects the gap calculation used throughout the simulation system, creating a coupled system that accurately represents the WEDM process. 