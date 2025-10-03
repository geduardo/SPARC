// ============================================================================
// SPARC Visualization Dashboard - Main Controller
// ============================================================================

class DashboardController {
    constructor() {
        this.data = null;
        this.currentFrame = 0;
        this.isPlaying = false;
        this.animationId = null;
        this.playbackSpeed = 1.0;

        // Panel instances
        this.panels = {
            sideView: null,
            oscilloscope: null,
            topView: null,
            thermal: null
        };

        this.init();
    }

    init() {
        // Get DOM elements
        this.elements = {
            loadData: document.getElementById('loadData'),
            fileInput: document.getElementById('fileInput'),
            playPause: document.getElementById('playPause'),
            reset: document.getElementById('reset'),
            timeline: document.getElementById('timeline'),
            timeDisplay: document.getElementById('timeDisplay'),
            loadingOverlay: document.getElementById('loadingOverlay')
        };

        // Setup event listeners
        this.elements.loadData.addEventListener('click', () => this.elements.fileInput.click());
        this.elements.fileInput.addEventListener('change', (e) => this.loadDataFile(e));
        this.elements.playPause.addEventListener('click', () => this.togglePlayPause());
        this.elements.reset.addEventListener('click', () => this.resetTimeline());
        this.elements.timeline.addEventListener('input', (e) => this.seekTo(parseInt(e.target.value)));

        // Initialize panels
        this.initializePanels();

        // Handle window resize
        window.addEventListener('resize', () => this.handleResize());

        console.log('Dashboard initialized. Load a simulation data file to begin.');
    }

    initializePanels() {
        // Create panel instances
        this.panels.sideView = new SideViewPanel('sideViewCanvas');
        this.panels.oscilloscope = new OscilloscopePanel('oscilloscopeCanvas');
        this.panels.topView = new TopViewPanel('topViewCanvas');
        this.panels.thermal = new ThermalProfilePanel('thermalCanvas');

        // Set up shared camera between TopView and SideView
        this.panels.sideView.sharedCamera = this.panels.topView;

        // Initialize all panels
        Object.values(this.panels).forEach(panel => panel.init());
    }

    async loadDataFile(event) {
        const file = event.target.files[0];
        if (!file) return;

        this.showLoading(true);

        try {
            const text = await file.text();
            this.data = JSON.parse(text);

            console.log('Data loaded:', this.data);

            // Validate data
            if (!this.data.time || !Array.isArray(this.data.time)) {
                throw new Error('Invalid data format: missing time array');
            }

            // Setup timeline
            const maxFrame = this.data.time.length - 1;
            this.elements.timeline.max = maxFrame;
            this.currentFrame = 0;

            // Update panels with data
            Object.values(this.panels).forEach(panel => {
                if (panel.setData) {
                    panel.setData(this.data);
                }
            });

            // Draw first frame
            this.drawFrame(0);
            this.updateTimeDisplay();

            console.log(`Loaded ${this.data.time.length} frames`);
        } catch (error) {
            console.error('Error loading data:', error);
            alert(`Error loading data: ${error.message}`);
        } finally {
            this.showLoading(false);
        }
    }

    togglePlayPause() {
        if (!this.data) {
            alert('Please load data first');
            return;
        }

        this.isPlaying = !this.isPlaying;
        this.elements.playPause.textContent = this.isPlaying ? '⏸ Pause' : '▶ Play';

        if (this.isPlaying) {
            this.play();
        } else {
            this.pause();
        }
    }

    play() {
        const animate = () => {
            if (!this.isPlaying) return;

            this.currentFrame++;
            if (this.currentFrame >= this.data.time.length) {
                this.currentFrame = 0; // Loop
            }

            this.drawFrame(this.currentFrame);
            this.updateTimeDisplay();
            this.elements.timeline.value = this.currentFrame;

            // Request next frame (60 FPS max)
            this.animationId = requestAnimationFrame(animate);
        };

        animate();
    }

    pause() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
    }

    resetTimeline() {
        this.pause();
        this.isPlaying = false;
        this.elements.playPause.textContent = '▶ Play';
        this.seekTo(0);
    }

    seekTo(frame) {
        if (!this.data) return;

        this.currentFrame = Math.max(0, Math.min(frame, this.data.time.length - 1));
        this.drawFrame(this.currentFrame);
        this.updateTimeDisplay();
    }

    drawFrame(frameIndex) {
        if (!this.data) return;

        const frameData = this.getFrameData(frameIndex);

        // Update all panels
        Object.values(this.panels).forEach(panel => {
            panel.draw(frameData, frameIndex);
        });
    }

    getFrameData(frameIndex) {
        // Extract data for current frame from all signals
        const frameData = {
            time: this.data.time[frameIndex],
            frameIndex: frameIndex,
            totalFrames: this.data.time.length
        };

        // Add all available signals
        for (const key in this.data) {
            if (key !== 'metadata' && Array.isArray(this.data[key])) {
                frameData[key] = this.data[key][frameIndex];
            }
        }

        return frameData;
    }

    updateTimeDisplay() {
        if (!this.data) return;

        const currentTime = this.data.time[this.currentFrame] / 1000; // Convert µs to ms
        const totalTime = this.data.time[this.data.time.length - 1] / 1000;

        const formatTime = (ms) => {
            const seconds = Math.floor(ms / 1000);
            const milliseconds = Math.floor(ms % 1000);
            return `${String(seconds).padStart(2, '0')}:${String(milliseconds).padStart(3, '0')}`;
        };

        this.elements.timeDisplay.textContent =
            `${formatTime(currentTime)} / ${formatTime(totalTime)}`;
    }

    handleResize() {
        Object.values(this.panels).forEach(panel => {
            if (panel.onResize) {
                panel.onResize();
            }
        });

        // Redraw current frame
        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
    }

    showLoading(show) {
        this.elements.loadingOverlay.classList.toggle('hidden', !show);
    }
}

