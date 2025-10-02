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
    draw(frameData, frameIndex) {
        this.clear();

        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;

        // Example rendering - replace with actual data visualization
        this.ctx.fillStyle = '#1a1a1a';
        this.ctx.fillRect(0, 0, w, h);

        // Draw placeholder
        this.drawText('Side View', w/2, h/2, {
            color: '#00ff88',
            font: 'bold 16px sans-serif',
            align: 'center',
            baseline: 'middle'
        });

        if (frameData) {
            this.drawText(`Frame: ${frameIndex}`, 10, 10, { color: '#888' });
            this.drawText(`Time: ${(frameData.time / 1000).toFixed(3)} ms`, 10, 25, { color: '#888' });
        }
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

        this.ctx.fillStyle = '#0a0a0a';
        this.ctx.fillRect(0, 0, w, h);

        // Draw grid
        this.drawGrid(w, h);

        // Draw placeholder
        this.drawText('Oscilloscope', w/2, h/2, {
            color: '#00ff88',
            font: 'bold 16px sans-serif',
            align: 'center',
            baseline: 'middle'
        });

        if (frameData && frameData.voltage !== undefined) {
            this.drawText(`Voltage: ${frameData.voltage.toFixed(1)} V`, 10, 10, { color: '#00ddff' });
        }
        if (frameData && frameData.current !== undefined) {
            this.drawText(`Current: ${frameData.current.toFixed(2)} A`, 10, 25, { color: '#ff8800' });
        }
    }

    drawGrid(w, h) {
        this.ctx.strokeStyle = '#2a2a2a';
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
        this.centerX = 0;
        this.centerY = 0;
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

        // Background
        this.ctx.fillStyle = '#0a0a0a';
        this.ctx.fillRect(0, 0, w, h);

        // Setup coordinate system
        this.centerX = w / 2;
        this.centerY = h / 2;

        // Auto-scale to fit nicely (show ~2x kerf width)
        const kerfWidth = this.wireDiameter + (this.initialGap * 2 / 1000); // Convert µm to mm
        const viewWidth = kerfWidth * 4; // Show 4x the kerf width
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

        // Calculate current gap and positions
        const wirePos = frameData.wire_position || 0; // µm
        const workpiecePos = frameData.workpiece_position || 0; // µm
        const gap = workpiecePos - wirePos; // µm

        // Convert to mm for drawing
        const gapMM = gap / 1000;
        const wireRadius = this.wireDiameter / 2;
        const workpieceOffset = gapMM + wireRadius; // Distance from wire center to workpiece edge

        // Save context
        this.ctx.save();
        this.ctx.translate(this.centerX, this.centerY);

        // Draw workpiece (right side, with semicircular frontier)
        this.drawWorkpiece(workpieceOffset);

        // Draw kerf (gap region)
        this.drawKerf(wireRadius, workpieceOffset);

        // Draw wire (center)
        this.drawWire(wireRadius, frameData);

        // Draw spark if active
        if (frameData.spark_status && frameData.spark_status[0] === 1) {
            this.drawSpark(wireRadius, workpieceOffset);
        }

        // Restore context
        this.ctx.restore();

        // Draw info overlay
        this.drawInfoOverlay(w, h, gap, frameData);
    }

    drawWire(wireRadius, frameData) {
        // Wire is at center (x=0)
        const radiusPx = wireRadius * this.scale;

        // Wire body
        this.ctx.fillStyle = '#ffcc00'; // Gold/brass color
        this.ctx.beginPath();
        this.ctx.arc(0, 0, radiusPx, 0, Math.PI * 2);
        this.ctx.fill();

        // Wire outline
        this.ctx.strokeStyle = '#ffaa00';
        this.ctx.lineWidth = 1.5;
        this.ctx.stroke();

        // Temperature indication (if available)
        if (frameData.wire_average_temperature) {
            const tempC = frameData.wire_average_temperature - 273.15;
            const tempRatio = Math.min(tempC / 500, 1); // 0-500°C range

            // Heat glow
            if (tempRatio > 0.1) {
                const glowRadius = radiusPx * (1 + tempRatio * 0.5);
                const gradient = this.ctx.createRadialGradient(0, 0, radiusPx, 0, 0, glowRadius);
                gradient.addColorStop(0, `rgba(255, 100, 0, 0)`);
                gradient.addColorStop(1, `rgba(255, 100, 0, ${tempRatio * 0.5})`);
                this.ctx.fillStyle = gradient;
                this.ctx.beginPath();
                this.ctx.arc(0, 0, glowRadius, 0, Math.PI * 2);
                this.ctx.fill();
            }
        }

        // Center dot
        this.ctx.fillStyle = '#ffffff';
        this.ctx.beginPath();
        this.ctx.arc(0, 0, 1.5, 0, Math.PI * 2);
        this.ctx.fill();
    }

    drawKerf(wireRadius, workpieceOffset) {
        // Kerf is the gap between wire and workpiece
        const wireRadiusPx = wireRadius * this.scale;
        const workpieceOffsetPx = workpieceOffset * this.scale;

        // Draw kerf region (semi-transparent)
        this.ctx.fillStyle = 'rgba(100, 150, 200, 0.2)';
        this.ctx.beginPath();
        this.ctx.arc(0, 0, workpieceOffsetPx, -Math.PI/2, Math.PI/2);
        this.ctx.arc(0, 0, wireRadiusPx, Math.PI/2, -Math.PI/2, true);
        this.ctx.closePath();
        this.ctx.fill();

        // Kerf boundary lines
        this.ctx.strokeStyle = 'rgba(100, 150, 200, 0.5)';
        this.ctx.lineWidth = 1;
        this.ctx.setLineDash([3, 3]);

        // Inner boundary (wire edge)
        this.ctx.beginPath();
        this.ctx.arc(0, 0, wireRadiusPx, -Math.PI/2, Math.PI/2);
        this.ctx.stroke();

        // Outer boundary (workpiece edge)
        this.ctx.beginPath();
        this.ctx.arc(0, 0, workpieceOffsetPx, -Math.PI/2, Math.PI/2);
        this.ctx.stroke();

        this.ctx.setLineDash([]);
    }

    drawWorkpiece(workpieceOffset) {
        const workpieceOffsetPx = workpieceOffset * this.scale;

        // Get canvas dimensions
        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;
        const maxDim = Math.max(w, h);

        // Workpiece material (fills right side)
        this.ctx.fillStyle = '#2a4a5a'; // Dark steel blue
        this.ctx.beginPath();

        // Semicircular frontier (left edge of workpiece)
        this.ctx.arc(0, 0, workpieceOffsetPx, -Math.PI/2, Math.PI/2);

        // Rectangle extending to the right
        this.ctx.lineTo(maxDim, workpieceOffsetPx);
        this.ctx.lineTo(maxDim, -workpieceOffsetPx);
        this.ctx.closePath();
        this.ctx.fill();

        // Workpiece edge highlight
        this.ctx.strokeStyle = '#4a7a8a';
        this.ctx.lineWidth = 2;
        this.ctx.beginPath();
        this.ctx.arc(0, 0, workpieceOffsetPx, -Math.PI/2, Math.PI/2);
        this.ctx.stroke();

        // Workpiece texture (optional grid lines)
        this.ctx.strokeStyle = 'rgba(74, 122, 138, 0.2)';
        this.ctx.lineWidth = 0.5;
        const gridSpacing = 10 * this.scale; // 10mm grid

        for (let x = workpieceOffsetPx; x < maxDim; x += gridSpacing) {
            this.ctx.beginPath();
            this.ctx.moveTo(x, -maxDim);
            this.ctx.lineTo(x, maxDim);
            this.ctx.stroke();
        }
    }

    drawSpark(wireRadius, workpieceOffset) {
        const wireRadiusPx = wireRadius * this.scale;
        const workpieceOffsetPx = workpieceOffset * this.scale;
        const gapPx = workpieceOffsetPx - wireRadiusPx;

        // Spark position (random point on wire surface facing workpiece)
        const angle = (Math.random() - 0.5) * Math.PI; // ±90° from center
        const sparkStartX = wireRadiusPx * Math.cos(angle);
        const sparkStartY = wireRadiusPx * Math.sin(angle);

        const sparkEndX = workpieceOffsetPx * Math.cos(angle);
        const sparkEndY = workpieceOffsetPx * Math.sin(angle);

        // Spark flash glow
        const gradient = this.ctx.createRadialGradient(
            sparkStartX, sparkStartY, 0,
            sparkStartX, sparkStartY, gapPx * 1.5
        );
        gradient.addColorStop(0, 'rgba(255, 255, 255, 0.8)');
        gradient.addColorStop(0.3, 'rgba(150, 200, 255, 0.4)');
        gradient.addColorStop(1, 'rgba(150, 200, 255, 0)');

        this.ctx.fillStyle = gradient;
        this.ctx.beginPath();
        this.ctx.arc(sparkStartX, sparkStartY, gapPx * 1.5, 0, Math.PI * 2);
        this.ctx.fill();

        // Spark arc/lightning
        this.ctx.strokeStyle = '#ffffff';
        this.ctx.lineWidth = 2;
        this.ctx.shadowBlur = 10;
        this.ctx.shadowColor = '#aaddff';

        this.ctx.beginPath();
        this.ctx.moveTo(sparkStartX, sparkStartY);

        // Jagged line
        const steps = 3;
        for (let i = 1; i <= steps; i++) {
            const t = i / steps;
            const x = sparkStartX + (sparkEndX - sparkStartX) * t;
            const y = sparkStartY + (sparkEndY - sparkStartY) * t;
            const jitter = (Math.random() - 0.5) * gapPx * 0.3;
            this.ctx.lineTo(x + jitter, y + jitter * 0.5);
        }
        this.ctx.lineTo(sparkEndX, sparkEndY);
        this.ctx.stroke();

        this.ctx.shadowBlur = 0;
    }

    drawInfoOverlay(w, h, gap, frameData) {
        // Info box (top-left)
        const padding = 10;
        const lineHeight = 16;
        let y = padding;

        this.drawText('TOP VIEW', padding, y, { color: '#00ff88', font: 'bold 11px sans-serif' });
        y += lineHeight;

        this.drawText(`Gap: ${gap.toFixed(1)} µm`, padding, y, { color: '#aaddff', font: '11px monospace' });
        y += lineHeight;

        this.drawText(`Wire Ø: ${this.wireDiameter.toFixed(3)} mm`, padding, y, { color: '#ffcc00', font: '11px monospace' });
        y += lineHeight;

        if (frameData.debris_density !== undefined) {
            const debrisPercent = (frameData.debris_density * 100).toFixed(1);
            this.drawText(`Debris: ${debrisPercent}%`, padding, y, { color: '#ff8800', font: '11px monospace' });
            y += lineHeight;
        }

        if (frameData.spark_status && frameData.spark_status[0] === 1) {
            this.drawText('⚡ SPARK', padding, y, { color: '#ffffff', font: 'bold 11px sans-serif' });
        } else if (frameData.spark_status && frameData.spark_status[0] === -1) {
            this.drawText('⚠ SHORT', padding, y, { color: '#ff4400', font: 'bold 11px sans-serif' });
        }

        // Scale reference (bottom-right)
        const scaleBarLength = 1.0; // 1mm reference
        const scaleBarLengthPx = scaleBarLength * this.scale;
        const scaleBarX = w - padding - scaleBarLengthPx;
        const scaleBarY = h - padding - 20;

        this.ctx.strokeStyle = '#ffffff';
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

        this.drawText('1 mm', scaleBarX + scaleBarLengthPx / 2, scaleBarY + 10, {
            color: '#ffffff',
            font: '10px sans-serif',
            align: 'center'
        });
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

        this.ctx.fillStyle = '#1a1a1a';
        this.ctx.fillRect(0, 0, w, h);

        // Draw placeholder
        this.drawText('Thermal Profile', w/2, h/2, {
            color: '#00ff88',
            font: 'bold 16px sans-serif',
            align: 'center',
            baseline: 'middle'
        });

        if (frameData && frameData.wire_average_temperature !== undefined) {
            const tempC = frameData.wire_average_temperature - 273.15;
            this.drawText(`Avg Temp: ${tempC.toFixed(1)}°C`, 10, 10, { color: '#ff4400' });
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
