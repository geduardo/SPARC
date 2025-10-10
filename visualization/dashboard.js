// ============================================================================
// SPARC Visualization Dashboard - Main Controller
// ============================================================================

class DashboardController {
    constructor() {
        this.data = null;
        this.currentFrame = 0;
        this.isPlaying = false;
        this.animationId = null;
        this.playbackSpeed = 60; // microseconds per second (default 60 µs/s)
        this.lastFrameTime = 0; // For timing playback
        this.viewsLinked = true; // Link/unlink top and side views

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
            prevFrame: document.getElementById('prevFrame'),
            nextFrame: document.getElementById('nextFrame'),
            timeline: document.getElementById('timeline'),
            frameCounter: document.getElementById('frameCounter'),
            timeDisplay: document.getElementById('timeDisplay'),
            loadingOverlay: document.getElementById('loadingOverlay'),
            speedControl: document.getElementById('speedControl'),
            timebaseControl: document.getElementById('timebaseControl'),
            linkViews: document.getElementById('linkViews'),
            toggleSideViewSparks: document.getElementById('toggleSideViewSparks'),
            toggleTopViewSparks: document.getElementById('toggleTopViewSparks'),
            toggleOscilloscope: document.getElementById('toggleOscilloscope'),
            triggerEnable: document.getElementById('triggerEnable'),
            triggerSource: document.getElementById('triggerSource'),
            triggerSlope: document.getElementById('triggerSlope'),
            triggerLevel: document.getElementById('triggerLevel'),
            triggerDelay: document.getElementById('triggerDelay'),
            voltageOffset: document.getElementById('voltageOffset'),
            currentOffset: document.getElementById('currentOffset'),
            vPerDiv: document.getElementById('vPerDiv'),
            iPerDiv: document.getElementById('iPerDiv')
        };

        // Setup event listeners
        this.elements.loadData.addEventListener('click', () => this.elements.fileInput.click());
        this.elements.fileInput.addEventListener('change', (e) => this.loadDataFile(e));
        this.elements.playPause.addEventListener('click', () => this.togglePlayPause());
        this.elements.reset.addEventListener('click', () => this.resetTimeline());
        this.elements.prevFrame.addEventListener('click', () => this.previousFrame());
        this.elements.nextFrame.addEventListener('click', () => this.nextFrame());
        this.elements.timeline.addEventListener('input', (e) => this.seekTo(parseInt(e.target.value)));
        this.elements.speedControl.addEventListener('change', (e) => this.setPlaybackSpeed(parseInt(e.target.value)));
        if (this.elements.timebaseControl) {
            this.elements.timebaseControl.addEventListener('change', (e) => this.setTimebase(e.target.value));
        }
        this.elements.linkViews.addEventListener('click', () => this.toggleViewsLink());
        this.elements.toggleSideViewSparks.addEventListener('click', () => this.toggleSideViewSparks());
        this.elements.toggleTopViewSparks.addEventListener('click', () => this.toggleTopViewSparks());
        this.elements.toggleOscilloscope.addEventListener('click', () => this.toggleOscilloscope());
        if (this.elements.triggerEnable) {
            const onTriggerChange = () => this.setTriggerConfig({
                enabled: !!this.elements.triggerEnable.checked,
                source: this.elements.triggerSource.value,
                slope: this.elements.triggerSlope.value,
                level: parseFloat(this.elements.triggerLevel.value),
                delayUs: this.elements.triggerDelay ? parseFloat(this.elements.triggerDelay.value || '0') : 0
            });
            this.elements.triggerEnable.addEventListener('change', onTriggerChange);
            this.elements.triggerSource.addEventListener('change', onTriggerChange);
            this.elements.triggerSlope.addEventListener('change', onTriggerChange);
            this.elements.triggerLevel.addEventListener('change', onTriggerChange);
            if (this.elements.triggerDelay) {
                this.elements.triggerDelay.addEventListener('change', onTriggerChange);
                this.elements.triggerDelay.addEventListener('input', onTriggerChange);
            }
        }

        // Offsets controls
        const onOffsetsChange = () => {
            const vOff = this.elements.voltageOffset ? parseFloat(this.elements.voltageOffset.value || '0') : 0;
            const iOff = this.elements.currentOffset ? parseFloat(this.elements.currentOffset.value || '0') : 0;
            if (this.panels && this.panels.oscilloscope && this.panels.oscilloscope.setOffsets) {
                this.panels.oscilloscope.setOffsets(vOff, iOff);
            }
            if (this.data) {
                this.drawFrame(this.currentFrame);
            }
        };
        if (this.elements.voltageOffset) {
            this.elements.voltageOffset.addEventListener('change', onOffsetsChange);
            this.elements.voltageOffset.addEventListener('input', onOffsetsChange);
        }
        if (this.elements.currentOffset) {
            this.elements.currentOffset.addEventListener('change', onOffsetsChange);
            this.elements.currentOffset.addEventListener('input', onOffsetsChange);
        }

        // Per-channel scale controls
        const onScaleChange = () => {
            const vpd = this.elements.vPerDiv ? this.elements.vPerDiv.value : 'auto';
            const ipd = this.elements.iPerDiv ? this.elements.iPerDiv.value : 'auto';
            if (this.panels && this.panels.oscilloscope && this.panels.oscilloscope.setVerticalScales) {
                this.panels.oscilloscope.setVerticalScales(vpd, ipd);
            }
            if (this.data) this.drawFrame(this.currentFrame);
        };
        if (this.elements.vPerDiv) {
            this.elements.vPerDiv.addEventListener('change', onScaleChange);
        }
        if (this.elements.iPerDiv) {
            this.elements.iPerDiv.addEventListener('change', onScaleChange);
        }

        // Initialize panels
        this.initializePanels();

        // Handle window resize
        window.addEventListener('resize', () => this.handleResize());

        // Setup keyboard controls
        this.setupKeyboardControls();