// ============================================================================
// Base Panel Class - All panels inherit from this
// ============================================================================

class BasePanel {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.data = null;
    }

    init() {
        this.setupCanvas();
    }

    setupCanvas() {
        // Set canvas resolution to match display size
        const rect = this.canvas.getBoundingClientRect();
        this.canvas.width = rect.width * window.devicePixelRatio;
        this.canvas.height = rect.height * window.devicePixelRatio;
        this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    }

    setData(data) {
        this.data = data;
        console.log(`${this.constructor.name} data set`);
    }

    onResize() {
        this.setupCanvas();
    }

    clear() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }

    // Helper to draw text
    drawText(text, x, y, options = {}) {
        const {
            color = '#ffffff',
            font = '12px sans-serif',
            align = 'left',
            baseline = 'top'
        } = options;

        this.ctx.fillStyle = color;
        this.ctx.font = font;
        this.ctx.textAlign = align;
        this.ctx.textBaseline = baseline;
        this.ctx.fillText(text, x, y);
    }

    // Override in subclasses
    draw(frameData, frameIndex) {
        this.clear();
        this.drawText('Panel not implemented', 10, 10, { color: '#888' });
    }
}

// ============================================================================
// Panel 1: Side View (Wire + Workpiece + Spark)
// ============================================================================

class SideViewPanel extends BasePanel {
    constructor(canvasId) {
        super(canvasId);

        // Default values
        this.wireDiameter = 0.25; // mm
        this.workpieceThickness = 5.0; // mm (example thickness)

        // Shared camera with TopView (will be set by DashboardController)
        this.sharedCamera = null;
    }

    draw(frameData, frameIndex) {
        this.clear();

        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;

        // Background
        this.ctx.fillStyle = '#fbf1c7';
        this.ctx.fillRect(0, 0, w, h);

        if (!frameData) {
            this.drawText('Side View', w/2, h/2, {
                color: '#427b58',
                font: 'bold 16px sans-serif',
                align: 'center',
                baseline: 'middle'
            });
            return;
        }

        // Get camera position from shared camera (TopView)
        const cameraX = this.sharedCamera ? this.sharedCamera.cameraX : 0;
        const zoomLevel = this.sharedCamera ? this.sharedCamera.zoomLevel : 3.0;

        // Scale calculation (match horizontal scale with TopView)
        const viewWidth = this.wireDiameter * zoomLevel;
        const scale = (w * 0.8) / viewWidth;

        // Wire position
        const wireEdgePos = frameData.wire_position || 0; // µm
        const wireRadius = this.wireDiameter / 2; // mm
        const wireCenterX = (wireEdgePos / 1000) - wireRadius; // mm

        // Save context
        this.ctx.save();

        // Setup camera transform (same as TopView horizontal)
        this.ctx.translate(w / 2, h / 2);
        this.ctx.translate(-cameraX * scale, 0);

        // Workpiece frontier position
        const workpieceEdgePos = frameData.workpiece_position || 0; // µm
        const workpieceEdgeX = workpieceEdgePos / 1000; // mm

        // Draw water dielectric everywhere
        this.drawWater(scale, h);

        // Draw cut material behind wire
        this.drawCutMaterial(workpieceEdgeX, scale, h);

        // Draw workpiece (full thickness block, starting from workpiece edge)
        this.drawWorkpiece(workpieceEdgeX, scale, h);

        // Draw nozzles
        this.drawNozzles(wireCenterX, wireRadius, scale);

        // Draw wire
        this.drawWire(wireCenterX, wireRadius, scale, frameData);

        // Draw spark if active
        if (frameData.spark_status && frameData.spark_status[0] === 1) {
            this.drawSpark(wireCenterX, wireRadius, workpieceEdgeX, scale);
        }

        // Restore context
        this.ctx.restore();

        // Draw info overlay
        this.drawInfoOverlay(w, h, frameData);
    }

