/**
 * Dashboard Controller
 * Main controller for the SPARC Visualization Dashboard
 */

import { loadSparcPack } from './utils/dataLoader.js';
import {
    DEFAULT_PLAYBACK_SPEED,
    TARGET_FPS,
    LARGE_FILE_WARNING_BYTES,
    MATERIAL_SEARCH_RADIUS,
    MATERIAL_TRACKING_FALLBACK_DISTANCE,
    MATERIAL_TRACKING_MAX_DISTANCE
} from './utils/constants.js';
import { SideViewPanel } from './panels/SideViewPanel.js';
import { OscilloscopePanel } from './panels/OscilloscopePanel.js';
import { TopViewPanel } from './panels/TopViewPanel.js';
import { ThermalProfilePanel } from './panels/ThermalProfilePanel.js';

export class DashboardController {
    constructor() {
        this.data = null;
        this.currentFrame = 0;
        this.isPlaying = false;
        this.animationId = null;
        this.playbackSpeed = DEFAULT_PLAYBACK_SPEED;
        this.lastFrameTime = 0;
        this.frameAccumulator = 0;
        this.viewsLinked = true;

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
            iPerDiv: document.getElementById('iPerDiv'),
            damageWindow: document.getElementById('damagePlotWindow'),
            closeDamageWindow: document.getElementById('closePlotWindow'),
            damageCanvas: document.getElementById('damagePlotCanvas')
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

        // Setup damage window controls
        this.setupDamageWindow();
    }