        console.log('Dashboard initialized. Load a simulation data file to begin.');
    }

    setupKeyboardControls() {
        window.addEventListener('keydown', (e) => {
            console.log('Key pressed:', e.key, 'Data loaded:', !!this.data);
            
            if (!this.data) return;

            // Arrow right: next frame
            if (e.key === 'ArrowRight') {
                e.preventDefault();
                console.log('Arrow Right - calling nextFrame()');
                this.nextFrame();
            }
            // Arrow left: previous frame
            else if (e.key === 'ArrowLeft') {
                e.preventDefault();
                console.log('Arrow Left - calling previousFrame()');
                this.previousFrame();
            }
        });
    }

    initializePanels() {
        // Create panel instances
        this.panels.sideView = new SideViewPanel('sideViewCanvas');
        this.panels.oscilloscope = new OscilloscopePanel('oscilloscopeCanvas');
        this.panels.topView = new TopViewPanel('topViewCanvas');
        this.panels.thermal = new ThermalProfilePanel('thermalCanvas');

        // Set up shared camera between TopView and SideView
        this.panels.sideView.sharedCamera = this.panels.topView;

        // Pass controller reference to panels for triggering redraws
        Object.values(this.panels).forEach(panel => {
            panel.controller = this;
            panel.init();
        });

        // Initialize oscilloscope timebase (defaults to Auto)
        if (this.elements.timebaseControl) {
            this.setTimebase(this.elements.timebaseControl.value || 'auto');
        }
        // Initialize trigger config defaults
        this.setTriggerConfig({
            enabled: this.elements.triggerEnable ? !!this.elements.triggerEnable.checked : false,
            source: this.elements.triggerSource ? this.elements.triggerSource.value : 'ch1',
            slope: this.elements.triggerSlope ? this.elements.triggerSlope.value : 'rising',
            level: this.elements.triggerLevel ? parseFloat(this.elements.triggerLevel.value) : 50,
            delayUs: this.elements.triggerDelay ? parseFloat(this.elements.triggerDelay.value || '0') : 0
        });
        // Initialize offsets defaults
        if (this.panels && this.panels.oscilloscope && this.panels.oscilloscope.setOffsets) {
            const vOff = this.elements.voltageOffset ? parseFloat(this.elements.voltageOffset.value || '0') : 0;
            const iOff = this.elements.currentOffset ? parseFloat(this.elements.currentOffset.value || '0') : 0;
            this.panels.oscilloscope.setOffsets(vOff, iOff);
        }
        // Initialize vertical scales defaults
        if (this.panels && this.panels.oscilloscope && this.panels.oscilloscope.setVerticalScales) {
            const vpd = this.elements.vPerDiv ? this.elements.vPerDiv.value : 'auto';
            const ipd = this.elements.iPerDiv ? this.elements.iPerDiv.value : 'auto';
            this.panels.oscilloscope.setVerticalScales(vpd, ipd);
        }
    }

    toggleViewsLink() {
        this.viewsLinked = !this.viewsLinked;
        this.elements.linkViews.textContent = this.viewsLinked ? '🔗 Linked Views' : '🔓 Unlinked Views';

        if (!this.viewsLinked) {
            // When unlinking, give each view its own independent camera
            this.panels.sideView.useIndependentCamera = true;
            this.panels.sideView.independentZoomLevel = this.panels.topView.zoomLevel;
            this.panels.sideView.independentCameraX = this.panels.topView.cameraX;
        } else {
            // When linking, revert to shared camera
            this.panels.sideView.useIndependentCamera = false;
        }

        // Redraw current frame
        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
    }

    toggleSideViewSparks() {
        this.panels.sideView.showSparks = !this.panels.sideView.showSparks;
        this.elements.toggleSideViewSparks.textContent = this.panels.sideView.showSparks ? '⚡ Sparks ON' : '⚡ Sparks OFF';
        this.elements.toggleSideViewSparks.style.background = this.panels.sideView.showSparks ? '#8ec07c' : '#d65d0e';

        // Redraw current frame
        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
    }

    toggleTopViewSparks() {
        this.panels.topView.showSparks = !this.panels.topView.showSparks;
        this.elements.toggleTopViewSparks.textContent = this.panels.topView.showSparks ? '⚡ Sparks ON' : '⚡ Sparks OFF';
        this.elements.toggleTopViewSparks.style.background = this.panels.topView.showSparks ? '#8ec07c' : '#d65d0e';

        // Redraw current frame
        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
    }

    toggleOscilloscope() {
        this.panels.oscilloscope.isEnabled = !this.panels.oscilloscope.isEnabled;
        this.elements.toggleOscilloscope.textContent = this.panels.oscilloscope.isEnabled ? '⏻ ON ' : '⏻ OFF';
        this.elements.toggleOscilloscope.style.background = this.panels.oscilloscope.isEnabled ? '#8ec07c' : '#cc0000';

        // Redraw current frame
        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
    }

    async loadDataFile(event) {
        const file = event.target.files[0];
        if (!file) return;

        this.showLoading(true);
        console.log(`Loading file: ${file.name} (${(file.size / (1024*1024)).toFixed(2)} MB)`);

        try {
            // For large files, use FileReader with better error handling
            const text = await this.readLargeFile(file);
            console.log(`File read complete, parsing JSON... (${(text.length / (1024*1024)).toFixed(2)} MB)`);

            // Check if file is too large (> 500MB of text)
            if (text.length > 500 * 1024 * 1024) {
                const proceed = confirm(
                    `Warning: This file is very large (${(text.length / (1024*1024)).toFixed(0)} MB). ` +
                    `Loading it may crash your browser. Continue anyway?`
                );
                if (!proceed) {
                    throw new Error('Load cancelled by user');
                }
            }

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

    readLargeFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();

            reader.onload = (e) => {
                resolve(e.target.result);
            };

            reader.onerror = (e) => {
                reject(new Error(`File read error: ${e.target.error.message || 'Unknown error'}`));
            };

            reader.onprogress = (e) => {
                if (e.lengthComputable) {
                    const percent = ((e.loaded / e.total) * 100).toFixed(1);
                    console.log(`Reading file: ${percent}% (${(e.loaded / (1024*1024)).toFixed(2)} MB / ${(e.total / (1024*1024)).toFixed(2)} MB)`);
                }
            };

            // Read as text with UTF-8 encoding
            reader.readAsText(file, 'UTF-8');
        });
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
        this.lastFrameTime = performance.now();

        const animate = (currentTime) => {
            if (!this.isPlaying) return;

            const deltaTime = currentTime - this.lastFrameTime; // milliseconds elapsed
            this.lastFrameTime = currentTime;

            // Calculate how many frames to advance based on playback speed
            // playbackSpeed is in µs/s (microseconds per second)
            // Each frame represents 1 µs of simulation time
            // deltaTime is in milliseconds (real time)
            const framesToAdvance = Math.round((deltaTime / 1000) * this.playbackSpeed);

            if (framesToAdvance > 0) {
                const oldFrame = this.currentFrame;
                this.currentFrame += framesToAdvance;

                if (this.currentFrame >= this.data.time.length) {
                    this.currentFrame = 0; // Loop
                }

                // Draw frame with accumulated sparks from skipped frames
                this.drawFrameWithAccumulatedSparks(oldFrame, this.currentFrame);
                this.updateTimeDisplay();
                this.elements.timeline.value = this.currentFrame;
            }

            // Request next frame (60 FPS max)
            this.animationId = requestAnimationFrame(animate);
        };

        this.animationId = requestAnimationFrame(animate);
    }

    setPlaybackSpeed(speed) {
        this.playbackSpeed = speed;
        console.log(`Playback speed set to ${speed} µs/s`);
        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
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

    previousFrame() {
        if (!this.data) return;
        // Calculate frame step based on playback speed (at 60 FPS, how many frames we'd advance per render frame)
        const frameStep = Math.max(1, Math.round(this.playbackSpeed / 60));
        const prevFrame = Math.max(this.currentFrame - frameStep, 0);
        console.log('Previous frame:', this.currentFrame, '->', prevFrame, `(step: ${frameStep})`);
        this.seekToWithAccumulation(prevFrame);
    }

    nextFrame() {
        if (!this.data) return;
        // Calculate frame step based on playback speed (at 60 FPS, how many frames we'd advance per render frame)
        const frameStep = Math.max(1, Math.round(this.playbackSpeed / 60));
        const nextFrame = Math.min(this.currentFrame + frameStep, this.data.time.length - 1);
        console.log('Next frame:', this.currentFrame, '->', nextFrame, `(step: ${frameStep})`);
        this.seekToWithAccumulation(nextFrame);
    }

    seekTo(frame) {
        if (!this.data) return;

        this.currentFrame = Math.max(0, Math.min(frame, this.data.time.length - 1));
        this.elements.timeline.value = this.currentFrame;
        this.drawFrame(this.currentFrame);
        this.updateTimeDisplay();
    }

    seekToWithAccumulation(targetFrame) {
        if (!this.data) return;

        const oldFrame = this.currentFrame;
        this.currentFrame = Math.max(0, Math.min(targetFrame, this.data.time.length - 1));
        this.elements.timeline.value = this.currentFrame;

        // If moving forward, accumulate sparks; otherwise just draw the frame
        if (this.currentFrame > oldFrame) {
            this.drawFrameWithAccumulatedSparks(oldFrame, this.currentFrame);
        } else {
            this.drawFrame(this.currentFrame);
        }

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

    drawFrameWithAccumulatedSparks(startFrame, endFrame) {
        if (!this.data) return;

        // Collect all sparks that occurred between startFrame and endFrame
        const accumulatedSparks = [];

        for (let f = startFrame + 1; f <= endFrame; f++) {
            const frameData = this.getFrameData(f);
            if (frameData.spark_status && frameData.spark_status[0] === 1 && frameData.spark_status[1] !== null) {
                accumulatedSparks.push({
                    locationMM: frameData.spark_status[1],
                    frameIndex: f
                });
            }
        }

        // Get the final frame data
        const finalFrameData = this.getFrameData(endFrame);

        // Add accumulated sparks to frame data
        finalFrameData.accumulatedSparks = accumulatedSparks;

        // Update all panels with accumulated sparks
        Object.values(this.panels).forEach(panel => {
            panel.draw(finalFrameData, endFrame);
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

        // Update frame counter
        this.elements.frameCounter.textContent = 
            `Frame: ${this.currentFrame + 1} / ${this.data.time.length}`;

        // Update time display
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

    // Timebase handling for oscilloscope
    setTimebase(value) {
        const mode = value === 'auto' ? 'auto' : 'manual';
        const usPerDiv = value === 'auto' ? null : parseInt(value);
        if (this.panels && this.panels.oscilloscope && this.panels.oscilloscope.setTimebase) {
            this.panels.oscilloscope.setTimebase(mode, usPerDiv);
        }
        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
    }

    // Trigger config handling
    setTriggerConfig(cfg) {
        this.triggerConfig = cfg;
        if (this.panels && this.panels.oscilloscope && this.panels.oscilloscope.setTrigger) {
            this.panels.oscilloscope.setTrigger(cfg);
        }
        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
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
        // For oscilloscope, also draw initial state to set up alignment
        if (this.constructor.name === 'OscilloscopePanel') {
            this.draw(null, 0);
        }
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

        // Independent camera for unlinked mode
        this.useIndependentCamera = false;
        this.independentZoomLevel = 3.0;
        this.independentCameraX = 0; // mm

        // Vertical camera offset (independent from TopView)
        this.cameraY = 0; // mm

        // Mouse interaction state
        this.isDragging = false;
        this.lastMouseX = 0;
        this.lastMouseY = 0;

        // Spark persistence tracking
        this.activeSparks = []; // Array of {locationMM, startFrame, intensity}
        this.baseSparkPersistenceFrames = 10; // Base number of frames sparks remain visible
        this.lastFrameIndex = -1; // Track frame changes for detecting backward seeks

        // Spark visibility toggle
        this.showSparks = true;

        // Setup controls
        this.setupControls();
    }

    setData(data) {
        super.setData(data);

        // Extract metadata if available
        if (data && data.metadata) {
            if (data.metadata.wire_diameter !== undefined) {
                this.wireDiameter = data.metadata.wire_diameter;
            }
            if (data.metadata.initial_gap !== undefined) {
                this.initialGap = data.metadata.initial_gap;
            }
            // Workpiece height/thickness in mm (directly from env_config)
            if (data.metadata.workpiece_height_mm !== undefined) {
                this.workpieceThickness = data.metadata.workpiece_height_mm;
            } else if (data.metadata.workpiece_height !== undefined) {
                this.workpieceThickness = data.metadata.workpiece_height;
            }
        }
        
        console.log('SideViewPanel setData - workpieceThickness:', this.workpieceThickness, 'mm');
    }

    setupControls() {
        // Mouse wheel for zoom (when in independent mode)
        this.canvas.addEventListener('wheel', (e) => {
            if (!this.useIndependentCamera) return;

            e.preventDefault();
            const zoomDelta = e.deltaY > 0 ? 1.2 : 0.8;
            this.independentZoomLevel *= zoomDelta;
            this.independentZoomLevel = Math.max(0.5, Math.min(100, this.independentZoomLevel));

            // Trigger redraw
            if (this.controller && this.controller.data) {
                this.controller.drawFrame(this.controller.currentFrame);
            }
        });

        // Mouse drag for pan
        this.canvas.addEventListener('mousedown', (e) => {
            this.isDragging = true;
            this.lastMouseX = e.offsetX;
            this.lastMouseY = e.offsetY;
            this.canvas.style.cursor = 'grabbing';
        });

        this.canvas.addEventListener('mousemove', (e) => {
            if (this.isDragging) {
                const dx = e.offsetX - this.lastMouseX;
                const dy = e.offsetY - this.lastMouseY;

                // Get scale
                const zoomLevel = this.useIndependentCamera ? this.independentZoomLevel :
                                 (this.sharedCamera ? this.sharedCamera.zoomLevel : 3.0);
                const w = this.canvas.width / window.devicePixelRatio;
                const viewWidth = this.wireDiameter * zoomLevel;
                const scale = (w * 0.8) / viewWidth;

                // Vertical pan (always available)
                this.cameraY -= dy / scale;

                // Horizontal pan (only in independent mode)
                if (this.useIndependentCamera) {
                    this.independentCameraX -= dx / scale;
                }

                this.lastMouseX = e.offsetX;
                this.lastMouseY = e.offsetY;

                // Trigger redraw
                if (this.controller && this.controller.data) {
                    this.controller.drawFrame(this.controller.currentFrame);
                }
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

        // Double-click to reset position
        this.canvas.addEventListener('dblclick', () => {
            this.cameraY = 0;
            if (this.useIndependentCamera) {
                this.independentCameraX = 0;
                this.independentZoomLevel = 3.0;
            }

            // Trigger redraw
            if (this.controller && this.controller.data) {
                this.controller.drawFrame(this.controller.currentFrame);
            }
        });
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

        // Get camera position (either from shared camera or independent)
        const cameraX = this.useIndependentCamera ? this.independentCameraX :
                       (this.sharedCamera ? this.sharedCamera.cameraX : 0);
        const zoomLevel = this.useIndependentCamera ? this.independentZoomLevel :
                         (this.sharedCamera ? this.sharedCamera.zoomLevel : 3.0);

        // Scale calculation
        const viewWidth = this.wireDiameter * zoomLevel;
        const scale = (w * 0.8) / viewWidth;

        // Wire position
        const wireEdgePos = frameData.wire_position || 0; // µm
        const wireRadius = this.wireDiameter / 2; // mm
        const wireCenterX = (wireEdgePos / 1000) - wireRadius; // mm

        // Draw static water background in screen space so it does not shift with camera
        this.drawWaterScreen(w, h);

        // Save context
        this.ctx.save();

        // Setup camera transform (horizontal from TopView, vertical independent)
        this.ctx.translate(w / 2, h / 2);
        this.ctx.translate(-cameraX * scale, -this.cameraY * scale);

        // Workpiece frontier position
        const workpieceEdgePos = frameData.workpiece_position || 0; // µm
        const workpieceEdgeX = workpieceEdgePos / 1000; // mm

        // Draw cut material behind wire (world space)
        this.drawCutMaterial(workpieceEdgeX, scale, h);

        // Draw workpiece (full thickness block, starting from workpiece edge)
        this.drawWorkpiece(workpieceEdgeX, scale, h);

        // Draw nozzles
        this.drawNozzles(wireCenterX, wireRadius, scale);

        // Draw wire
        this.drawWire(wireCenterX, wireRadius, scale, frameData);

        // Detect backward seek and clear sparks
        if (frameIndex < this.lastFrameIndex) {
            this.activeSparks = [];
        }
        this.lastFrameIndex = frameIndex;

        // Handle accumulated sparks from skipped frames
        if (frameData.accumulatedSparks && frameData.accumulatedSparks.length > 0) {
            // Add all accumulated sparks to the active sparks list
            frameData.accumulatedSparks.forEach(spark => {
                this.activeSparks.push({
                    locationMM: spark.locationMM,
                    startFrame: spark.frameIndex,
                    intensity: 1.0
                });
            });
        }

        // Update spark persistence tracking for current frame
        if (frameData.spark_status && frameData.spark_status[0] === 1 && frameData.spark_status[1] !== null) {
            const sparkLocationMM = frameData.spark_status[1]; // y position on wire (mm)
            // Add new spark to active sparks list
            this.activeSparks.push({
                locationMM: sparkLocationMM,
                startFrame: frameIndex,
                intensity: 1.0
            });
        }

        // Calculate dynamic spark persistence based on playback speed
        // Goal: sparks should be visible for ~200ms of real time
        // At 60 FPS display, that's ~12 display frames
        // But we need to account for how many simulation frames pass per display frame
        const playbackSpeed = this.controller ? this.controller.playbackSpeed : 60;
        const framesPerDisplayFrame = Math.max(1, Math.round(playbackSpeed / 60));
        // Scale persistence so sparks are visible for approximately the same real-time duration
        const sparkPersistenceFrames = Math.max(this.baseSparkPersistenceFrames, framesPerDisplayFrame * 12);

        // Remove old sparks (older than persistence time)
        this.activeSparks = this.activeSparks.filter(
            spark => (frameIndex - spark.startFrame) < sparkPersistenceFrames
        );

        // Draw all active sparks with decay (if enabled)
        if (this.showSparks) {
            const gap = (frameData.workpiece_position || 0) - (frameData.wire_position || 0); // Gap in µm
            this.activeSparks.forEach(spark => {
                const age = frameIndex - spark.startFrame;
                const decayFactor = 1.0 - (age / sparkPersistenceFrames); // Linear decay from 1.0 to 0
                this.drawSpark(wireCenterX, wireRadius, workpieceEdgeX, scale, spark.locationMM, gap, decayFactor);
            });
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

    drawWaterScreen(canvasWidth, canvasHeight) {
        // Draw water across the entire canvas in screen space (does not pan/zoom)
        this.ctx.fillStyle = 'rgba(69, 133, 136, 0.2)';
        this.ctx.fillRect(0, 0, canvasWidth, canvasHeight);
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

        // Nozzle dimensions - fixed size (independent of workpiece thickness)
        const nozzleWidth = 6.0 * scale; // 6mm width at base (2x original)
        const nozzleHeight = 2.0 * scale; // 2mm height (same as original)
        const nozzleTopWidth = 1.6 * scale; // 1.6mm width at narrow end (2x original)

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

    drawSpark(wireCenterX, wireRadius, workpieceEdgeX, scale, sparkLocationMM, gapUM, decayFactor) {
        const wireCenterXPx = wireCenterX * scale;
        const radiusPx = wireRadius * scale;
        const workpieceEdgeXPx = workpieceEdgeX * scale;

        // Spark position: from wire right edge
        const wireRightEdge = wireCenterXPx + radiusPx;
        
        // Ensure minimum spark length of 50µm for visibility
        const minSparkLengthUM = 50.0; // µm
        const actualGapMM = gapUM / 1000.0; // Convert gap to mm
        const minSparkLengthMM = minSparkLengthUM / 1000.0; // Convert to mm
        const sparkLengthMM = Math.max(actualGapMM, minSparkLengthMM);
        const sparkEndX = wireRightEdge + (sparkLengthMM * scale);

        // Vertical position from spark_status[1] (y position on wire in mm)
        // spark_location ranges from 0 (bottom) to workpiece_height (top) in mm
        // Canvas: +y is down, -y is up
        // Map: 0 → +workpieceHalfThickness (bottom), workpiece_height → -workpieceHalfThickness (top)
        const thicknessMM = this.workpieceThickness; // in mm
        const workpieceHalfThickness = thicknessMM / 2;
        const sparkY = (workpieceHalfThickness - sparkLocationMM) * scale;

        // Spark appearance with decay
        const brightness = decayFactor; // 1.0 when new, fades to 0
        const alpha = Math.pow(brightness, 0.5); // Square root for slower visual fade
        
        // Spark thickness: 100 µm = 0.1 mm (as originally requested)
        const sparkThickness = 0.1 * scale;
        
        // Draw bright spark with multiple layers for visibility (only varying glow, not thickness)
        // Layer 1: Wide outer glow (cool blue-white outer)
        this.ctx.strokeStyle = `rgba(150, 200, 255, ${alpha * 0.4})`; // Light blue outer glow
        this.ctx.lineWidth = sparkThickness * 3.0;
        this.ctx.shadowBlur = 15;
        this.ctx.shadowColor = `rgba(180, 220, 255, ${alpha * 0.8})`;
        this.ctx.beginPath();
        this.ctx.moveTo(wireRightEdge, sparkY);
        this.ctx.lineTo(sparkEndX, sparkY);
        this.ctx.stroke();

        // Layer 2: Medium glow (bright cyan-white)
        this.ctx.strokeStyle = `rgba(200, 230, 255, ${alpha * 0.7})`; // Cyan-white
        this.ctx.lineWidth = sparkThickness * 2.0;
        this.ctx.shadowBlur = 10;
        this.ctx.shadowColor = `rgba(220, 240, 255, ${alpha})`;
        this.ctx.beginPath();
        this.ctx.moveTo(wireRightEdge, sparkY);
        this.ctx.lineTo(sparkEndX, sparkY);
        this.ctx.stroke();

        // Layer 3: Bright core (100µm thickness - intense white-blue)
        this.ctx.strokeStyle = `rgba(240, 250, 255, ${alpha * 0.95})`; // Very bright blue-white core
        this.ctx.lineWidth = sparkThickness;
        this.ctx.shadowBlur = 5;
        this.ctx.shadowColor = `rgba(255, 255, 255, ${alpha})`;
        this.ctx.beginPath();
        this.ctx.moveTo(wireRightEdge, sparkY);
        this.ctx.lineTo(sparkEndX, sparkY);
        this.ctx.stroke();

        // Reset shadow
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
    constructor(canvasId) {
        super(canvasId);
        this.mode = 'auto'; // 'auto' | 'manual'
        this.usPerDiv = null; // µs per division when manual
        this.divisionsX = 10; // vertical grid lines (time/div)
        this.divisionsY = 5;  // horizontal grid lines per channel
        this.windowUs = 100; // updated per timebase
        this.lastDrawnFrame = -1;
        this.sampleStartIndex = 0; // left edge index in data arrays
        this.sampleEndIndex = 0;   // right edge index in data arrays
        this.maxPointsPerSeries = 2000; // decimation guard for performance
        this.channelGap = 8; // gap between channels in px
        // Fixed voltage axis limits
        this.vFixedMin = 0;
        this.vFixedMax = 100;
        // Trigger configuration
        this.trigger = { enabled: false, source: 'ch1', slope: 'rising', level: 50, delayUs: 0 };
        // Vertical offsets
        this.vOffset = 0; // volts
        this.iOffset = 0; // amps
        // Per-channel vertical scale (V/div and A/div). 'auto' or numeric
        this.vPerDiv = 'auto';
        this.iPerDiv = 'auto';
        // Enable/disable toggle
        this.isEnabled = false; // Default OFF
    }

    setTrigger(cfg) {
        this.trigger = Object.assign({}, this.trigger, cfg || {});
    }

    setOffsets(vOffset, iOffset) {
        this.vOffset = Number.isFinite(vOffset) ? vOffset : 0;
        this.iOffset = Number.isFinite(iOffset) ? iOffset : 0;
    }

    setVerticalScales(vPerDiv, iPerDiv) {
        this.vPerDiv = vPerDiv === 'auto' ? 'auto' : parseFloat(vPerDiv);
        this.iPerDiv = iPerDiv === 'auto' ? 'auto' : parseFloat(iPerDiv);
    }

    setTimebase(mode, usPerDiv) {
        this.mode = mode;
        this.usPerDiv = usPerDiv;
        // Reset auto timebase when switching modes
        if (mode === 'auto') {
            this.autoTimebaseUsPerDiv = null;
        }
    }

    setData(data) {
        super.setData(data);
        // Reset auto timebase so it gets recalculated for new data
        this.autoTimebaseUsPerDiv = null;
        this.recomputeWindow(this.controller ? this.controller.currentFrame : 0);
    }

    onResize() {
        super.onResize();
        if (this.controller && this.controller.data) {
            this.controller.drawFrame(this.controller.currentFrame);
        }
    }

    recomputeWindow(frameIndex) {
        if (!this.data) return;
        const totalFrames = this.data.time.length;
        const w = this.canvas.width / window.devicePixelRatio;

        let usPerDiv;
        if (this.mode === 'manual' && this.usPerDiv) {
            usPerDiv = this.usPerDiv;
        } else {
            // Use a fixed auto timebase calculated once from typical values
            if (!this.autoTimebaseUsPerDiv) {
                // Calculate once from median ON/OFF times or use defaults
                let onUs = 3, offUs = 80; // defaults
                if (this.data.ON_time && this.data.ON_time.length > 0) {
                    // Use median value for stability
                    const validOns = this.data.ON_time.filter(v => typeof v === 'number' && v > 0);
                    if (validOns.length > 0) {
                        validOns.sort((a, b) => a - b);
                        onUs = validOns[Math.floor(validOns.length / 2)];
                    }
                }
                if (this.data.OFF_time && this.data.OFF_time.length > 0) {
                    const validOffs = this.data.OFF_time.filter(v => typeof v === 'number' && v > 0);
                    if (validOffs.length > 0) {
                        validOffs.sort((a, b) => a - b);
                        offUs = validOffs[Math.floor(validOffs.length / 2)];
                    }
                }
                const typicalCycleUs = Math.max(onUs + offUs, 20);
                const desiredWindowUs = typicalCycleUs * 12; // ~1.2 cycles across 10 divisions
                this.autoTimebaseUsPerDiv = Math.max(1, Math.round(desiredWindowUs / this.divisionsX));
            }
            usPerDiv = this.autoTimebaseUsPerDiv;
        }

        this.windowUs = usPerDiv * this.divisionsX;

        // Default window right-aligned at current frame
        const right = frameIndex;
        const left = Math.max(0, right - this.windowUs + 1);
        this.sampleStartIndex = left;
        this.sampleEndIndex = Math.min(totalFrames - 1, right);

        // If trigger enabled, center 0-time (trigger) in the middle, with optional delay
        if (this.trigger && this.trigger.enabled) {
            // Search for trigger within a broader range around current frame
            const searchLeft = Math.max(0, frameIndex - this.windowUs * 5);
            const searchRight = Math.min(totalFrames - 1, frameIndex + this.windowUs * 5);
            const trigIdx = this.findTriggerIndex(searchLeft, searchRight);
            if (trigIdx !== null) {
                const half = Math.floor(this.windowUs / 2);
                const delayFrames = Math.round(Number(this.trigger.delayUs || 0));
                const centerIdx = trigIdx + delayFrames;
                let newLeft = Math.max(0, centerIdx - half);
                let newRight = Math.min(totalFrames - 1, newLeft + this.windowUs - 1);
                if (newRight - newLeft + 1 < this.windowUs) {
                    newLeft = Math.max(0, newRight - this.windowUs + 1);
                }
                this.sampleStartIndex = newLeft;
                this.sampleEndIndex = newRight;
            }
        }
    }

    // Find first trigger crossing within [start, end]; returns index or null
    findTriggerIndex(start, end) {
        const sourceSeries = this.trigger.source === 'ch2' ? (this.data.current || []) : (this.data.voltage || []);
        const level = this.trigger.level;
        const rising = this.trigger.slope !== 'falling';
        for (let i = Math.max(start + 1, 1); i <= end; i++) {
            const prev = sourceSeries[i - 1];
            const curr = sourceSeries[i];
            if (typeof prev !== 'number' || typeof curr !== 'number') continue;
            if (rising) {
                if (prev < level && curr >= level) return i;
            } else {
                if (prev > level && curr <= level) return i;
            }
        }
        return null;
    }

    draw(frameData, frameIndex) {
        this.clear();
        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;

        // Background (professional gray)
        this.ctx.fillStyle = '#1a1a1a';
        this.ctx.fillRect(0, 0, w, h);

        // Always calculate grid positions for sidebar alignment, even when disabled
        const padLeft = 64;
        const padRight = 64;
        const padTop = 10;
        const padBottom = 18;
        const availableH = Math.max(1, h - padTop - padBottom);
        const channelGap = 8;
        const chH = Math.max(1, Math.floor((availableH - channelGap) / 2));
        const vTopY0 = padTop;
        const vTopY1 = vTopY0 + chH;
        const cBotY0 = vTopY1 + channelGap;
        const cBotY1 = cBotY0 + chH;
        
        // Store grid positions for sidebar alignment
        this.channelGridPositions = {
            ch1Y0: vTopY0,
            ch1Y1: vTopY1,
            ch2Y0: cBotY0,
            ch2Y1: cBotY1,
            canvasHeight: h
        };

        if (!this.isEnabled) {
            this.drawText('Oscilloscope OFF', w/2, h/2, {
                color: '#888', font: 'bold 16px sans-serif', align: 'center', baseline: 'middle'
            });
            // Align controls even when off
            this.alignSidebarControls();
            return;
        }

        if (!this.data) {
            this.drawText('Oscilloscope', w/2, h/2, {
                color: '#076678', font: 'bold 16px sans-serif', align: 'center', baseline: 'middle'
            });
            // Align controls even when no data
            this.alignSidebarControls();
            return;
        }

        // Update window based on timebase and current frame
        this.recomputeWindow(frameIndex);

        // Determine series
        const voltageSeries = this.data.voltage || [];
        const currentSeries = this.data.current || [];
        const sparkStatus = this.data.spark_status || [];

        // Visible range in data (may be shorter than full window at the beginning)
        const start = this.sampleStartIndex;
        const end = this.sampleEndIndex;
        // For axis/grid scaling, use a fixed virtual window span even if we have few samples
        const endForScale = Math.max(end, start + this.windowUs - 1);

        // Layout (extra side padding so labels fit on screen)
        // Grid positions already calculated at top of draw() for alignment
        const plotX0 = padLeft;
        const plotX1 = w - padRight;
        const plotW = Math.max(1, plotX1 - plotX0);

        // X scale common to both channels (fixed-width window regardless of available samples)
        const xToPx = (i) => plotX0 + ((i - start) / Math.max(1, (endForScale - start))) * plotW;

        // Voltage Y scale
        let vMin, vMax;
        if (this.vPerDiv === 'auto') {
            // Auto mode: fixed range with offset shifting the display
            vMin = this.vFixedMin - (this.vOffset || 0);
            vMax = this.vFixedMax - (this.vOffset || 0);
        } else {
            // Manual mode: use V/div to set range, centered with offset
            const span = Number(this.vPerDiv) * this.divisionsY; // total volts across channel
            const center = -(this.vOffset || 0); // offset shifts the center
            vMin = center - span / 2;
            vMax = center + span / 2;
        }
        const vToPx = (v) => vTopY1 - ((v - vMin) / Math.max(1e-9, vMax - vMin)) * chH;

        // Current Y scale
        let cMin, cTop;
        if (this.iPerDiv === 'auto') {
            // Auto mode: find range from data, apply offset
            const cMM = this.seriesMinMax(currentSeries, start, end, 0, 1);
            cMin = cMM.min - (this.iOffset || 0);
            cTop = cMM.max + 10 - (this.iOffset || 0); // add 10 A headroom above maximum
            if (!(cTop > cMin)) { cTop = cMin + 1; }
        } else {
            // Manual mode: use A/div to set range, centered with offset
            const span = Number(this.iPerDiv) * this.divisionsY; // total amps across channel
            const center = -(this.iOffset || 0); // offset shifts the center
            cMin = center - span / 2;
            cTop = center + span / 2;
        }
        const cToPx = (c) => cBotY1 - ((c - cMin) / Math.max(1e-9, cTop - cMin)) * chH;

        // Draw grids per channel (subtle on dark background)
        this.drawGridRect(plotX0, vTopY0, plotW, chH);
        this.drawGridRect(plotX0, cBotY0, plotW, chH);

        // Clip and draw series in each channel
        // Voltage (bright blue with faint glow)
        this.ctx.save();
        this.ctx.beginPath();
        this.ctx.rect(plotX0, vTopY0, plotW, chH);
        this.ctx.clip();
        this.drawSeriesDecimated(
            voltageSeries,
            start,
            end,
            xToPx,
            vToPx,
            '#4fc3ff', // bright blue
            2.2,
            'rgba(79,195,255,0.5)'
        );
        this.ctx.restore();

        // Current (bright pink/red with faint glow)
        this.ctx.save();
        this.ctx.beginPath();
        this.ctx.rect(plotX0, cBotY0, plotW, chH);
        this.ctx.clip();
        this.drawSeriesDecimated(
            currentSeries,
            start,
            end,
            xToPx,
            cToPx,
            '#ff6aa0', // pinkish red
            2.0,
            'rgba(255,106,160,0.45)'
        );
        this.ctx.restore();

        // Event markers in both channels (REMOVED - shorts no longer displayed)

        // Trigger centerline axis with dense ticks (when enabled)
        if (this.trigger && this.trigger.enabled) {
            const centerX = plotX0 + plotW / 2;
            this.drawCenterTimeAxis(centerX, vTopY0, vTopY1, cBotY0, cBotY1);
        }

        // Axis labels per channel
        this.drawText('Ch1 V', plotX0 - 36, vTopY0 - 2 + 10, { color: '#4fc3ff', font: '10px monospace' });
        this.drawText(`${vMax.toFixed(0)} V`, 6, vTopY0 - 2, { color: '#b3e5ff', font: '10px monospace' });
        this.drawText(`${vMin.toFixed(0)} V`, 6, vTopY1 - 12, { color: '#b3e5ff', font: '10px monospace' });

        this.drawText('Ch2 I', plotX1 + 6, cBotY0 - 2 + 10, { color: '#ff6aa0', font: '10px monospace' });
        this.drawText(`${cTop.toFixed(2)} A`, plotX1 + 6, cBotY0 - 2, { color: '#ffc1d8', font: '10px monospace' });
        this.drawText(`${cMin.toFixed(2)} A`, plotX1 + 6, cBotY1 - 12, { color: '#ffc1d8', font: '10px monospace' });

        // Timebase label bottom-center
        const timebaseLabel = this.mode === 'manual' && this.usPerDiv ? `${this.usPerDiv} µs/div` : 'Auto';
        this.drawText(timebaseLabel, w / 2, h - 12, { color: 'rgba(220,220,220,0.8)', font: '10px monospace', align: 'center' });
        
        this.lastDrawnFrame = frameIndex;
        
        // Align sidebar controls with channel grids (after drawing)
        this.alignSidebarControls();
    }
    
    
    alignSidebarControls() {
        const ch1Controls = document.getElementById('ch1Controls');
        const ch2Controls = document.getElementById('ch2Controls');
        
        if (!ch1Controls || !ch2Controls) return;
        if (!this.channelGridPositions) return;
        
        const pos = this.channelGridPositions;
        const canvasRect = this.canvas.getBoundingClientRect();
        
        // Calculate center positions of each channel grid
        const ch1Center = pos.ch1Y0 + (pos.ch1Y1 - pos.ch1Y0) / 2;
        const ch2Center = pos.ch2Y0 + (pos.ch2Y1 - pos.ch2Y0) / 2;
        
        // Get control heights
        const ch1Height = ch1Controls.offsetHeight;
        const ch2Height = ch2Controls.offsetHeight;
        
        // Calculate top positions to center controls on grids
        const ch1Top = ch1Center - ch1Height / 2;
        const ch2Top = ch2Center - ch2Height / 2;
        
        // Apply positions (relative to sidebar container)
        ch1Controls.style.position = 'absolute';
        ch1Controls.style.top = `${ch1Top}px`;
        ch1Controls.style.left = '8px';
        ch1Controls.style.right = '8px';
        ch1Controls.style.margin = '0';
        
        ch2Controls.style.position = 'absolute';
        ch2Controls.style.top = `${ch2Top}px`;
        ch2Controls.style.left = '8px';
        ch2Controls.style.right = '8px';
        ch2Controls.style.margin = '0';
    }

    drawGridRect(x, y, width, height) {
        // Subtle grid on dark background
        this.ctx.strokeStyle = 'rgba(255,255,255,0.08)';
        this.ctx.lineWidth = 1;
        // Horizontal
        for (let i = 0; i <= this.divisionsY; i++) {
            const yy = y + (height / this.divisionsY) * i;
            this.ctx.beginPath();
            this.ctx.moveTo(x, yy);
            this.ctx.lineTo(x + width, yy);
            this.ctx.stroke();
        }
        // Vertical
        for (let i = 0; i <= this.divisionsX; i++) {
            const xx = x + (width / this.divisionsX) * i;
            this.ctx.beginPath();
            this.ctx.moveTo(xx, y);
            this.ctx.lineTo(xx, y + height);
            this.ctx.stroke();
        }
        // Slightly stronger outer border
        this.ctx.save();
        this.ctx.strokeStyle = 'rgba(255,255,255,0.22)';
        this.ctx.lineWidth = 1.5;
        this.ctx.strokeRect(x, y, width, height);
        this.ctx.restore();
    }

    seriesMinMax(arr, start, end, fallbackMin, fallbackMax) {
        let min = Infinity, max = -Infinity;
        for (let i = start; i <= end; i++) {
            const v = arr[i];
            if (typeof v !== 'number') continue;
            if (v < min) min = v;
            if (v > max) max = v;
        }
        if (!isFinite(min) || !isFinite(max) || min === max) {
            min = fallbackMin; max = Math.max(fallbackMax, min + 1);
        }
        return { min, max };
    }

    drawSeriesDecimated(series, start, end, xToPx, yToPx, color, lineWidth, glowColor) {
        const w = this.canvas.width / window.devicePixelRatio;
        const plotWidthPx = Math.max(50, w - 80);
        const span = end - start + 1;
        if (span <= 1) return;

        // Simple and effective: max 2 points per pixel (min/max pairs)
        // This prevents canvas overload while preserving waveform shape
        const maxBuckets = Math.floor(plotWidthPx * 2);
        const targetBuckets = Math.min(maxBuckets, this.maxPointsPerSeries);
        const bucketSize = Math.max(1, Math.ceil(span / targetBuckets));

        this.ctx.strokeStyle = color;
        this.ctx.lineWidth = lineWidth;
        
        // Only use glow for reasonable point counts
        const useGlow = glowColor && targetBuckets < 1000;
        if (useGlow) {
            this.ctx.shadowBlur = 8;
            this.ctx.shadowColor = glowColor;
        }
        
        this.ctx.beginPath();
        let penDown = false;
        
        for (let i = start; i <= end; i += bucketSize) {
            let bucketMin = Infinity, bucketMax = -Infinity;
            const bucketEnd = Math.min(end, i + bucketSize - 1);
            
            // Find min/max in bucket
            for (let j = i; j <= bucketEnd; j++) {
                const v = series[j];
                if (typeof v === 'number') {
                    if (v < bucketMin) bucketMin = v;
                    if (v > bucketMax) bucketMax = v;
                }
            }
            
            if (!isFinite(bucketMin)) continue;
            
            // Draw vertical line from min to max at this x position
            const x = xToPx(i + bucketSize / 2);
            const y0 = yToPx(bucketMin);
            const y1 = yToPx(bucketMax);
            
            if (!penDown) {
                this.ctx.moveTo(x, y0);
                penDown = true;
            } else {
                this.ctx.lineTo(x, y0);
            }
            
            if (Math.abs(y1 - y0) > 0.5) {
                this.ctx.lineTo(x, y1);
            }
        }
        
        this.ctx.stroke();
        
        if (useGlow) {
            this.ctx.shadowBlur = 0;
        }
    }

    drawEventMarkersRect(sparkStatus, start, end, xToPx, y0, y1) {
        if (!sparkStatus) return;
        for (let i = start; i <= end; i++) {
            const s = sparkStatus[i];
            if (!s) continue;
            const state = s[0];
            const x = xToPx(i);
            if (state === -1) {
                // short marker at bottom of channel (red) on dark bg
                this.ctx.strokeStyle = 'rgba(255, 80, 80, 0.85)';
                this.ctx.lineWidth = 2;
                this.ctx.beginPath();
                this.ctx.moveTo(x, y1 - (y1 - y0) * 0.12);
                this.ctx.lineTo(x, y1);
                this.ctx.stroke();
            }
        }
    }

    // Draw centered vertical time-axis (t=0) with dense ticks
    drawCenterTimeAxis(centerX, topY0, topY1, botY0, botY1) {
        const drawAxis = (y0, y1) => {
            // Axis line
            this.ctx.save();
            this.ctx.strokeStyle = 'rgba(255,255,255,0.35)';
            this.ctx.lineWidth = 1.8; // thicker than grid
            // Inset slightly so ticks don't collide with border
            const inset = 1.5;
            this.ctx.beginPath();
            this.ctx.moveTo(centerX, y0 + inset);
            this.ctx.lineTo(centerX, y1 - inset);
            this.ctx.stroke();

            // Dense ticks: major at grid lines, minor at half-steps
            const h = y1 - y0;
            const majorCount = this.divisionsY;
            const majorStep = h / majorCount;
            const minorStep = majorStep / 2;
            const majorLen = 8;
            const minorLen = 5;

            this.ctx.lineWidth = 1.3;
            // Major ticks
            for (let i = 0; i <= majorCount; i++) {
                const yy = y0 + majorStep * i;
                // Avoid outer border overlap
                if (yy <= y0 + 2 || yy >= y1 - 2) continue;
                this.ctx.beginPath();
                this.ctx.moveTo(centerX - majorLen, yy);
                this.ctx.lineTo(centerX + majorLen, yy);
                this.ctx.stroke();
            }
            // Minor ticks
            this.ctx.strokeStyle = 'rgba(255,255,255,0.25)';
            this.ctx.lineWidth = 1.0;
            for (let y = y0 + minorStep; y < y1 - 0.5; y += minorStep) {
                if (y <= y0 + 2 || y >= y1 - 2) continue;
                this.ctx.beginPath();
                this.ctx.moveTo(centerX - minorLen, y);
                this.ctx.lineTo(centerX + minorLen, y);
                this.ctx.stroke();
            }

            this.ctx.restore();
        };

        drawAxis(topY0, topY1);
        drawAxis(botY0, botY1);
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
        this.zoomLevel = 15.0; // User-controlled zoom multiplier (start with wider view to see workpiece)
        this.autoPan = true; // Auto-pan when wire gets close to edge

        // Mouse interaction state
        this.isDragging = false;
        this.lastMouseX = 0;
        this.lastMouseY = 0;

        // Spark persistence tracking
        this.activeSparks = []; // Array of {locationMM, startFrame, intensity}
        this.baseSparkPersistenceFrames = 10; // Base number of frames sparks remain visible
        this.lastFrameIndex = -1; // Track frame changes for detecting backward seeks

        // Spark angle map (precomputed on data load)
        this.sparkAngles = new Map();

        // Spark visibility toggle
        this.showSparks = true;

        // Setup mouse controls
        this.setupControls();
    }

    setupControls() {
        // Mouse wheel for zoom
        this.canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const zoomDelta = e.deltaY > 0 ? 1.2 : 0.8;
            this.zoomLevel *= zoomDelta;
            this.zoomLevel = Math.max(0.05, Math.min(10000, this.zoomLevel)); // Clamp between 0.05x and 50x (allows viewing full workpiece)
            
            // Trigger redraw
            if (this.controller && this.controller.data) {
                this.controller.drawFrame(this.controller.currentFrame);
            }
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
                
                // Trigger redraw
                if (this.controller && this.controller.data) {
                    this.controller.drawFrame(this.controller.currentFrame);
                }
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
            this.zoomLevel = 15.0;
            this.autoPan = true;
            this.cameraX = 0;
            
            // Trigger redraw
            if (this.controller && this.controller.data) {
                this.controller.drawFrame(this.controller.currentFrame);
            }
        });
    }

    setData(data) {
        super.setData(data);

        // Extract metadata if available
        if (data.metadata) {
            this.wireDiameter = data.metadata.wire_diameter || 0.25;
            this.initialGap = data.metadata.initial_gap || 50.0;
            this.baseOvercut = data.metadata.base_overcut || 0.030; // mm

            // Workpiece height/thickness for spark mapping in Top View (in mm, from env_config)
            if (data.metadata.workpiece_height_mm !== undefined) {
                this.workpieceHeightMM = data.metadata.workpiece_height_mm;
            } else if (data.metadata.workpiece_height !== undefined) {
                this.workpieceHeightMM = data.metadata.workpiece_height;
            } else {
                // Fallback to 20mm (default from env_config)
                this.workpieceHeightMM = 20.0;
            }

            console.log('TopViewPanel setData - workpieceHeightMM:', this.workpieceHeightMM, 'mm');
            console.log('TopViewPanel setData - baseOvercut:', this.baseOvercut, 'mm');
        }

        // Pre-calculate radial angles for all sparks using the provided distribution
        // p(θ) = k * e^(-k|θ|) / (2(1 - e^(-kπ/2))) for θ ∈ [-π/2, π/2]
        this.precomputeSparkAngles(data);
    }

    precomputeSparkAngles(data) {
        // Initialize spark angle map
        this.sparkAngles = new Map();

        if (!data || !data.spark_status || !data.wire_position || !data.workpiece_position) return;

        // Get base overcut for comparison (in µm)
        // NOTE: base_overcut in metadata is already PER SIDE (not total), so don't divide by 2
        const baseOvercutPerSideUM = (this.baseOvercut || 0.026) * 1000; // Convert mm to µm, per side
        const threshold = baseOvercutPerSideUM; // Threshold is the base_overcut per side
        const transitionRange = 5.0; // ±5 µm transition zone around threshold

        console.log(`=== Spark Angle Distribution ===`);
        console.log(`Base overcut per side (from metadata): ${baseOvercutPerSideUM.toFixed(1)} µm`);
        console.log(`Threshold: ${threshold.toFixed(1)} µm`);
        console.log(`Transition zone: ${(threshold - transitionRange).toFixed(1)} - ${(threshold + transitionRange).toFixed(1)} µm`);
        console.log(`Rule: gap < ${(threshold - transitionRange).toFixed(1)}µm → FRONT (0°) | transition zone → MIXED | gap > ${(threshold + transitionRange).toFixed(1)}µm → SIDES (±90°)`);

        // Track some sample gaps and angles for debugging
        let sampleCount = 0;
        const maxSamples = 15;
        let frontCount = 0;
        let sidesCount = 0;
        let transitionCount = 0;

        // Angle sampling function with gap-dependent distribution
        // Smooth transition between front and sides modes
        const sampleAngle = (gapUM) => {
            // Calculate probability of "sides" mode based on gap
            // Linear interpolation in transition zone
            let pSides; // Probability of using sides distribution

            if (gapUM < threshold - transitionRange) {
                // Pure FRONT mode
                pSides = 0.0;
            } else if (gapUM > threshold + transitionRange) {
                // Pure SIDES mode
                pSides = 1.0;
            } else {
                // TRANSITION zone: linear interpolation
                // gap at (threshold - range) → pSides = 0
                // gap at (threshold + range) → pSides = 1
                pSides = (gapUM - (threshold - transitionRange)) / (2 * transitionRange);
                pSides = Math.max(0, Math.min(1, pSides)); // Clamp to [0, 1]
            }

            // Decide which distribution to use based on probability
            const useSidesMode = Math.random() < pSides;

            // Track statistics
            if (pSides === 0.0) {
                frontCount++;
            } else if (pSides === 1.0) {
                sidesCount++;
            } else {
                transitionCount++;
            }

            // Debug logging for first few sparks
            if (sampleCount < maxSamples) {
                const mode = pSides === 0.0 ? 'FRONT' : pSides === 1.0 ? 'SIDES' : `TRANSITION (${(pSides*100).toFixed(0)}% sides)`;
                console.log(`  Spark ${sampleCount}: gap=${gapUM.toFixed(2)}µm → ${mode}`);
                sampleCount++;
            }

            let angle;

            if (useSidesMode) {
                // Large gap: sparks concentrated at the SIDES (±90°, where workpiece walls are)
                // Use exponential distribution but centered at ±π/2 instead of 0
                const u = Math.random();
                const k = 20.0; // Concentration parameter

                // Choose which pole (north +π/2 or south -π/2) randomly
                const pole = Math.random() < 0.5 ? Math.PI/2 : -Math.PI/2;

                // Sample angle around the chosen pole using exponential distribution
                // Map the exponential from [-π/2, π/2] to be centered at the pole
                let offset;
                if (u < 0.5) {
                    // Negative side from pole
                    offset = -Math.log(1 - 2*u*(1 - Math.exp(-k*Math.PI/2))) / k;
                } else {
                    // Positive side from pole
                    offset = Math.log(2*(u-0.5)*(1 - Math.exp(-k*Math.PI/2)) + Math.exp(-k*Math.PI/2)) / k;
                }

                // Add offset to pole position
                angle = pole + offset;

                // Wrap angle to [-π, π]
                if (angle > Math.PI) angle -= 2*Math.PI;
                if (angle < -Math.PI) angle += 2*Math.PI;
            } else {
                // Small gap: sparks concentrated at front (θ=0, perpendicular to workpiece)
                // Use original exponential distribution from initial implementation
                const u = Math.random();
                const k = 5.0; // Concentration parameter

                // Original symmetric exponential distribution on [-π/2, π/2]
                // HARD CONSTRAINT: θ ∈ (-π/2, π/2)
                if (u < 0.5) {
                    // Negative side
                    angle = -Math.log(1 - 2*u*(1 - Math.exp(-k*Math.PI/2))) / k;
                } else {
                    // Positive side
                    angle = Math.log(2*(u-0.5)*(1 - Math.exp(-k*Math.PI/2)) + Math.exp(-k*Math.PI/2)) / k;
                }

                // HARD CONSTRAINT: angles MUST be strictly between -90° and +90°
                angle = Math.max(-Math.PI/2 + 0.001, Math.min(Math.PI/2 - 0.001, angle));
            }

            return angle;
        };

        // Pre-calculate angle for each spark event based on gap at that frame
        let minGap = Infinity;
        let maxGap = -Infinity;
        let sumGap = 0;
        let gapCount = 0;

        data.spark_status.forEach((status, frameIndex) => {
            if (status && status[0] === 1 && status[1] !== null) {
                // Calculate gap at this frame (µm)
                const wirePos = data.wire_position[frameIndex] || 0;
                const workpiecePos = data.workpiece_position[frameIndex] || 0;
                const gapUM = workpiecePos - wirePos;

                // Track gap statistics
                minGap = Math.min(minGap, gapUM);
                maxGap = Math.max(maxGap, gapUM);
                sumGap += gapUM;
                gapCount++;

                // Sample angle from gap-dependent distribution
                const angle = sampleAngle(gapUM);
                this.sparkAngles.set(frameIndex, angle);
            }
        });

        const avgGap = sumGap / gapCount;

        console.log(`\n=== Gap Statistics ===`);
        console.log(`Min gap: ${minGap.toFixed(2)} µm`);
        console.log(`Max gap: ${maxGap.toFixed(2)} µm`);
        console.log(`Avg gap: ${avgGap.toFixed(2)} µm`);
        console.log(`Threshold: ${threshold.toFixed(2)} µm (±${transitionRange.toFixed(1)} µm transition)`);
        console.log(`\n=== Results ===`);
        console.log(`Total sparks: ${this.sparkAngles.size}`);
        console.log(`Distribution: ${frontCount} pure FRONT (0°), ${transitionCount} TRANSITION, ${sidesCount} pure SIDES (±90°)`);
        console.log(`${((frontCount/this.sparkAngles.size)*100).toFixed(1)}% front, ${((transitionCount/this.sparkAngles.size)*100).toFixed(1)}% transition, ${((sidesCount/this.sparkAngles.size)*100).toFixed(1)}% sides`);
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

        // Kerf width: k = base_overcut + wire_diameter (ignoring dynamic crater_depth component)
        // This is a static approximation. Full formula: k = base_overcut + wire_diameter + crater_depth
        const kerfWidth = ((this.baseOvercut || 0.05)) + this.wireDiameter + 0.01; // mm + crater_size*2

        // Workpiece frontier geometry
        // The kerf width is the TOTAL width of the cutting channel, so the frontier radius
        // from the wire center is half the kerf width
        const frontierRadius = kerfWidth / 2; // mm

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

        // Handle spark persistence tracking (same as side view)
        // Detect backward seek and clear sparks
        if (frameIndex < this.lastFrameIndex) {
            this.activeSparks = [];
        }
        this.lastFrameIndex = frameIndex;

        // Handle accumulated sparks from skipped frames
        if (frameData.accumulatedSparks && frameData.accumulatedSparks.length > 0) {
            frameData.accumulatedSparks.forEach(spark => {
                this.activeSparks.push({
                    locationMM: spark.locationMM,
                    startFrame: spark.frameIndex,
                    intensity: 1.0
                });
            });
        }

        // Update spark persistence tracking for current frame
        if (frameData.spark_status && frameData.spark_status[0] === 1 && frameData.spark_status[1] !== null) {
            const sparkLocationMM = frameData.spark_status[1];
            this.activeSparks.push({
                locationMM: sparkLocationMM,
                startFrame: frameIndex,
                intensity: 1.0
            });
        }

        // Calculate dynamic spark persistence
        const playbackSpeed = this.controller ? this.controller.playbackSpeed : 60;
        const framesPerDisplayFrame = Math.max(1, Math.round(playbackSpeed / 60));
        const sparkPersistenceFrames = Math.max(this.baseSparkPersistenceFrames, framesPerDisplayFrame * 12);

        // Remove old sparks
        this.activeSparks = this.activeSparks.filter(
            spark => (frameIndex - spark.startFrame) < sparkPersistenceFrames
        );

        // Layer 1 (bottom): Draw blue dielectric/water background
        this.drawKerf(wireCenterX, wireRadius, frontierCenterX, frontierRadius);

        // Layer 4 (top): Draw all active sparks with decay (if enabled)
        if (this.showSparks) {
            this.activeSparks.forEach(spark => {
                const age = frameIndex - spark.startFrame;
                const decayFactor = 1.0 - (age / sparkPersistenceFrames);
                this.drawSpark(wireCenterX, wireRadius, spark.locationMM, gapUM, decayFactor, spark.startFrame);
            });
        }

        // Layer 2: Draw workpiece blocks
        this.drawWorkpiece(frontierCenterX, frontierRadius, wireCenterX, wireRadius);

        // Layer 3: Draw wire
        this.drawWire(wireCenterX, wireRadius, frameData);



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
        // Draw blue dielectric/water background in the gap region
        const frontierCenterXPx = frontierCenterX * this.scale;
        const frontierRadiusPx = frontierRadius * this.scale;

        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;
        const maxDim = Math.max(w, h) * 2;

        const cutChannelHalfHeight = frontierRadiusPx;

        // Draw water/dielectric background in cut channel
        this.ctx.fillStyle = 'rgba(69, 133, 136, 0.35)'; // Gruvbox blue
        this.ctx.fillRect(
            -maxDim,
            -cutChannelHalfHeight,
            frontierCenterXPx + maxDim + maxDim,
            cutChannelHalfHeight * 2
        );
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

    drawSpark(wireX, wireRadius, sparkLocationMM, gapUM, decayFactor, sparkFrameIndex) {
        const wireCenterXPx = wireX * this.scale;
        const wireRadiusPx = wireRadius * this.scale;

        // Get precomputed angle for this spark (or fallback to 0 if not found)
        const angle = this.sparkAngles.get(sparkFrameIndex) || 0;

        // Draw LONGER cylinders that extend beyond wire and workpiece
        // This way we only see the middle portion, avoiding cylinder end caps
        const extensionFactor = 0.4; // Extend 60% beyond each end (5x shorter than before)

        // Spark starts INSIDE the wire (negative extension)
        const sparkStartRadiusMM = -wireRadius * extensionFactor;
        // Spark ends BEYOND the workpiece
        const gapMM = gapUM / 1000.0; // Convert gap to mm
        const sparkEndRadiusMM = wireRadius + gapMM + wireRadius * extensionFactor;

        // Calculate start and end positions
        const sparkStartX = wireCenterXPx + (sparkStartRadiusMM * this.scale) * Math.cos(angle);
        const sparkStartY = (sparkStartRadiusMM * this.scale) * Math.sin(angle);

        const sparkEndX = wireCenterXPx + (sparkEndRadiusMM * this.scale) * Math.cos(angle);
        const sparkEndY = (sparkEndRadiusMM * this.scale) * Math.sin(angle);

        // Spark diameter: 60 µm = 0.06 mm
        const sparkDiameter = 0.04; // mm
        const sparkRadiusPx = (sparkDiameter / 2) * this.scale;

        // Spark appearance with decay
        const brightness = decayFactor; // 1.0 when new, fades to 0
        const alpha = Math.pow(brightness, 0.5); // Square root for slower visual fade

        // Draw cylinder (line in 2D top view) - blue-white plasma color
        // Use 'butt' lineCap since the ends are hidden anyway
        this.ctx.lineCap = 'butt';

        // Layer 1: Wide outer glow (cool blue-white outer)
        this.ctx.strokeStyle = `rgba(150, 200, 255, ${alpha * 0.4})`; // Light blue outer glow
        this.ctx.lineWidth = sparkRadiusPx * 2 * 3.0;
        this.ctx.shadowBlur = 15;
        this.ctx.shadowColor = `rgba(180, 220, 255, ${alpha * 0.8})`;
        this.ctx.beginPath();
        this.ctx.moveTo(sparkStartX, sparkStartY);
        this.ctx.lineTo(sparkEndX, sparkEndY);
        this.ctx.stroke();

        // Layer 2: Medium glow (bright cyan-white)
        this.ctx.strokeStyle = `rgba(200, 230, 255, ${alpha * 0.7})`; // Cyan-white
        this.ctx.lineWidth = sparkRadiusPx * 2 * 2.0;
        this.ctx.shadowBlur = 10;
        this.ctx.shadowColor = `rgba(220, 240, 255, ${alpha})`;
        this.ctx.beginPath();
        this.ctx.moveTo(sparkStartX, sparkStartY);
        this.ctx.lineTo(sparkEndX, sparkEndY);
        this.ctx.stroke();

        // Layer 3: Bright core (60µm diameter - intense white-blue)
        this.ctx.strokeStyle = `rgba(240, 250, 255, ${alpha * 0.95})`; // Very bright blue-white core
        this.ctx.lineWidth = sparkRadiusPx * 2;
        this.ctx.shadowBlur = 5;
        this.ctx.shadowColor = `rgba(255, 255, 255, ${alpha})`;
        this.ctx.beginPath();
        this.ctx.moveTo(sparkStartX, sparkStartY);
        this.ctx.lineTo(sparkEndX, sparkEndY);
        this.ctx.stroke();

        // Reset shadow and lineCap
        this.ctx.shadowBlur = 0;
        this.ctx.lineCap = 'round';
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