    drawWorkpiece(workpieceEdgeX, scale, canvasHeight) {
        const maxDim = canvasHeight * 2;
        const workpieceHalfThickness = (this.workpieceThickness / 2) * scale;
        const workpieceEdgeXPx = workpieceEdgeX * scale;

        // Workpiece block (from workpiece edge to the right)
        this.ctx.fillStyle = '#bdae93'; // Gruvbox gray
        this.ctx.fillRect(
            workpieceEdgeXPx,
            -workpieceHalfThickness,
            maxDim * 4,
            this.workpieceThickness * scale
        );

        // Left edge (frontier face)
        this.ctx.strokeStyle = '#665c54';
        this.ctx.lineWidth = 2.5;
        this.ctx.beginPath();
        this.ctx.moveTo(workpieceEdgeXPx, -workpieceHalfThickness);
        this.ctx.lineTo(workpieceEdgeXPx, workpieceHalfThickness);
        this.ctx.stroke();

        // Top edge
        this.ctx.lineWidth = 2;
        this.ctx.beginPath();
        this.ctx.moveTo(workpieceEdgeXPx, -workpieceHalfThickness);
        this.ctx.lineTo(workpieceEdgeXPx + maxDim * 4, -workpieceHalfThickness);
        this.ctx.stroke();

        // Bottom edge
        this.ctx.beginPath();
        this.ctx.moveTo(workpieceEdgeXPx, workpieceHalfThickness);
        this.ctx.lineTo(workpieceEdgeXPx + maxDim * 4, workpieceHalfThickness);
        this.ctx.stroke();

        // Texture lines
        this.ctx.strokeStyle = 'rgba(60, 56, 54, 0.15)';
        this.ctx.lineWidth = 0.5;
        const gridSpacing = 10 * scale;

        for (let x = workpieceEdgeXPx + gridSpacing; x < workpieceEdgeXPx + maxDim * 4; x += gridSpacing) {
            this.ctx.beginPath();
            this.ctx.moveTo(x, -workpieceHalfThickness);
            this.ctx.lineTo(x, workpieceHalfThickness);
            this.ctx.stroke();
        }
    }

    drawWater(scale, canvasHeight) {
        const maxDim = canvasHeight * 2;
        const workpieceHalfThickness = (this.workpieceThickness / 2) * scale;

        // Water everywhere above and below workpiece
        this.ctx.fillStyle = 'rgba(69, 133, 136, 0.35)';

        // Water above workpiece
        this.ctx.fillRect(-maxDim, -maxDim, maxDim * 4, maxDim - workpieceHalfThickness);

        // Water below workpiece
        this.ctx.fillRect(-maxDim, workpieceHalfThickness, maxDim * 4, maxDim - workpieceHalfThickness);

        // Water in the cut channel (where workpiece was removed)
        this.ctx.fillRect(-maxDim, -workpieceHalfThickness, maxDim * 4, this.workpieceThickness * scale);
    }

    drawCutMaterial(workpieceEdgeX, scale, canvasHeight) {
        const maxDim = canvasHeight * 2;
        const workpieceHalfThickness = (this.workpieceThickness / 2) * scale;
        const workpieceEdgeXPx = workpieceEdgeX * scale;

        // Cut material behind wire (lighter/translucent gray showing eroded material)
        this.ctx.fillStyle = 'rgba(189, 174, 147, 0.3)'; // Translucent workpiece color
        this.ctx.fillRect(
            -maxDim,
            -workpieceHalfThickness,
            workpieceEdgeXPx + maxDim,
            this.workpieceThickness * scale
        );
    }

    drawWire(wireCenterX, wireRadius, scale, frameData) {
        const wireCenterXPx = wireCenterX * scale;
        const radiusPx = wireRadius * scale;
        const workpieceHalfThickness = (this.workpieceThickness / 2) * scale;

        // Wire extends vertically through the workpiece
        this.ctx.fillStyle = '#d79921'; // Gruvbox yellow/gold
        this.ctx.fillRect(
            wireCenterXPx - radiusPx,
            -workpieceHalfThickness - radiusPx,
            radiusPx * 2,
            (workpieceHalfThickness * 2) + (radiusPx * 2)
        );

        // Wire edges
        this.ctx.strokeStyle = '#b57614';
        this.ctx.lineWidth = 1.5;
        this.ctx.beginPath();
        this.ctx.moveTo(wireCenterXPx - radiusPx, -workpieceHalfThickness - radiusPx);
        this.ctx.lineTo(wireCenterXPx - radiusPx, workpieceHalfThickness + radiusPx);
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.moveTo(wireCenterXPx + radiusPx, -workpieceHalfThickness - radiusPx);
        this.ctx.lineTo(wireCenterXPx + radiusPx, workpieceHalfThickness + radiusPx);
        this.ctx.stroke();
    }