    setupDamageWindow() {
        const win = this.elements.damageWindow;
        if (!win) return;

        const header = win.querySelector('.window-header');
        let isDragging = false;
        let startX, startY, initialLeft, initialTop;

        header.addEventListener('mousedown', (e) => {
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            initialLeft = win.offsetLeft;
            initialTop = win.offsetTop;
            header.style.cursor = 'grabbing';
            e.preventDefault();
        });

        window.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            win.style.left = `${initialLeft + dx}px`;
            win.style.top = `${initialTop + dy}px`;
        });

        window.addEventListener('mouseup', () => {
            isDragging = false;
            if (header) header.style.cursor = 'move';
        });

        if (this.elements.closeDamageWindow) {
            this.elements.closeDamageWindow.addEventListener('click', () => {
                win.style.display = 'none';
            });
        }
    }

    showDamagePlot() {
        if (!this.data || !this.selectedMaterialTrace) return;
        const win = this.elements.damageWindow;
        if (!win) return;

        win.style.display = 'flex';
        this.drawDamagePlot();
    }

    drawDamagePlot() {
        if (!this.data || !this.selectedMaterialTrace) return;
        const canvas = this.elements.damageCanvas;
        if (!canvas) return;

        const trace = this.selectedMaterialTrace;

        const ctx = canvas.getContext('2d');
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width * window.devicePixelRatio;
        canvas.height = rect.height * window.devicePixelRatio;
        ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
        const w = rect.width, h = rect.height;

        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = '#fbf1c7';
        ctx.fillRect(0, 0, w, h);

        const damageData = this.data.wire_damage || this.data.damage;
        const positionsData = this.data.wire_material_positions_mm;
        const timeData = this.data.time;

        if (!damageData || !positionsData || !timeData) return;

        let inlet = 160, outlet = 0;
        if (this.data.metadata) {
            const hWP = this.data.metadata.workpiece_height || 100;
            const bBot = this.data.metadata.buffer_len_bottom || 30;
            const bTop = this.data.metadata.buffer_len_top || 30;
            inlet = bBot + hWP + bTop;
            outlet = 0;
        }

        const frames = Array.from(trace.keys()).sort((a, b) => a - b);
        const allT = [], allD = [], allP = [];
        const isD64 = damageData.data && damageData.shape, isP64 = positionsData.data && positionsData.shape;
        const dCols = isD64 ? damageData.shape[1] : 0, pCols = isP64 ? positionsData.shape[1] : 0;

        for (const f of frames) {
            const k = trace.get(f);
            allT.push(Number(timeData[f]) / 1e3);
            allD.push(isD64 ? damageData.data[f * dCols + k] : (damageData[f] ? damageData[f][k] : 0));
            allP.push(isP64 ? positionsData.data[f * pCols + k] : (positionsData[f] ? positionsData[f][k] : 0));
        }

        if (allT.length < 2) return;

        const movesDown = allP[allP.length - 1] < allP[0];
        const entrancePos = movesDown ? Math.max(inlet, outlet) : Math.min(inlet, outlet);

        let speed = 0.001;
        const dt = allT[allT.length - 1] - allT[0], dp = Math.abs(allP[allP.length - 1] - allP[0]);
        if (dt > 1 && dp > 0.001) speed = dp / dt;

        const maxT = Math.abs(inlet - outlet) / speed;
        const maxY = 1.0;

        const padL = 50, padR = 20, padT = 30, padB = 40;
        const graphW = w - padL - padR, graphH = h - padT - padB;

        let currIdx = -1;
        for (let i = 0; i < frames.length; i++) {
            if (frames[i] <= this.currentFrame) currIdx = i; else break;
        }

        let startIdx = -1;
        for (let i = 0; i < allP.length; i++) {
            if (movesDown ? (allP[i] <= entrancePos) : (allP[i] >= entrancePos)) {
                startIdx = i; break;
            }
        }
        if (startIdx === -1) startIdx = 0;

        ctx.strokeStyle = '#3c3836'; ctx.beginPath();
        ctx.moveTo(padL, padT); ctx.lineTo(padL, h - padB); ctx.lineTo(w - padR, h - padB);
        ctx.stroke();

        ctx.fillStyle = '#3c3836'; ctx.font = '10px sans-serif'; ctx.textAlign = 'right';
        ctx.fillText('1.0', padL - 5, padT + 4); ctx.fillText('0', padL - 5, h - padB);
        ctx.textAlign = 'center'; ctx.fillText('0 ms', padL, h - padB + 15);
        ctx.fillText(maxT.toFixed(0) + ' ms', w - padR, h - padB + 15);

        ctx.strokeStyle = '#d65d0e'; ctx.lineWidth = 2; ctx.beginPath();
        let first = true;
        for (let i = startIdx; i <= currIdx; i++) {
            const distFromInlet = movesDown ? (entrancePos - allP[i]) : (allP[i] - entrancePos);
            const tx = distFromInlet / speed;

            const px = padL + (tx / maxT) * graphW;
            const py = h - padB - (allD[i] / maxY) * graphH;
            if (first) { ctx.moveTo(px, py); first = false; } else ctx.lineTo(px, py);
        }
        ctx.stroke();

        if (currIdx >= startIdx) {
            const distFromInlet = movesDown ? (entrancePos - allP[currIdx]) : (allP[currIdx] - entrancePos);
            const tx = distFromInlet / speed;
            const cx = padL + (tx / maxT) * graphW;
            const cy = h - padB - (allD[currIdx] / maxY) * graphH;
            ctx.setLineDash([4, 4]); ctx.strokeStyle = '#d65d0e';
            ctx.beginPath(); ctx.moveTo(cx, padT); ctx.lineTo(cx, h - padB); ctx.stroke();
            ctx.setLineDash([]); ctx.fillStyle = '#d65d0e';
            ctx.beginPath(); ctx.arc(cx, cy, 4, 0, Math.PI * 2); ctx.fill();
        }

        const clickIdx = this.selectedSegmentClickIndex !== undefined ? this.selectedSegmentClickIndex : '?';
        ctx.fillStyle = '#427b58'; ctx.font = 'bold 12px sans-serif'; ctx.textAlign = 'left';
        ctx.fillText(`Segment #${clickIdx}`, padL + 10, padT - 15);
    }

    traceMaterial(startFrame, startSegmentIndex) {
        const trace = new Map();
        if (!this.data || !this.data.wire_material_positions_mm) return trace;

        const positionsData = this.data.wire_material_positions_mm;
        const numFrames = this.data.time.length;
        const isTyped = positionsData.data && positionsData.shape;
        const numCols = isTyped ? positionsData.shape[1] : 0;

        const getPt = (f, k) => isTyped ? positionsData.data[f * numCols + k] : (positionsData[f] ? positionsData[f][k] : undefined);
        const getLen = (f) => isTyped ? numCols : (positionsData[f] ? positionsData[f].length : 0);

        if (getLen(startFrame) <= startSegmentIndex) return trace;

        let currIdx = startSegmentIndex;
        let prevPos = getPt(startFrame, startSegmentIndex);
        trace.set(startFrame, startSegmentIndex);

        // Forward Trace
        for (let f = startFrame + 1; f < numFrames; f++) {
            const n = getLen(f); if (n === 0) break;
            let bestK = -1;
            let bestDist = Infinity;

            const searchRadius = MATERIAL_SEARCH_RADIUS;
            const startK = Math.max(0, currIdx - searchRadius);
            const endK = Math.min(n - 1, currIdx + searchRadius);

            for (let k = startK; k <= endK; k++) {
                const d = Math.abs(getPt(f, k) - prevPos);
                if (d < bestDist) { bestDist = d; bestK = k; }
            }

            if (bestK === -1 || bestDist > MATERIAL_TRACKING_FALLBACK_DISTANCE) {
                for (let k = 0; k < n; k++) {
                    const d = Math.abs(getPt(f, k) - prevPos);
                    if (d < bestDist) { bestDist = d; bestK = k; }
                }
            }

            if (bestK !== -1 && bestDist < MATERIAL_TRACKING_MAX_DISTANCE) {
                currIdx = bestK;
                prevPos = getPt(f, bestK);
                trace.set(f, currIdx);
            } else {
                break;
            }
        }

        // Backward Trace
        currIdx = startSegmentIndex;
        prevPos = getPt(startFrame, startSegmentIndex);
        for (let f = startFrame - 1; f >= 0; f--) {
            const n = getLen(f); if (n === 0) break;
            let bestK = -1;
            let bestDist = Infinity;

            const searchRadius = MATERIAL_SEARCH_RADIUS;
            const startK = Math.max(0, currIdx - searchRadius);
            const endK = Math.min(n - 1, currIdx + searchRadius);

            for (let k = startK; k <= endK; k++) {
                const d = Math.abs(getPt(f, k) - prevPos);
                if (d < bestDist) { bestDist = d; bestK = k; }
            }

            if (bestK === -1 || bestDist > MATERIAL_TRACKING_FALLBACK_DISTANCE) {
                for (let k = 0; k < n; k++) {
                    const d = Math.abs(getPt(f, k) - prevPos);
                    if (d < bestDist) { bestDist = d; bestK = k; }
                }
            }

            if (bestK !== -1 && bestDist < MATERIAL_TRACKING_MAX_DISTANCE) {
                currIdx = bestK;
                prevPos = getPt(f, bestK);
                trace.set(f, currIdx);
            } else {
                break;
            }
        }

        return trace;
    }

    setupKeyboardControls() {
        window.addEventListener('keydown', (e) => {
            if (!this.data) return;

            if (e.key === 'ArrowRight') {
                e.preventDefault();
                this.nextFrame();
            } else if (e.key === 'ArrowLeft') {
                e.preventDefault();
                this.previousFrame();
            }
        });
    }

    initializePanels() {
        this.panels.sideView = new SideViewPanel('sideViewCanvas');
        this.panels.oscilloscope = new OscilloscopePanel('oscilloscopeCanvas');
        this.panels.topView = new TopViewPanel('topViewCanvas');
        this.panels.thermal = new ThermalProfilePanel('thermalCanvas');

        this.panels.sideView.sharedCamera = this.panels.topView;

        Object.values(this.panels).forEach(panel => {
            panel.controller = this;
            panel.init();
        });

        if (this.elements.timebaseControl) {
            this.setTimebase(this.elements.timebaseControl.value || 'auto');
        }
        this.setTriggerConfig({
            enabled: this.elements.triggerEnable ? !!this.elements.triggerEnable.checked : false,
            source: this.elements.triggerSource ? this.elements.triggerSource.value : 'ch1',
            slope: this.elements.triggerSlope ? this.elements.triggerSlope.value : 'rising',
            level: this.elements.triggerLevel ? parseFloat(this.elements.triggerLevel.value) : 50,
            delayUs: this.elements.triggerDelay ? parseFloat(this.elements.triggerDelay.value || '0') : 0
        });
        if (this.panels && this.panels.oscilloscope && this.panels.oscilloscope.setOffsets) {
            const vOff = this.elements.voltageOffset ? parseFloat(this.elements.voltageOffset.value || '0') : 0;
            const iOff = this.elements.currentOffset ? parseFloat(this.elements.currentOffset.value || '0') : 0;
            this.panels.oscilloscope.setOffsets(vOff, iOff);
        }
        if (this.panels && this.panels.oscilloscope && this.panels.oscilloscope.setVerticalScales) {
            const vpd = this.elements.vPerDiv ? this.elements.vPerDiv.value : 'auto';
            const ipd = this.elements.iPerDiv ? this.elements.iPerDiv.value : 'auto';
            this.panels.oscilloscope.setVerticalScales(vpd, ipd);
        }
    }

    toggleViewsLink() {
        this.viewsLinked = !this.viewsLinked;
        this.elements.linkViews.textContent = this.viewsLinked ? 'Linked Views' : 'Unlinked Views';

        if (!this.viewsLinked) {
            this.panels.sideView.useIndependentCamera = true;
            this.panels.sideView.independentZoomLevel = this.panels.topView.zoomLevel;
            this.panels.sideView.independentCameraX = this.panels.topView.cameraX;
        } else {
            this.panels.sideView.useIndependentCamera = false;
        }

        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
    }

    toggleSideViewSparks() {
        this.panels.sideView.showSparks = !this.panels.sideView.showSparks;
        const btn = this.elements.toggleSideViewSparks;
        btn.textContent = this.panels.sideView.showSparks ? 'Sparks ON' : 'Sparks OFF';
        btn.classList.toggle('toggle-on', this.panels.sideView.showSparks);
        btn.classList.toggle('toggle-off', !this.panels.sideView.showSparks);

        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
    }

    toggleTopViewSparks() {
        this.panels.topView.showSparks = !this.panels.topView.showSparks;
        const btn = this.elements.toggleTopViewSparks;
        btn.textContent = this.panels.topView.showSparks ? 'Sparks ON' : 'Sparks OFF';
        btn.classList.toggle('toggle-on', this.panels.topView.showSparks);
        btn.classList.toggle('toggle-off', !this.panels.topView.showSparks);

        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
    }

    toggleOscilloscope() {
        this.panels.oscilloscope.isEnabled = !this.panels.oscilloscope.isEnabled;
        const btn = this.elements.toggleOscilloscope;
        btn.textContent = this.panels.oscilloscope.isEnabled ? 'ON' : 'OFF';
        btn.classList.toggle('osc-power-on', this.panels.oscilloscope.isEnabled);
        btn.classList.toggle('osc-power-off', !this.panels.oscilloscope.isEnabled);

        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
    }

    async loadDataFile(event) {
        const file = event.target.files[0];
        if (!file) return;

        this.showLoading(true);

        try {
            const lowerName = (file.name || '').toLowerCase();
            const isJson = lowerName.endsWith('.json');
            if (isJson) {
                const text = await this.readLargeFile(file);
                if (text.length > LARGE_FILE_WARNING_BYTES) {
                    const proceed = confirm(
                        `Warning: This file is very large (${(text.length / (1024 * 1024)).toFixed(0)} MB). ` +
                        `Loading it may crash your browser. Continue anyway?`
                    );
                    if (!proceed) {
                        throw new Error('Load cancelled by user');
                    }
                }
                this.data = JSON.parse(text);
            } else {
                this.data = await loadSparcPack(file);
            }

            if (!this.data.time || !(Array.isArray(this.data.time) || ArrayBuffer.isView(this.data.time))) {
                throw new Error('Invalid data format: missing time array');
            }

            const maxFrame = (this.data.time.length || 0) - 1;
            this.elements.timeline.max = maxFrame;
            this.currentFrame = 0;

            Object.values(this.panels).forEach(panel => {
                if (panel.setData) {
                    panel.setData(this.data);
                }
            });

            this.drawFrame(0);
            this.updateTimeDisplay();

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
            reader.onload = (e) => resolve(e.target.result);
            reader.onerror = (e) => reject(new Error(`File read error: ${e.target.error.message || 'Unknown error'}`));
            reader.readAsText(file, 'UTF-8');
        });
    }

    togglePlayPause() {
        if (!this.data) {
            alert('Please load data first');
            return;
        }

        this.isPlaying = !this.isPlaying;
        this.elements.playPause.textContent = this.isPlaying ? 'Pause' : 'Play';

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

            const deltaTime = currentTime - this.lastFrameTime;
            this.lastFrameTime = currentTime;

            const framesFloat = (deltaTime / 1000) * this.playbackSpeed;
            this.frameAccumulator += framesFloat;
            const framesToAdvance = Math.floor(this.frameAccumulator);
            this.frameAccumulator -= framesToAdvance;

            if (framesToAdvance > 0) {
                const oldFrame = this.currentFrame;
                this.currentFrame += framesToAdvance;

                if (this.currentFrame >= this.data.time.length) {
                    this.currentFrame = 0;
                }

                this.drawFrameWithAccumulatedSparks(oldFrame, this.currentFrame);
                this.updateTimeDisplay();
                this.elements.timeline.value = this.currentFrame;
            }

            this.animationId = requestAnimationFrame(animate);
        };

        this.animationId = requestAnimationFrame(animate);
    }

    setPlaybackSpeed(speed) {
        this.playbackSpeed = speed;
        this.frameAccumulator = 0;
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
        this.elements.playPause.textContent = 'Play';
        this.seekTo(0);
    }

    previousFrame() {
        if (!this.data) return;
        const frameStep = Math.max(1, Math.round(this.playbackSpeed / TARGET_FPS));
        const prevFrame = Math.max(this.currentFrame - frameStep, 0);
        this.seekToWithAccumulation(prevFrame);
    }

    nextFrame() {
        if (!this.data) return;
        const frameStep = Math.max(1, Math.round(this.playbackSpeed / TARGET_FPS));
        const nextFrame = Math.min(this.currentFrame + frameStep, this.data.time.length - 1);
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

        Object.values(this.panels).forEach(panel => {
            panel.draw(frameData, frameIndex);
        });

        if (this.selectedMaterialTrace && this.elements.damageWindow && this.elements.damageWindow.style.display !== 'none') {
            this.drawDamagePlot();
        }
    }

    drawFrameWithAccumulatedSparks(startFrame, endFrame) {
        if (!this.data) return;

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

        const finalFrameData = this.getFrameData(endFrame);
        finalFrameData.accumulatedSparks = accumulatedSparks;

        Object.values(this.panels).forEach(panel => {
            panel.draw(finalFrameData, endFrame);
        });

        if (this.selectedMaterialTrace && this.elements.damageWindow && this.elements.damageWindow.style.display !== 'none') {
            this.drawDamagePlot();
        }
    }

    getFrameData(frameIndex) {
        const timeSeries = this.data.time;
        const frameData = {
            time: ArrayBuffer.isView(timeSeries) ? timeSeries[frameIndex] : timeSeries[frameIndex],
            frameIndex: frameIndex,
            totalFrames: this.data.time.length
        };

        const isSeries = (v) => Array.isArray(v) || ArrayBuffer.isView(v);

        for (const key in this.data) {
            if (key === 'metadata') continue;
            const value = this.data[key];

            if (value && value.shape && ArrayBuffer.isView(value.data)) {
                if (Array.isArray(value.shape) && value.shape.length === 2) {
                    const cols = value.shape[1];
                    const start = frameIndex * cols;
                    const end = start + cols;
                    const subarray = value.data.subarray(start, end);
                    frameData[key] = Array.from(subarray);
                }
                continue;
            }

            if (isSeries(value)) {
                frameData[key] = value[frameIndex];
            }
        }

        if (!frameData.spark_status) {
            const s = this.data.spark_status_state;
            const l = this.data.spark_status_location_mm;
            const e = this.data.spark_status_extra;
            if (s && l && e && isSeries(s) && isSeries(l) && isSeries(e)) {
                frameData.spark_status = [s[frameIndex], l[frameIndex], e[frameIndex]];
            }
        }

        return frameData;
    }

    updateTimeDisplay() {
        if (!this.data) return;

        const currentTime = Number(this.data.time[this.currentFrame]) / 1000;
        const totalTime = Number(this.data.time[this.data.time.length - 1]) / 1000;

        const formatTime = (ms) => {
            const seconds = Math.floor(ms / 1000);
            const milliseconds = Math.floor(ms % 1000);
            return `${String(seconds).padStart(2, '0')}:${String(milliseconds).padStart(3, '0')}`;
        };

        this.elements.frameCounter.textContent =
            `Frame: ${this.currentFrame + 1} / ${this.data.time.length}`;

        this.elements.timeDisplay.textContent =
            `${formatTime(currentTime)} / ${formatTime(totalTime)}`;
    }

    handleResize() {
        Object.values(this.panels).forEach(panel => {
            if (panel.onResize) {
                panel.onResize();
            }
        });

        if (this.data) {
            this.drawFrame(this.currentFrame);
        }
    }

    showLoading(show) {
        this.elements.loadingOverlay.classList.toggle('hidden', !show);
    }

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
