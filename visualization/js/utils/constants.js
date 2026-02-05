/**
 * SPARC Dashboard Constants
 * Centralized configuration values and magic numbers
 */

// ============================================================================
// Playback Settings
// ============================================================================

/** Default playback speed in microseconds per second */
export const DEFAULT_PLAYBACK_SPEED = 60;

/** Target display frame rate */
export const TARGET_FPS = 60;

/** Base number of frames sparks remain visible */
export const BASE_SPARK_PERSISTENCE_FRAMES = 10;

/** Target spark visibility duration in milliseconds */
export const SPARK_VISIBILITY_MS = 200;

// ============================================================================
// Wire & Workpiece Defaults
// ============================================================================

/** Default wire diameter in mm */
export const DEFAULT_WIRE_DIAMETER = 0.25;

/** Default workpiece thickness in mm */
export const DEFAULT_WORKPIECE_THICKNESS = 5.0;

/** Default initial gap in mm */
export const DEFAULT_INITIAL_GAP = 0.05;

/** Default zoom level for views */
export const DEFAULT_ZOOM_LEVEL = 3.0;

// ============================================================================
// Nozzle Geometry (scaled from original dimensions)
// ============================================================================

/** Nozzle scale factor (15 / 1.6 = 9.375x from original) */
export const NOZZLE_SCALE_FACTOR = 9.375;

/** Nozzle width at base in mm (6.0 * 9.375) */
export const NOZZLE_WIDTH_MM = 56.25;

/** Nozzle narrow width in mm (1.6 * 9.375) */
export const NOZZLE_NARROW_MM = 15.0;

/** Nozzle height in mm (2.0 * 9.375) */
export const NOZZLE_HEIGHT_MM = 18.75;

/** Distance from wire center to nozzle + buffer zone in mm */
export const NOZZLE_BUFFER_DISTANCE_MM = 118.75;

/** Extra margin for view calculations in mm */
export const VIEW_MARGIN_MM = 20;

// ============================================================================
// Material Tracking
// ============================================================================

/** Local search radius for material tracking (segments) */
export const MATERIAL_SEARCH_RADIUS = 25;

/** Maximum distance for material tracking fallback in mm */
export const MATERIAL_TRACKING_FALLBACK_DISTANCE = 2.0;

/** Maximum allowed tracking distance before losing track in mm */
export const MATERIAL_TRACKING_MAX_DISTANCE = 10.0;

// ============================================================================
// Oscilloscope Settings
// ============================================================================

/** Number of horizontal divisions on oscilloscope */
export const OSC_HORIZONTAL_DIVISIONS = 10;

/** Number of vertical divisions on oscilloscope */
export const OSC_VERTICAL_DIVISIONS = 8;

/** Oscilloscope grid color */
export const OSC_GRID_COLOR = '#3a5a3a';

/** Oscilloscope background color */
export const OSC_BACKGROUND_COLOR = '#1a1a1a';

/** Channel 1 (Voltage) color */
export const OSC_CH1_COLOR = '#4fc3ff';

/** Channel 2 (Current) color */
export const OSC_CH2_COLOR = '#ff6aa0';

// ============================================================================
// Thermal Profile Settings
// ============================================================================

/** Minimum temperature for color scale in Kelvin */
export const THERMAL_MIN_TEMP_K = 293;

/** Maximum temperature for color scale in Kelvin */
export const THERMAL_MAX_TEMP_K = 3695;

/** Melting point of brass (wire material) in Kelvin */
export const BRASS_MELTING_POINT_K = 1200;

// ============================================================================
// Color Palette (Modern Minimal)
// ============================================================================

export const COLORS = {
    // Backgrounds
    bg: '#f8f9fa',
    bgDark: '#1a1d21',
    bgMedium: '#252a30',
    bgPanel: '#ffffff',
    bgCanvas: '#e8eef4',
    bgThermal: '#ffffff',

    // Accents
    accent: '#0066cc',
    accentHover: '#0052a3',
    success: '#28a745',
    warning: '#fd7e14',
    danger: '#dc3545',

    // Neutrals
    gray1: '#e9ecef',
    gray2: '#dee2e6',
    gray3: '#ced4da',
    gray4: '#adb5bd',
    gray5: '#6c757d',
    gray6: '#495057',
    text: '#212529',
    textSecondary: '#495057',
    textMuted: '#6c757d',

    // Workpiece
    workpiece: '#C0C0C0',
    workpieceStroke: '#a0a0a0',

    // Water/fluid
    water: 'rgba(70, 130, 180, 0.5)',
    waterDark: 'rgba(50, 110, 160, 0.6)',

    // Spark colors
    sparkCore: '#ffffff',
    sparkGlow: 'rgba(220, 53, 69, 0.85)',
    sparkOuter: 'rgba(253, 126, 20, 0.5)',
};

// ============================================================================
// File Size Limits
// ============================================================================

/** Warning threshold for large JSON files in bytes (500 MB) */
export const LARGE_FILE_WARNING_BYTES = 500 * 1024 * 1024;