    drawNozzles(wireCenterX, wireRadius, scale) {
        const wireCenterXPx = wireCenterX * scale;
        const radiusPx = wireRadius * scale;
        const workpieceHalfThickness = (this.workpieceThickness / 2) * scale;

        // Wire ends (same as wire drawing)
        const wireTopEnd = -workpieceHalfThickness - radiusPx;
        const wireBottomEnd = workpieceHalfThickness + radiusPx;

        // Nozzle dimensions
        const nozzleWidth = 3.0 * scale; // 3mm width at base
        const nozzleHeight = 2.0 * scale; // 2mm height
        const nozzleTopWidth = 0.8 * scale; // 0.8mm width at narrow end

        // Upper nozzle (trapezoid pointing down) - ends at wire top
        this.ctx.fillStyle = '#7c6f64'; // Gruvbox darker gray
        this.ctx.beginPath();
        // Top wide edge
        this.ctx.moveTo(wireCenterXPx - nozzleWidth / 2, wireTopEnd - nozzleHeight);
        this.ctx.lineTo(wireCenterXPx + nozzleWidth / 2, wireTopEnd - nozzleHeight);
        // Bottom narrow edge (at wire end)
        this.ctx.lineTo(wireCenterXPx + nozzleTopWidth / 2, wireTopEnd);
        this.ctx.lineTo(wireCenterXPx - nozzleTopWidth / 2, wireTopEnd);
        this.ctx.closePath();
        this.ctx.fill();

        // Nozzle outline
        this.ctx.strokeStyle = '#504945';
        this.ctx.lineWidth = 1.5;
        this.ctx.stroke();

        // Lower nozzle (trapezoid pointing up) - ends at wire bottom
        this.ctx.fillStyle = '#7c6f64';
        this.ctx.beginPath();
        // Bottom wide edge
        this.ctx.moveTo(wireCenterXPx - nozzleWidth / 2, wireBottomEnd + nozzleHeight);
        this.ctx.lineTo(wireCenterXPx + nozzleWidth / 2, wireBottomEnd + nozzleHeight);
        // Top narrow edge (at wire end)
        this.ctx.lineTo(wireCenterXPx + nozzleTopWidth / 2, wireBottomEnd);
        this.ctx.lineTo(wireCenterXPx - nozzleTopWidth / 2, wireBottomEnd);
        this.ctx.closePath();
        this.ctx.fill();

        // Nozzle outline
        this.ctx.strokeStyle = '#504945';
        this.ctx.lineWidth = 1.5;
        this.ctx.stroke();
    }

    drawSpark(wireCenterX, wireRadius, workpieceEdgeX, scale) {
        const wireCenterXPx = wireCenterX * scale;
        const radiusPx = wireRadius * scale;
        const workpieceEdgeXPx = workpieceEdgeX * scale;

        // Spark line thickness: 100 µm = 0.1 mm
        const sparkThickness = 0.1 * scale;

        // Spark position: from wire right edge to workpiece left edge
        const wireRightEdge = wireCenterXPx + radiusPx;
        const workpieceLeftEdge = workpieceEdgeXPx;

        // Random vertical position centered on workpiece thickness
        const workpieceHalfThickness = (this.workpieceThickness / 2) * scale;
        const sparkY = (Math.random() - 0.5) * workpieceHalfThickness * 1.5; // Random position within ±75% of thickness

        // Draw cyan spark line
        this.ctx.strokeStyle = '#8ec07c'; // Gruvbox cyan/aqua
        this.ctx.lineWidth = sparkThickness;
        this.ctx.beginPath();
        this.ctx.moveTo(wireRightEdge, sparkY);
        this.ctx.lineTo(workpieceLeftEdge, sparkY);
        this.ctx.stroke();

        // Add glow effect
        this.ctx.shadowBlur = 5;
        this.ctx.shadowColor = '#8ec07c';
        this.ctx.stroke();
        this.ctx.shadowBlur = 0;
    }

    drawInfoOverlay(w, h, frameData) {
        const padding = 10;
        const lineHeight = 16;
        let y = padding;

        this.drawText('SIDE VIEW', padding, y, { color: '#427b58', font: 'bold 11px sans-serif' });
        y += lineHeight;

        const wireEdgePos = frameData.wire_position || 0;
        const workpieceEdgePos = frameData.workpiece_position || 0;
        const gap = workpieceEdgePos - wireEdgePos;

        this.drawText(`Gap: ${gap.toFixed(1)} µm`, padding, y, { color: '#076678', font: '11px monospace' });
        y += lineHeight;

        this.drawText(`WP Thickness: ${this.workpieceThickness.toFixed(1)} mm`, padding, y, { color: '#7c6f64', font: '11px monospace' });
    }
}

// ============================================================================
// Panel 2: Oscilloscope (Voltage / Current)
// ============================================================================

class OscilloscopePanel extends BasePanel {
    draw(frameData, frameIndex) {
        this.clear();

        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;

        this.ctx.fillStyle = '#fbf1c7';
        this.ctx.fillRect(0, 0, w, h);

        // Draw grid
        this.drawGrid(w, h);

        // Draw placeholder
        this.drawText('Oscilloscope', w/2, h/2, {
            color: '#076678',
            font: 'bold 16px sans-serif',
            align: 'center',
            baseline: 'middle'
        });

        if (frameData && frameData.voltage !== undefined) {
            this.drawText(`Voltage: ${frameData.voltage.toFixed(1)} V`, 10, 10, { color: '#076678' });
        }
        if (frameData && frameData.current !== undefined) {
            this.drawText(`Current: ${frameData.current.toFixed(2)} A`, 10, 25, { color: '#d65d0e' });
        }
    }

    drawGrid(w, h) {
        this.ctx.strokeStyle = '#ebdbb2';
        this.ctx.lineWidth = 1;

        // Horizontal lines
        for (let i = 0; i <= 5; i++) {
            const y = (h / 5) * i;
            this.ctx.beginPath();
            this.ctx.moveTo(0, y);
            this.ctx.lineTo(w, y);
            this.ctx.stroke();
        }

        // Vertical lines
        for (let i = 0; i <= 10; i++) {
            const x = (w / 10) * i;
            this.ctx.beginPath();
            this.ctx.moveTo(x, 0);
            this.ctx.lineTo(x, h);
            this.ctx.stroke();
        }
    }
}

// ============================================================================
// Panel 3: Top View (Wire + Kerf + Workpiece frontier)
// ============================================================================

class TopViewPanel extends BasePanel {
    constructor(canvasId) {
        super(canvasId);

        // Default values (will be updated from data metadata if available)
        this.wireDiameter = 0.25; // mm
        this.initialGap = 50.0; // µm

        // Visualization parameters
        this.scale = 1.0; // pixels per mm
        this.cameraX = 0; // Camera offset in mm (world space)
        this.zoomLevel = 3.0; // User-controlled zoom multiplier (3x wire diameter view)
        this.autoPan = true; // Auto-pan when wire gets close to edge

        // Mouse interaction state
        this.isDragging = false;
        this.lastMouseX = 0;
        this.lastMouseY = 0;

        // Setup mouse controls
        this.setupControls();
    }

    setupControls() {
        // Mouse wheel for zoom
        this.canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const zoomDelta = e.deltaY > 0 ? 1.2 : 0.8;
            this.zoomLevel *= zoomDelta;
            this.zoomLevel = Math.max(0.5, Math.min(50, this.zoomLevel)); // Clamp between 0.5x and 50x (wider range)
        });

        // Mouse drag to pan
        this.canvas.addEventListener('mousedown', (e) => {
            this.isDragging = true;
            this.autoPan = false; // Disable auto-pan when user manually pans
            this.lastMouseX = e.offsetX;
            this.lastMouseY = e.offsetY;
            this.canvas.style.cursor = 'grabbing';
        });

        this.canvas.addEventListener('mousemove', (e) => {
            if (this.isDragging) {
                const dx = e.offsetX - this.lastMouseX;
                this.cameraX -= dx / this.scale; // Convert screen pixels to world space
                this.lastMouseX = e.offsetX;
                this.lastMouseY = e.offsetY;
            }
        });

        this.canvas.addEventListener('mouseup', () => {
            this.isDragging = false;
            this.canvas.style.cursor = 'default';
        });

        this.canvas.addEventListener('mouseleave', () => {
            this.isDragging = false;
            this.canvas.style.cursor = 'default';
        });

        // Double-click to reset view
        this.canvas.addEventListener('dblclick', () => {
            this.zoomLevel = 3.0;
            this.autoPan = true;
            this.cameraX = 0;
        });
    }

    setData(data) {
        super.setData(data);

        // Extract metadata if available
        if (data.metadata) {
            this.wireDiameter = data.metadata.wire_diameter || 0.25;
            this.initialGap = data.metadata.initial_gap || 50.0;
        }
    }

    draw(frameData, frameIndex) {
        this.clear();

        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;

        // Background - Gruvbox light
        this.ctx.fillStyle = '#fbf1c7';
        this.ctx.fillRect(0, 0, w, h);

        // Auto-scale based on user zoom level
        const viewWidth = this.wireDiameter * this.zoomLevel;
        this.scale = (w * 0.8) / viewWidth;

        if (!frameData) {
            this.drawText('Top View - No Data', w/2, h/2, {
                color: '#888',
                font: '14px sans-serif',
                align: 'center',
                baseline: 'middle'
            });
            return;
        }

        // Calculate positions in world space (mm)
        // IMPORTANT: wire_position and workpiece_position refer to EDGES, not centers
        const wireEdgePos = frameData.wire_position || 0; // µm - right edge of wire
        const workpieceEdgePos = frameData.workpiece_position || 0; // µm - left edge of workpiece frontier

        const wireRadius = this.wireDiameter / 2; // mm

        // Kerf width (half on each side of the gap)
        const kerfWidth = this.initialGap / 1000; // Convert µm to mm

        // Workpiece frontier geometry
        const frontierRadius = wireRadius + kerfWidth; // Radius includes wire radius + kerf

        // Calculate CENTER positions from EDGE positions
        // Wire center = wire right edge - wire radius
        const wireCenterX = (wireEdgePos / 1000) - wireRadius; // mm

        // Frontier center = workpiece left edge - frontier radius
        const frontierCenterX = (workpieceEdgePos / 1000) - frontierRadius; // mm

        // Calculate actual gap (surface to surface)
        // Gap = workpiece left edge - wire right edge
        const gapUM = workpieceEdgePos - wireEdgePos; // Already in µm

        // Camera panning: auto-follow wire when enabled
        if (this.autoPan) {
            const wireScreenX = (wireCenterX - this.cameraX) * this.scale + w / 2;
            const edgeThreshold = w * 0.1; // 10% from edge

            // Pan camera if wire is getting too close to left or right edge
            if (wireScreenX < edgeThreshold) {
                this.cameraX = wireCenterX - (edgeThreshold / this.scale) + (w / 2 / this.scale);
            } else if (wireScreenX > w - edgeThreshold) {
                this.cameraX = wireCenterX + (edgeThreshold / this.scale) - (w / 2 / this.scale);
            }
        }

        // Save context
        this.ctx.save();

        // Setup camera transform
        // Center vertically, pan horizontally based on camera
        this.ctx.translate(w / 2, h / 2);
        this.ctx.translate(-this.cameraX * this.scale, 0);

        // Draw workpiece (fills entire area with cut trail behind wire)
        this.drawWorkpiece(frontierCenterX, frontierRadius, wireCenterX, wireRadius);

        // Draw kerf (gap region)
        this.drawKerf(wireCenterX, wireRadius, frontierCenterX, frontierRadius);

        // Draw wire (at wireCenterX position)
        this.drawWire(wireCenterX, wireRadius, frameData);

        // Draw spark if active
        if (frameData.spark_status && frameData.spark_status[0] === 1) {
            this.drawSpark(wireCenterX, wireRadius, frontierCenterX, frontierRadius);
        }

        // Restore context
        this.ctx.restore();

        // Draw info overlay
        this.drawInfoOverlay(w, h, gapUM, wireEdgePos, workpieceEdgePos, frontierRadius, frameData);
    }

    drawWire(wireX, wireRadius, frameData) {
        // Wire position in world space
        const wireCenterX = wireX * this.scale;
        const radiusPx = wireRadius * this.scale;

        // Wire body
        this.ctx.fillStyle = '#d79921'; // Gruvbox yellow/gold
        this.ctx.beginPath();
        this.ctx.arc(wireCenterX, 0, radiusPx, 0, Math.PI * 2);
        this.ctx.fill();

        // Wire outline
        this.ctx.strokeStyle = '#b57614';
        this.ctx.lineWidth = 1.5;
        this.ctx.stroke();

        // Temperature indication (if available)
        if (frameData.wire_average_temperature) {
            const tempC = frameData.wire_average_temperature - 273.15;
            const tempRatio = Math.min(tempC / 500, 1); // 0-500°C range

            // Heat glow
            if (tempRatio > 0.1) {
                const glowRadius = radiusPx * (1 + tempRatio * 0.5);
                const gradient = this.ctx.createRadialGradient(
                    wireCenterX, 0, radiusPx,
                    wireCenterX, 0, glowRadius
                );
                gradient.addColorStop(0, `rgba(255, 100, 0, 0)`);
                gradient.addColorStop(1, `rgba(255, 100, 0, ${tempRatio * 0.5})`);
                this.ctx.fillStyle = gradient;
                this.ctx.beginPath();
                this.ctx.arc(wireCenterX, 0, glowRadius, 0, Math.PI * 2);
                this.ctx.fill();
            }
        }
    }

    drawKerf(wireX, wireRadius, frontierCenterX, frontierRadius) {
        // Kerf region - removed shading, will be added later with debris
        // For now, just clean empty space between wire and frontier
    }

    drawWorkpiece(frontierCenterX, frontierRadius, wireCenterX, wireRadius) {
        const frontierCenterXPx = frontierCenterX * this.scale;
        const frontierRadiusPx = frontierRadius * this.scale;

        // Get canvas dimensions
        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;
        const maxDim = Math.max(w, h) * 2;

        const cutChannelHalfHeight = frontierRadiusPx;
        const blockThickness = maxDim;

        // === Draw water background in cut channel ===
        this.ctx.fillStyle = 'rgba(69, 133, 136, 0.35)'; // More visible blue (Gruvbox blue)
        this.ctx.fillRect(
            -maxDim,
            -cutChannelHalfHeight,
            frontierCenterXPx + maxDim + maxDim,
            cutChannelHalfHeight * 2
        );

        // === Draw simple rectangular workpiece block ===
        this.ctx.fillStyle = '#bdae93'; // Gruvbox gray workpiece

        // Top block (above cut channel)
        this.ctx.fillRect(
            -maxDim,
            cutChannelHalfHeight,
            frontierCenterXPx + maxDim + maxDim,
            blockThickness
        );

        // Bottom block (below cut channel)
        this.ctx.fillRect(
            -maxDim,
            -cutChannelHalfHeight - blockThickness,
            frontierCenterXPx + maxDim + maxDim,
            blockThickness
        );

        // === Draw frontier face (uncut semicircle) ===
        this.ctx.fillStyle = '#bdae93'; // Gruvbox gray
        this.ctx.beginPath();
        this.ctx.arc(frontierCenterXPx, 0, frontierRadiusPx, -Math.PI/2, Math.PI/2);
        this.ctx.lineTo(frontierCenterXPx + maxDim, frontierRadiusPx);
        this.ctx.lineTo(frontierCenterXPx + maxDim, -frontierRadiusPx);
        this.ctx.closePath();
        this.ctx.fill();

        // === Draw ALL cut edges with dark outlines ===
        this.ctx.strokeStyle = '#665c54'; // Gruvbox dark gray edges
        this.ctx.lineWidth = 2.5;

        // Top wall of cut channel (from far left to frontier)
        this.ctx.beginPath();
        this.ctx.moveTo(-maxDim, cutChannelHalfHeight);
        this.ctx.lineTo(frontierCenterXPx, cutChannelHalfHeight);
        this.ctx.stroke();

        // Bottom wall of cut channel (from far left to frontier)
        this.ctx.beginPath();
        this.ctx.moveTo(-maxDim, -cutChannelHalfHeight);
        this.ctx.lineTo(frontierCenterXPx, -cutChannelHalfHeight);
        this.ctx.stroke();

        // Frontier semicircular edge
        this.ctx.beginPath();
        this.ctx.arc(frontierCenterXPx, 0, frontierRadiusPx, -Math.PI/2, Math.PI/2);
        this.ctx.stroke();

        // === Texture lines on uncut workpiece ===
        this.ctx.strokeStyle = 'rgba(60, 56, 54, 0.15)'; // Subtle Gruvbox dark lines
        this.ctx.lineWidth = 0.5;
        const gridSpacing = 10 * this.scale;

        // Horizontal lines
        for (let y = cutChannelHalfHeight + gridSpacing; y < blockThickness; y += gridSpacing) {
            this.ctx.beginPath();
            this.ctx.moveTo(frontierCenterXPx, y);
            this.ctx.lineTo(frontierCenterXPx + maxDim, y);
            this.ctx.stroke();

            this.ctx.beginPath();
            this.ctx.moveTo(frontierCenterXPx, -y);
            this.ctx.lineTo(frontierCenterXPx + maxDim, -y);
            this.ctx.stroke();
        }
    }

    drawSpark(wireX, wireRadius, frontierCenterX, frontierRadius) {
        const wireCenterXPx = wireX * this.scale;
        const frontierCenterXPx = frontierCenterX * this.scale;
        const wireRadiusPx = wireRadius * this.scale;
        const frontierRadiusPx = frontierRadius * this.scale;

        // Calculate gap between surfaces
        const gapPx = (frontierCenterXPx + frontierRadiusPx) - (wireCenterXPx + wireRadiusPx);

        // Spark position (random point on wire surface facing workpiece)
        const angle = (Math.random() - 0.5) * Math.PI; // ±90° from center
        const sparkStartX = wireCenterXPx + wireRadiusPx * Math.cos(angle);
        const sparkStartY = wireRadiusPx * Math.sin(angle);

        const sparkEndX = frontierCenterXPx + frontierRadiusPx * Math.cos(angle);
        const sparkEndY = frontierRadiusPx * Math.sin(angle);

        // Spark flash glow
        const gradient = this.ctx.createRadialGradient(
            sparkStartX, sparkStartY, 0,
            sparkStartX, sparkStartY, Math.abs(gapPx) * 1.5
        );
        gradient.addColorStop(0, 'rgba(184, 187, 38, 0.8)'); // Gruvbox yellow bright
        gradient.addColorStop(0.3, 'rgba(215, 153, 33, 0.4)'); // Gruvbox yellow/orange
        gradient.addColorStop(1, 'rgba(215, 153, 33, 0)');

        this.ctx.fillStyle = gradient;
        this.ctx.beginPath();
        this.ctx.arc(sparkStartX, sparkStartY, Math.abs(gapPx) * 1.5, 0, Math.PI * 2);
        this.ctx.fill();

        // Spark arc/lightning
        this.ctx.strokeStyle = '#fabd2f'; // Gruvbox bright yellow
        this.ctx.lineWidth = 2;
        this.ctx.shadowBlur = 10;
        this.ctx.shadowColor = '#d79921'; // Gruvbox yellow glow

        this.ctx.beginPath();
        this.ctx.moveTo(sparkStartX, sparkStartY);

        // Jagged line
        const steps = 3;
        for (let i = 1; i <= steps; i++) {
            const t = i / steps;
            const x = sparkStartX + (sparkEndX - sparkStartX) * t;
            const y = sparkStartY + (sparkEndY - sparkStartY) * t;
            const jitter = (Math.random() - 0.5) * Math.abs(gapPx) * 0.3;
            this.ctx.lineTo(x + jitter, y + jitter * 0.5);
        }
        this.ctx.lineTo(sparkEndX, sparkEndY);
        this.ctx.stroke();

        this.ctx.shadowBlur = 0;
    }

    drawInfoOverlay(w, h, gap, wirePos, workpiecePos, frontierRadius, frameData) {
        // Info box (top-left)
        const padding = 10;
        const lineHeight = 16;
        let y = padding;

        this.drawText('TOP VIEW', padding, y, { color: '#427b58', font: 'bold 11px sans-serif' });
        y += lineHeight;

        this.drawText(`Wire Pos: ${wirePos.toFixed(1)} µm`, padding, y, { color: '#d79921', font: '11px monospace' });
        y += lineHeight;

        this.drawText(`WP Pos: ${workpiecePos.toFixed(1)} µm`, padding, y, { color: '#7c6f64', font: '11px monospace' });
        y += lineHeight;

        this.drawText(`Gap: ${gap.toFixed(1)} µm`, padding, y, { color: '#076678', font: '11px monospace' });
        y += lineHeight;

        this.drawText(`Wire Ø: ${this.wireDiameter.toFixed(3)} mm`, padding, y, { color: '#7c6f64', font: '11px monospace' });
        y += lineHeight;

        this.drawText(`Frontier R: ${frontierRadius.toFixed(3)} mm`, padding, y, { color: '#7c6f64', font: '11px monospace' });
        y += lineHeight;

        // Zoom level indicator
        this.drawText(`Zoom: ${this.zoomLevel.toFixed(1)}x`, padding, y, { color: '#427b58', font: '11px monospace' });
        y += lineHeight;

        if (frameData.debris_density !== undefined) {
            const debrisPercent = (frameData.debris_density * 100).toFixed(1);
            this.drawText(`Debris: ${debrisPercent}%`, padding, y, { color: '#d65d0e', font: '11px monospace' });
            y += lineHeight;
        }

        if (frameData.spark_status && frameData.spark_status[0] === 1) {
            this.drawText('⚡ SPARK', padding, y, { color: '#8f3f71', font: 'bold 11px sans-serif' });
        } else if (frameData.spark_status && frameData.spark_status[0] === -1) {
            this.drawText('⚠ SHORT', padding, y, { color: '#9d0006', font: 'bold 11px sans-serif' });
        }

        // Scale reference (bottom-right) - dynamic based on zoom
        // Choose scale bar size based on zoom level
        let scaleBarLength, scaleBarLabel;
        if (this.zoomLevel < 2.0) {
            // Zoomed out: use 1mm scale
            scaleBarLength = 1.0; // mm
            scaleBarLabel = '1 mm';
        } else {
            // Zoomed in: use 100µm scale
            scaleBarLength = 0.1; // mm
            scaleBarLabel = '100 µm';
        }

        const scaleBarLengthPx = scaleBarLength * this.scale;
        const scaleBarX = w - padding - scaleBarLengthPx;
        const scaleBarY = h - padding - 20;

        this.ctx.strokeStyle = '#665c54';
        this.ctx.lineWidth = 2;
        this.ctx.beginPath();
        this.ctx.moveTo(scaleBarX, scaleBarY);
        this.ctx.lineTo(scaleBarX + scaleBarLengthPx, scaleBarY);
        this.ctx.stroke();

        // Scale ticks
        this.ctx.beginPath();
        this.ctx.moveTo(scaleBarX, scaleBarY - 3);
        this.ctx.lineTo(scaleBarX, scaleBarY + 3);
        this.ctx.moveTo(scaleBarX + scaleBarLengthPx, scaleBarY - 3);
        this.ctx.lineTo(scaleBarX + scaleBarLengthPx, scaleBarY + 3);
        this.ctx.stroke();

        this.drawText(scaleBarLabel, scaleBarX + scaleBarLengthPx / 2, scaleBarY + 10, {
            color: '#665c54',
            font: '10px sans-serif',
            align: 'center'
        });

        // Control hints (bottom-left)
        const hintsY = h - padding - 30;
        this.drawText('🖱️ Scroll: Zoom | Drag: Pan | Double-click: Reset', padding, hintsY, {
            color: '#7c6f64',
            font: '9px sans-serif'
        });

        // Auto-pan indicator
        if (!this.autoPan) {
            this.drawText('Manual Mode', padding, hintsY + 12, {
                color: '#d65d0e',
                font: 'bold 9px sans-serif'
            });
        }
    }
}

// ============================================================================
// Panel 4: Thermal Profile (Wire temperature heatmap)
// ============================================================================

class ThermalProfilePanel extends BasePanel {
    draw(frameData, frameIndex) {
        this.clear();

        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;

        this.ctx.fillStyle = '#fbf1c7';
        this.ctx.fillRect(0, 0, w, h);

        // Draw placeholder
        this.drawText('Thermal Profile', w/2, h/2, {
            color: '#9d0006',
            font: 'bold 16px sans-serif',
            align: 'center',
            baseline: 'middle'
        });

        if (frameData && frameData.wire_average_temperature !== undefined) {
            const tempC = frameData.wire_average_temperature - 273.15;
            this.drawText(`Avg Temp: ${tempC.toFixed(1)}°C`, 10, 10, { color: '#9d0006' });
        }
    }
}

// ============================================================================
// Initialize Dashboard
// ============================================================================

let dashboard;
window.addEventListener('DOMContentLoaded', () => {
    dashboard = new DashboardController();
});
