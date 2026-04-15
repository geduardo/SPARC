/**
 * Dashboard Controller
 * Main controller for the SPARC Visualization Dashboard
 */

import { loadSparcPack } from './utils/dataLoader.js';
import { FileDashboardDataSource, LiveDashboardDataSource } from './utils/dataSource.js';
import {
    DEFAULT_PLAYBACK_SPEED,
    TARGET_FPS,
    LARGE_FILE_WARNING_BYTES,
    MATERIAL_SEARCH_RADIUS,
    MATERIAL_TRACKING_FALLBACK_DISTANCE,
    MATERIAL_TRACKING_MAX_DISTANCE,
    COLORS
} from './utils/constants.js';
import { SideViewPanel } from './panels/SideViewPanel.js';
import { OscilloscopePanel } from './panels/OscilloscopePanel.js';
import { TopViewPanel } from './panels/TopViewPanel.js';
import { ThermalProfilePanel } from './panels/ThermalProfilePanel.js';

const REALTIME_SCHEMA_VERSION = 1;

const LIVE_SETPOINT_CONFIG = {
    gap: { param: 'target_gap', label: 'Target Gap (um)', min: '0', step: '0.1' },
    voltage: { param: 'target_avg_voltage', label: 'Target Vavg (V)', min: '0', step: '0.1' },
    'fixed-servo': { param: 'fixed_servo', label: 'Servo Command', step: '0.01' }
};

export class DashboardController {
    constructor() {
        this.data = null;
        this.dataSource = null;
        this.currentFrame = 0;
        this.isPlaying = false;
        this.animationId = null;
        this.liveAnimationId = null;
        this.playbackSpeed = DEFAULT_PLAYBACK_SPEED;
        this.lastFrameTime = 0;
        this.frameAccumulator = 0;
        this.viewsLinked = true;
        this.followLiveTail = true;
        this.dataSourceSubscription = null;
        this.liveControlTimers = new Map();
        this.liveLastError = null;
        this.liveLastProcessFrameWallMs = null;
        this.currentMode = 'file';
        this.selectedMaterialTrace = null;
        this.selectedMaterialAnchor = null;
        this.selectedSegmentClickIndex = null;
        this.damagePlotCache = null;

        // Panel instances
        this.panels = {
            sideView: null,
            oscilloscope: null,
            topView: null,
            thermal: null
        };

        this.init();
    }

    setDataSource(dataSource) {
        this.clearLiveControlTimers();
        if (this.dataSource && this.dataSourceSubscription) {
            this.dataSourceSubscription();
            this.dataSourceSubscription = null;
        }
        if (this.dataSource && this.dataSource.isLive) {
            this.dataSource.disconnect();
        }

        this.dataSource = dataSource;
        this.data = dataSource ? dataSource.getData() : null;
        this.liveLastError = null;

        if (this.dataSource && this.dataSource.subscribe) {
            this.dataSourceSubscription = this.dataSource.subscribe((event) => this.handleDataSourceEvent(event));
        }

        Object.values(this.panels).forEach(panel => {
            if (panel.setData) {
                panel.setData(this.data);
            }
        });

        this.refreshTimelineBounds();
        this.updateModeLayout();
        this.updateLiveControls();
    }

    handleDataSourceEvent(event) {
        if (!event) return;

        if (event.type === 'header') {
            this.data = this.dataSource ? this.dataSource.getData() : this.data;
            this.liveLastError = null;
            this.liveLastProcessFrameWallMs = null;
            this.clearSelectedMaterialTracking();
            if (this.elements.damageWindow) {
                this.elements.damageWindow.style.display = 'none';
            }
            Object.values(this.panels).forEach(panel => {
                if (panel.setData) {
                    panel.setData(this.data);
                }
            });
            this.refreshTimelineBounds();
            this.updateLiveControls();
            this.drawFrame(this.currentFrame);
            return;
        }

        if (event.type === 'process_frame') {
            this.data = this.dataSource ? this.dataSource.getData() : this.data;
            this.liveLastProcessFrameWallMs = performance.now();
            if (event.droppedFrames > 0) {
                this.handleHistoryTrim(event.droppedFrames);
            }
            this.extendSelectedMaterialTraceToLatestFrame();
            this.refreshTimelineBounds();
            this.updateLiveControls();
            const latestFrame = this.getTotalFrames() - 1;
            if (
                this.dataSource &&
                this.dataSource.isLive &&
                latestFrame >= 0 &&
                (this.followLiveTail || this.currentFrame >= latestFrame)
            ) {
                this.ingestLiveSparks(latestFrame, this.liveLastProcessFrameWallMs);
            }
            if (this.dataSource && this.dataSource.isLive && this.followLiveTail && !this.isPlaying) {
                this.currentFrame = Math.max(0, latestFrame);
                this.elements.timeline.value = this.currentFrame;
                this.updateTimeDisplay();
                if (!this.liveAnimationId) {
                    this.drawFrame(this.currentFrame);
                }
            }
            return;
        }

        if (event.type === 'pulse_chunk') {
            if (this.dataSource && this.dataSource.isLive && !this.isPlaying && this.getTotalFrames() > 0) {
                const latestFrame = Math.max(0, this.getTotalFrames() - 1);
                if ((this.followLiveTail || this.currentFrame >= latestFrame) && !this.liveAnimationId) {
                    this.drawFrame(this.currentFrame);
                }
            }
            return;
        }

        if (event.type === 'session_state') {
            this.data = this.dataSource ? this.dataSource.getData() : this.data;
            this.liveLastError = null;
            this.updateLiveControls();
            return;
        }

        if (event.type === 'reconnecting' || event.type === 'connected' || event.type === 'disconnected' || event.type === 'error') {
            if (event.type === 'error') {
                this.liveLastError = this.extractLiveErrorMessage(event.error);
            } else if (event.type === 'connected') {
                this.liveLastError = null;
            }
            this.updateLiveControls();
            console.info('Dashboard data source event:', event);
        }
    }

    handleHistoryTrim(droppedFrames) {
        if (!Number.isFinite(droppedFrames) || droppedFrames <= 0) return;

        if (!this.followLiveTail) {
            this.currentFrame = Math.max(0, this.currentFrame - droppedFrames);
        }

        if (this.selectedMaterialTrace) {
            const shiftedTrace = new Map();
            for (const [frameIndex, segmentIndex] of this.selectedMaterialTrace.entries()) {
                const shiftedFrame = frameIndex - droppedFrames;
                if (shiftedFrame >= 0) {
                    shiftedTrace.set(shiftedFrame, segmentIndex);
                }
            }
            this.selectedMaterialTrace = shiftedTrace.size > 0 ? shiftedTrace : null;
            if (this.selectedMaterialAnchor) {
                this.selectedMaterialAnchor = {
                    ...this.selectedMaterialAnchor,
                    frameIndex: this.selectedMaterialAnchor.frameIndex - droppedFrames
                };
            }
            this.normalizeSelectedMaterialAnchor();
            this.damagePlotCache = null;
            if (!this.selectedMaterialTrace && this.elements.damageWindow) {
                this.selectedMaterialAnchor = null;
                this.elements.damageWindow.style.display = 'none';
            }
        }

        Object.values(this.panels).forEach(panel => {
            if (panel && panel.onHistoryTrim) {
                panel.onHistoryTrim(droppedFrames);
            }
        });
    }

    async connectLiveStream(url, options = {}) {
        const source = new LiveDashboardDataSource(url, options);
        this.setDataSource(source);
        await source.connect();
        return source;
    }

    disconnectLiveStream() {
        if (this.dataSource && this.dataSource.isLive) {
            this.dataSource.disconnect();
        }
    }

    getTotalFrames() {
        if (this.dataSource) {
            return this.dataSource.getFrameCount();
        }
        if (!this.data || !this.data.time) return 0;
        return this.data.time.length || 0;
    }

    refreshTimelineBounds() {
        const totalFrames = this.getTotalFrames();
        const maxFrame = Math.max(0, totalFrames - 1);
        this.elements.timeline.max = maxFrame;
        this.currentFrame = Math.max(0, Math.min(this.currentFrame, maxFrame));
        this.elements.timeline.value = this.currentFrame;
    }

    init() {
        // Get DOM elements
        this.elements = {
            modeBadge: document.getElementById('modeBadge'),
            recordingControls: document.getElementById('recordingControls'),
            loadData: document.getElementById('loadData'),
            fileInput: document.getElementById('fileInput'),
            playPause: document.getElementById('playPause'),
            reset: document.getElementById('reset'),
            prevFrame: document.getElementById('prevFrame'),
            nextFrame: document.getElementById('nextFrame'),
            timeline: document.getElementById('timeline'),
            frameCounter: document.getElementById('frameCounter'),
            timeDisplay: document.getElementById('timeDisplay'),
            liveControls: document.getElementById('liveControls'),
            liveConnectionState: document.getElementById('liveConnectionState'),
            liveSessionState: document.getElementById('liveSessionState'),
            liveControllerType: document.getElementById('liveControllerType'),
            liveSimTime: document.getElementById('liveSimTime'),
            liveFrameBuffer: document.getElementById('liveFrameBuffer'),
            liveControllerSelect: document.getElementById('liveControllerSelect'),
            liveSetpointLabel: document.getElementById('liveSetpointLabel'),
            liveSetpointValue: document.getElementById('liveSetpointValue'),
            liveSlowdownFactor: document.getElementById('liveSlowdownFactor'),
            liveGeneratorVoltage: document.getElementById('liveGeneratorVoltage'),
            liveCurrentMode: document.getElementById('liveCurrentMode'),
            liveOffTime: document.getElementById('liveOffTime'),
            livePauseResume: document.getElementById('livePauseResume'),
            liveRestart: document.getElementById('liveRestart'),
            liveStop: document.getElementById('liveStop'),
            liveControlNote: document.getElementById('liveControlNote'),
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
            this.elements.triggerLevel.addEventListener('input', onTriggerChange);
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

        this.setupLiveControls();

        // Initialize panels
        this.initializePanels();

        // Handle window resize
        window.addEventListener('resize', () => this.handleResize());

        // Setup keyboard controls
        this.setupKeyboardControls();

        // Setup damage window controls
        this.setupDamageWindow();
        this.updateModeLayout();
    }

    setupLiveControls() {
        const bindDebouncedNumberInput = (element, key, callback, delayMs = 180) => {
            if (!element) return;

            const dispatch = () => {
                const value = parseFloat(element.value);
                if (!Number.isFinite(value)) return;
                callback(value);
            };

            element.addEventListener('input', () => {
                this.scheduleLiveControl(key, dispatch, delayMs);
            });
            element.addEventListener('change', () => {
                this.cancelLiveControl(key);
                dispatch();
            });
        };

        bindDebouncedNumberInput(
            this.elements.liveSlowdownFactor,
            'slowdown_factor',
            (value) => {
                const clampedValue = this.clampRequestedLivePace(value);
                if (!Number.isFinite(clampedValue) || clampedValue <= 0) {
                    return;
                }
                if (this.elements.liveSlowdownFactor) {
                    this.elements.liveSlowdownFactor.value = this.formatLiveControlValue(clampedValue, 0);
                }
                this.sendLiveSpeed(clampedValue);
            }
        );
        bindDebouncedNumberInput(
            this.elements.liveGeneratorVoltage,
            'generator_voltage',
            (value) => this.sendLiveParam('generator_voltage', value)
        );
        bindDebouncedNumberInput(
            this.elements.liveOffTime,
            'off_time',
            (value) => this.sendLiveParam('off_time', value)
        );
        bindDebouncedNumberInput(
            this.elements.liveSetpointValue,
            'active_setpoint',
            (value) => {
                const config = this.getActiveLiveSetpointConfig();
                if (config) {
                    this.sendLiveParam(config.param, value);
                }
            }
        );

        if (this.elements.liveControllerSelect) {
            this.elements.liveControllerSelect.addEventListener('change', () => {
                const value = this.elements.liveControllerSelect.value;
                if (value) {
                    this.sendLiveParam('controller_type', value);
                }
            });
        }

        if (this.elements.liveCurrentMode) {
            this.elements.liveCurrentMode.addEventListener('change', () => {
                const value = parseInt(this.elements.liveCurrentMode.value, 10);
                if (Number.isFinite(value)) {
                    this.sendLiveParam('current_mode', value);
                }
            });
        }

        if (this.elements.livePauseResume) {
            this.elements.livePauseResume.addEventListener('click', () => this.handleLivePauseResume());
        }
        if (this.elements.liveRestart) {
            this.elements.liveRestart.addEventListener('click', () => this.sendLiveCommand('restart'));
        }
        if (this.elements.liveStop) {
            this.elements.liveStop.addEventListener('click', () => this.sendLiveCommand('stop'));
        }

        this.updateLiveControls();
    }

    scheduleLiveControl(key, callback, delayMs = 180) {
        this.cancelLiveControl(key);
        const timer = setTimeout(() => {
            this.liveControlTimers.delete(key);
            callback();
        }, delayMs);
        this.liveControlTimers.set(key, timer);
    }

    cancelLiveControl(key) {
        if (!this.liveControlTimers.has(key)) return;
        clearTimeout(this.liveControlTimers.get(key));
        this.liveControlTimers.delete(key);
    }

    clearLiveControlTimers() {
        this.liveControlTimers.forEach((timerId) => clearTimeout(timerId));
        this.liveControlTimers.clear();
    }

    sendLiveCommand(type, payload = {}) {
        if (!this.dataSource || !this.dataSource.isLive || typeof this.dataSource.send !== 'function') {
            return false;
        }

        const sent = this.dataSource.send({
            v: REALTIME_SCHEMA_VERSION,
            type,
            payload
        });
        if (!sent) {
            this.liveLastError = 'live websocket is not connected';
            this.updateLiveControls();
        }
        return sent;
    }

    sendLiveParam(name, value) {
        return this.sendLiveCommand('set_param', { name, value });
    }

    clampRequestedLivePace(simUsPerWallSecond) {
        const requested = Number(simUsPerWallSecond);
        if (!Number.isFinite(requested) || requested <= 0) {
            return null;
        }

        const maxPace = Number(this.data?.live_session?.maxSimUsPerWallSecond);
        if (Number.isFinite(maxPace) && maxPace > 0) {
            return Math.min(requested, maxPace);
        }
        return requested;
    }

    sendLiveSpeed(simUsPerWallSecond) {
        const pace = Number(simUsPerWallSecond);
        if (!Number.isFinite(pace) || pace <= 0) {
            return false;
        }
        return this.sendLiveCommand('set_speed', { slowdown_factor: 1000000 / pace });
    }

    handleLivePauseResume() {
        const sessionState = this.data && this.data.live_session ? this.data.live_session.sessionState : 'stopped';
        if (sessionState === 'paused') {
            return this.sendLiveCommand('resume');
        }
        if (sessionState === 'stopped') {
            return false;
        }
        return this.sendLiveCommand('pause');
    }

    getActiveLiveSetpointConfig() {
        const currentParams = this.data && this.data.live_session ? this.data.live_session.currentParams || {} : {};
        const controllerType =
            currentParams.controller_type ||
            (this.data && this.data.metadata ? this.data.metadata.controller_strategy : null);
        return LIVE_SETPOINT_CONFIG[controllerType] || null;
    }

    extractLiveErrorMessage(error) {
        if (!error) return null;
        if (typeof error === 'string') return error;
        if (error.payload && typeof error.payload.message === 'string') return error.payload.message;
        if (typeof error.message === 'string') return error.message;
        return 'live session error';
    }

    formatLiveControlValue(value, digits = 3) {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return '';
        if (Number.isInteger(numeric)) {
            return String(numeric);
        }
        return String(Number(numeric.toFixed(digits)));
    }

    isLiveMode() {
        return !!(this.dataSource && this.dataSource.isLive);
    }

    updateModeLayout() {
        const isLiveMode = this.isLiveMode();
        const nextMode = isLiveMode ? 'live' : 'file';
        const modeChanged = nextMode !== this.currentMode;
        this.currentMode = nextMode;
        if (document.body) {
            document.body.classList.toggle('mode-live', isLiveMode);
            document.body.classList.toggle('mode-file', !isLiveMode);
        }

        if (this.elements.modeBadge) {
            this.elements.modeBadge.textContent = isLiveMode ? 'Live' : 'Recording';
            this.elements.modeBadge.classList.toggle('mode-badge-live', isLiveMode);
            this.elements.modeBadge.classList.toggle('mode-badge-file', !isLiveMode);
        }

        if (isLiveMode) {
            this.followLiveTail = true;
            if (this.isPlaying) {
                this.pause();
                this.isPlaying = false;
                this.updatePlayPauseIcon();
            }
            this.startLiveRenderLoop();
        } else {
            this.stopLiveRenderLoop();
            this.liveLastProcessFrameWallMs = null;
        }

        if (modeChanged) {
            requestAnimationFrame(() => this.handleResize());
        }
    }

    startLiveRenderLoop() {
        if (this.liveAnimationId) return;

        const render = (renderTimeMs) => {
            if (!this.isLiveMode()) {
                this.liveAnimationId = null;
                return;
            }

            if (this.data && this.getTotalFrames() > 0) {
                if (this.followLiveTail) {
                    this.currentFrame = Math.max(0, this.getTotalFrames() - 1);
                }
                this.drawFrame(this.currentFrame, { renderTimeMs });
            }

            this.liveAnimationId = requestAnimationFrame(render);
        };

        this.liveAnimationId = requestAnimationFrame(render);
    }

    stopLiveRenderLoop() {
        if (!this.liveAnimationId) return;
        cancelAnimationFrame(this.liveAnimationId);
        this.liveAnimationId = null;
    }

    formatSimTimeShort(timeUs) {
        const numeric = Number(timeUs);
        if (!Number.isFinite(numeric) || numeric < 0) return '--';
        if (numeric >= 1000000) {
            return `${this.formatLiveControlValue(numeric / 1000000, 3)} s`;
        }
        if (numeric >= 1000) {
            return `${this.formatLiveControlValue(numeric / 1000, 3)} ms`;
        }
        return `${this.formatLiveControlValue(numeric, 1)} us`;
    }

    getLivePaceMetrics(slowdownFactor) {
        const slowdown = Number(slowdownFactor);
        const servoIntervalUs = Number(this.data?.metadata?.servo_interval_us) || 1000;

        if (!Number.isFinite(slowdown) || slowdown <= 0) {
            return {
                controlStepSimUs: servoIntervalUs,
                wallMsPerControlStep: null,
                updatesPerWallSecond: null,
                simUsPerWallSecond: null
            };
        }

        return {
            controlStepSimUs: servoIntervalUs,
            wallMsPerControlStep: (servoIntervalUs * slowdown) / 1000,
            updatesPerWallSecond: 1000000 / (servoIntervalUs * slowdown),
            simUsPerWallSecond: 1000000 / slowdown
        };
    }

    formatSimUsPerWallSecond(value) {
        const numeric = Number(value);
        if (!Number.isFinite(numeric) || numeric <= 0) return '--';
        return `${this.formatLiveControlValue(numeric, 0)} us/s`;
    }

    getLiveRequestedPace() {
        const requestedSlowdownFactor = Number(this.data?.live_session?.requestedSlowdownFactor);
        if (!Number.isFinite(requestedSlowdownFactor) || requestedSlowdownFactor <= 0) {
            return null;
        }
        return this.getLivePaceMetrics(requestedSlowdownFactor).simUsPerWallSecond;
    }

    getLiveRenderableFrameData(frameIndex, renderTimeMs = performance.now()) {
        const frameData = this.getFrameData(frameIndex);
        frameData.isLiveMode = true;
        frameData.liveRenderTimeMs = renderTimeMs;

        const totalFrames = this.getTotalFrames();
        if (frameIndex !== totalFrames - 1) {
            return frameData;
        }

        const liveSession = this.data?.live_session || {};
        const currentParams = liveSession.currentParams || {};
        const slowdownFactor = Number(currentParams.slowdown_factor);
        const sessionState = liveSession.sessionState || 'created';
        const connectionState = liveSession.connectionState || 'disconnected';
        const servoIntervalUs = Number(this.data?.metadata?.servo_interval_us) || 1000;

        if (
            sessionState !== 'running' ||
            connectionState !== 'connected' ||
            !Number.isFinite(slowdownFactor) ||
            slowdownFactor <= 0 ||
            !Number.isFinite(this.liveLastProcessFrameWallMs)
        ) {
            return frameData;
        }

        const elapsedWallMs = Math.max(0, renderTimeMs - this.liveLastProcessFrameWallMs);
        const extrapolatedSimUs = Math.min(servoIntervalUs, (elapsedWallMs * 1000) / slowdownFactor);
        if (!Number.isFinite(extrapolatedSimUs) || extrapolatedSimUs <= 0) {
            return frameData;
        }

        const wirePosition = Number(frameData.wire_position);
        const wireVelocity = Number(frameData.wire_velocity);
        if (Number.isFinite(wirePosition) && Number.isFinite(wireVelocity)) {
            frameData.wire_position = wirePosition + wireVelocity * (extrapolatedSimUs / 1000000);
        }

        const timeUs = Number(frameData.time);
        if (Number.isFinite(timeUs)) {
            frameData.time = timeUs + extrapolatedSimUs;
        }
        frameData.liveExtrapolatedSimUs = extrapolatedSimUs;

        return frameData;
    }

    setLiveBadgeState(element, prefix, value, classValue = value) {
        if (!element) return;
        const normalized = String(value || 'unknown');
        const className = String(classValue || value || 'unknown');
        const stateClass = `state-${className.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`;
        element.className = `live-status-badge ${stateClass}`;
        element.textContent = `${prefix} ${normalized}`;
    }

    syncLiveInputValue(element, value, digits = 3) {
        if (!element) return;
        if (document.activeElement === element) return;
        element.value = this.formatLiveControlValue(value, digits);
    }

    updateLiveControls() {
        const liveSession = this.data && this.data.live_session ? this.data.live_session : {};
        const isLiveSource = this.isLiveMode();
        const connectionState = liveSession.connectionState || (isLiveSource ? 'disconnected' : 'file');
        const sessionState = liveSession.sessionState || (isLiveSource ? 'created' : 'stopped');
        const supportedParams = Array.isArray(liveSession.supportedParams) ? liveSession.supportedParams : [];
        const currentParams = liveSession.currentParams || {};
        const controllerType =
            currentParams.controller_type ||
            (this.data && this.data.metadata ? this.data.metadata.controller_strategy : null);
        const setpointConfig = LIVE_SETPOINT_CONFIG[controllerType] || null;
        const isConnected = isLiveSource && connectionState === 'connected';
        const solverLimited = !!liveSession.solverLimited;
        const requestedPace = this.getLiveRequestedPace();
        const maxSustainablePace = Number(liveSession.maxSimUsPerWallSecond);
        const controlComputeWallS = Number(liveSession.controlComputeWallS);
        const terminationReason = liveSession.terminationReason || null;
        const lastError = liveSession.lastError || this.liveLastError;

        if (this.elements.liveControls) {
            this.elements.liveControls.classList.toggle('live-disabled', !isConnected);
        }

        this.setLiveBadgeState(this.elements.liveConnectionState, 'WS', connectionState);
        const sessionBadgeValue =
            sessionState === 'stopped' && terminationReason === 'wire_broken'
                ? 'wire broken'
                : sessionState;
        this.setLiveBadgeState(
            this.elements.liveSessionState,
            'Session',
            sessionBadgeValue,
            sessionState
        );

        if (this.elements.liveControllerType) {
            this.elements.liveControllerType.textContent = controllerType
                ? `Strategy: ${controllerType}`
                : 'Strategy: unavailable';
        }

        if (this.elements.liveSimTime) {
            const latestTimeSeries = this.data && this.data.time;
            const latestTimeUs = latestTimeSeries && latestTimeSeries.length > 0
                ? latestTimeSeries[latestTimeSeries.length - 1]
                : null;
            this.elements.liveSimTime.textContent = `Sim: ${this.formatSimTimeShort(latestTimeUs)}`;
        }
        if (this.elements.liveFrameBuffer) {
            this.elements.liveFrameBuffer.textContent = `Buffered frames: ${this.getTotalFrames()}`;
        }

        if (this.elements.liveSetpointLabel) {
            this.elements.liveSetpointLabel.textContent = setpointConfig ? setpointConfig.label : 'Setpoint';
        }
        if (this.elements.liveSetpointValue && setpointConfig) {
            if (setpointConfig.min !== undefined) {
                this.elements.liveSetpointValue.min = setpointConfig.min;
            } else {
                this.elements.liveSetpointValue.removeAttribute('min');
            }
            if (setpointConfig.step !== undefined) {
                this.elements.liveSetpointValue.step = setpointConfig.step;
            }
        }

        const currentPace = this.getLivePaceMetrics(currentParams.slowdown_factor).simUsPerWallSecond;
        this.syncLiveInputValue(
            this.elements.liveSlowdownFactor,
            Number.isFinite(requestedPace) ? requestedPace : currentPace,
            0
        );
        if (this.elements.liveSlowdownFactor) {
            if (Number.isFinite(maxSustainablePace) && maxSustainablePace > 0) {
                this.elements.liveSlowdownFactor.max = String(Math.max(1, Math.floor(maxSustainablePace)));
            } else {
                this.elements.liveSlowdownFactor.removeAttribute('max');
            }
        }
        this.syncLiveInputValue(this.elements.liveGeneratorVoltage, currentParams.generator_voltage, 2);
        this.syncLiveInputValue(this.elements.liveOffTime, currentParams.off_time, 3);
        if (this.elements.liveControllerSelect && document.activeElement !== this.elements.liveControllerSelect) {
            const nextControllerType = controllerType || 'gap';
            this.elements.liveControllerSelect.value = nextControllerType;
        }
        if (setpointConfig) {
            this.syncLiveInputValue(this.elements.liveSetpointValue, currentParams[setpointConfig.param], 3);
        }
        if (this.elements.liveCurrentMode && document.activeElement !== this.elements.liveCurrentMode) {
            const currentMode = currentParams.current_mode;
            this.elements.liveCurrentMode.value = Number.isFinite(Number(currentMode)) ? String(currentMode) : '';
        }

        const setDisabled = (element, disabled) => {
            if (element) {
                element.disabled = disabled;
            }
        };

        setDisabled(this.elements.liveControllerSelect, !isConnected || !supportedParams.includes('controller_type'));
        setDisabled(this.elements.liveSlowdownFactor, !isConnected || !supportedParams.includes('slowdown_factor'));
        setDisabled(this.elements.liveGeneratorVoltage, !isConnected || !supportedParams.includes('generator_voltage'));
        setDisabled(this.elements.liveCurrentMode, !isConnected || !supportedParams.includes('current_mode'));
        setDisabled(this.elements.liveOffTime, !isConnected || !supportedParams.includes('off_time'));
        setDisabled(
            this.elements.liveSetpointValue,
            !isConnected || !setpointConfig || !supportedParams.includes(setpointConfig.param)
        );

        if (this.elements.livePauseResume) {
            this.elements.livePauseResume.textContent = sessionState === 'paused' ? 'Resume' : 'Pause';
            this.elements.livePauseResume.disabled = !isConnected || sessionState === 'stopped';
        }
        if (this.elements.liveStop) {
            this.elements.liveStop.disabled = !isConnected || sessionState === 'stopped';
        }
        if (this.elements.liveRestart) {
            this.elements.liveRestart.disabled = !isConnected || sessionState !== 'stopped';
        }

        if (this.elements.liveControlNote) {
            const requestedPaceIsCapped =
                Number.isFinite(requestedPace) &&
                requestedPace > 0 &&
                Number.isFinite(maxSustainablePace) &&
                maxSustainablePace > 0 &&
                requestedPace > (maxSustainablePace * 1.001);
            if (!isLiveSource) {
                this.elements.liveControlNote.textContent = 'Load a live session to enable runtime controls.';
            } else if (lastError) {
                this.elements.liveControlNote.textContent = `Last error: ${lastError}`;
            } else if (connectionState === 'connecting') {
                this.elements.liveControlNote.textContent = 'Connecting to live session...';
            } else if (connectionState === 'disconnected') {
                this.elements.liveControlNote.textContent = 'Live controls are disabled until the websocket reconnects.';
            } else if (sessionState === 'stopped' && terminationReason === 'wire_broken') {
                this.elements.liveControlNote.textContent = 'Wire broken. Click Restart to launch a fresh live session.';
            } else if (sessionState === 'stopped') {
                this.elements.liveControlNote.textContent = 'Live session stopped. Click Restart to launch a fresh live session.';
            } else if (requestedPaceIsCapped || solverLimited) {
                const requestedText = Number.isFinite(requestedPace) && requestedPace > 0
                    ? `Requested ${this.formatSimUsPerWallSecond(requestedPace)}`
                    : 'Requested pace';
                const appliedText = Number.isFinite(currentPace) && currentPace > 0
                    ? ` applied as ${this.formatSimUsPerWallSecond(currentPace)}`
                    : '';
                const paceText = Number.isFinite(maxSustainablePace) && maxSustainablePace > 0
                    ? `${requestedText} is capped at ${this.formatSimUsPerWallSecond(maxSustainablePace)} by measured solver throughput.${appliedText}.`
                    : `${requestedText} is capped by measured solver throughput.${appliedText}.`;
                const computeText = Number.isFinite(controlComputeWallS) && controlComputeWallS >= 0
                    ? ` Last compute step: ${this.formatLiveControlValue(controlComputeWallS * 1000, 2)} ms.`
                    : '';
                this.elements.liveControlNote.textContent = `${paceText}${computeText}`;
            } else {
                this.elements.liveControlNote.textContent = '';
            }
        }
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
                // Clear tracking and cache when window is closed
                this.clearSelectedMaterialTracking();
                if (this.data) {
                    this.drawFrame(this.currentFrame);
                }
            });
        }

        // Redraw plot when window is resized
        const resizeObserver = new ResizeObserver(() => {
            if (win.style.display !== 'none' && this.selectedMaterialTrace) {
                this.drawDamagePlot();
            }
        });
        resizeObserver.observe(win);
    }

    showDamagePlot() {
        if (!this.data || !this.selectedMaterialTrace) return;
        const win = this.elements.damageWindow;
        if (!win) return;

        win.style.display = 'flex';
        // Precompute plot data once when showing the plot
        this.precomputeDamagePlotData();
        this.drawDamagePlot();
    }

    precomputeDamagePlotData() {
        if (!this.data || !this.selectedMaterialTrace) {
            this.damagePlotCache = null;
            return;
        }

        const trace = this.selectedMaterialTrace;
        const damageData = this.data.wire_damage || this.data.damage;
        const positionsData = this.data.wire_material_positions_mm;
        const temperatureData = this.data.wire_temperature;
        const timeData = this.data.time;

        if (!damageData || !positionsData || !timeData) {
            this.damagePlotCache = null;
            return;
        }

        let inlet = 160, outlet = 0;
        let unwindingSpeed = Number.NaN;
        if (this.data.metadata) {
            const hWP = this.data.metadata.workpiece_height_mm ?? this.data.metadata.workpiece_height ?? 100;
            const bBot = this.data.metadata.buffer_len_bottom || 30;
            const bTop = this.data.metadata.buffer_len_top || 30;
            inlet = bBot + hWP + bTop;
            outlet = 0;
            unwindingSpeed = Number(this.data.metadata.wire_unwinding_speed_mm_per_ms);
        }

        const frames = Array.from(trace.keys()).sort((a, b) => a - b);
        const allT = [], allD = [], allP = [], allTemp = [];
        const isD64 = damageData.data && damageData.shape, isP64 = positionsData.data && positionsData.shape;
        const isTemp64 = temperatureData && temperatureData.data && temperatureData.shape;
        const dCols = isD64 ? damageData.shape[1] : 0, pCols = isP64 ? positionsData.shape[1] : 0;
        const tempCols = isTemp64 ? temperatureData.shape[1] : 0;

        for (const f of frames) {
            const k = trace.get(f);
            allT.push(Number(timeData[f]) / 1e3);
            allD.push(isD64 ? damageData.data[f * dCols + k] : (damageData[f] ? damageData[f][k] : 0));
            allP.push(isP64 ? positionsData.data[f * pCols + k] : (positionsData[f] ? positionsData[f][k] : 0));

            // Extract temperature (convert from K to C)
            if (temperatureData) {
                const tempK = isTemp64 ? temperatureData.data[f * tempCols + k] : (temperatureData[f] ? temperatureData[f][k] : 273.15);
                allTemp.push(tempK - 273.15);
            } else {
                allTemp.push(0);
            }
        }

        if (allT.length < 2) {
            this.damagePlotCache = null;
            return;
        }

        const movesDown = allP[allP.length - 1] < allP[0];
        const entrancePos = movesDown ? Math.max(inlet, outlet) : Math.min(inlet, outlet);

        let speed = unwindingSpeed;
        if (!Number.isFinite(speed) || speed <= 0) {
            const dt = allT[allT.length - 1] - allT[0];
            const dp = Math.abs(allP[allP.length - 1] - allP[0]);
            if (dt > 1 && dp > 0.001) {
                speed = dp / dt;
            } else {
                speed = 0.001;
            }
        }

        const travelDistance = Math.abs(inlet - outlet);
        const maxT = travelDistance / speed;

        let startIdx = -1;
        for (let i = 0; i < allP.length; i++) {
            if (movesDown ? (allP[i] <= entrancePos) : (allP[i] >= entrancePos)) {
                startIdx = i; break;
            }
        }
        if (startIdx === -1) startIdx = 0;

        // Precompute normalized X coordinates for each point
        const normalizedX = [];
        for (let i = 0; i < allP.length; i++) {
            const distFromInlet = movesDown ? (entrancePos - allP[i]) : (allP[i] - entrancePos);
            normalizedX.push(
                travelDistance > 0
                    ? Math.max(0, Math.min(1, distFromInlet / travelDistance))
                    : 0
            );
        }

        // Find max temperature for scaling (using loop to avoid stack overflow with large arrays)
        let maxTemp = 500; // At least 500C for scale
        for (let i = 0; i < allTemp.length; i++) {
            if (allTemp[i] > maxTemp) maxTemp = allTemp[i];
        }
        const hasTemperature = temperatureData !== undefined && temperatureData !== null;

        this.damagePlotCache = {
            frames,
            allD,
            allTemp,
            normalizedX,
            startIdx,
            maxT,
            maxTemp,
            hasTemperature
        };
    }

    drawDamagePlot() {
        if (!this.data || !this.selectedMaterialTrace) return;
        const canvas = this.elements.damageCanvas;
        if (!canvas) return;

        // Use cached data if available
        if (!this.damagePlotCache) {
            this.precomputeDamagePlotData();
            if (!this.damagePlotCache) return;
        }

        const { frames, allD, allTemp, normalizedX, startIdx, maxT, maxTemp, hasTemperature } = this.damagePlotCache;

        const ctx = canvas.getContext('2d');
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width * window.devicePixelRatio;
        canvas.height = rect.height * window.devicePixelRatio;
        ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
        const w = rect.width, h = rect.height;

        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, w, h);

        const maxY = 1.0;
        const padL = 70, padR = hasTemperature ? 70 : 40, padT = 50, padB = 60;
        const graphW = w - padL - padR, graphH = h - padT - padB;

        // Find current frame index using binary search
        let currIdx = -1;
        let lo = 0, hi = frames.length - 1;
        while (lo <= hi) {
            const mid = (lo + hi) >> 1;
            if (frames[mid] <= this.currentFrame) {
                currIdx = mid;
                lo = mid + 1;
            } else {
                hi = mid - 1;
            }
        }

        // Draw left Y-axis (Damage)
        ctx.strokeStyle = COLORS.danger; ctx.lineWidth = 1.5; ctx.beginPath();
        ctx.moveTo(padL, padT); ctx.lineTo(padL, h - padB);
        ctx.stroke();

        // Draw X-axis
        ctx.strokeStyle = COLORS.text; ctx.lineWidth = 1.5; ctx.beginPath();
        ctx.moveTo(padL, h - padB); ctx.lineTo(w - padR, h - padB);
        ctx.stroke();

        // Left Y-axis labels (Damage)
        ctx.fillStyle = COLORS.danger; ctx.font = '14px sans-serif'; ctx.textAlign = 'right';
        ctx.fillText('1.0', padL - 8, padT + 5);
        ctx.fillText('0.5', padL - 8, padT + graphH / 2 + 4);
        ctx.fillText('0', padL - 8, h - padB + 5);

        // X-axis labels
        ctx.fillStyle = COLORS.text; ctx.textAlign = 'center'; ctx.font = '14px sans-serif';
        ctx.fillText('0', padL, h - padB + 20);
        ctx.fillText(maxT.toFixed(0) + ' ms', w - padR, h - padB + 20);

        // Left Y-axis title (Damage)
        ctx.save();
        ctx.translate(padL - 50, padT + graphH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.font = 'bold 14px sans-serif';
        ctx.fillStyle = COLORS.danger;
        ctx.textAlign = 'center';
        ctx.fillText('Damage', 0, 0);
        ctx.restore();

        // X-axis title
        ctx.fillStyle = COLORS.text;
        ctx.font = 'bold 14px sans-serif';
        ctx.fillText('Time (ms)', padL + graphW / 2, h - padB + 42);

        // Right Y-axis (Temperature) if available
        if (hasTemperature) {
            ctx.strokeStyle = COLORS.warning; ctx.lineWidth = 1.5; ctx.beginPath();
            ctx.moveTo(w - padR, padT); ctx.lineTo(w - padR, h - padB);
            ctx.stroke();

            // Right Y-axis labels (Temperature)
            ctx.fillStyle = COLORS.warning; ctx.font = '14px sans-serif'; ctx.textAlign = 'left';
            const tempStep = maxTemp > 1000 ? 500 : (maxTemp > 500 ? 250 : 100);
            const roundedMax = Math.ceil(maxTemp / tempStep) * tempStep;
            ctx.fillText(roundedMax + 'C', w - padR + 8, padT + 5);
            ctx.fillText((roundedMax / 2).toFixed(0) + 'C', w - padR + 8, padT + graphH / 2 + 4);
            ctx.fillText('0C', w - padR + 8, h - padB + 5);

            // Right Y-axis title (Temperature)
            ctx.save();
            ctx.translate(w - padR + 55, padT + graphH / 2);
            ctx.rotate(Math.PI / 2);
            ctx.font = 'bold 14px sans-serif';
            ctx.fillStyle = COLORS.warning;
            ctx.textAlign = 'center';
            ctx.fillText('Temperature (C)', 0, 0);
            ctx.restore();

            // Draw temperature curve
            const tempScale = Math.ceil(maxTemp / tempStep) * tempStep;
            ctx.strokeStyle = COLORS.warning; ctx.lineWidth = 2; ctx.beginPath();
            let first = true;
            for (let i = startIdx; i <= currIdx; i++) {
                const px = padL + normalizedX[i] * graphW;
                const py = h - padB - (allTemp[i] / tempScale) * graphH;
                if (first) { ctx.moveTo(px, py); first = false; } else ctx.lineTo(px, py);
            }
            ctx.stroke();

            // Temperature marker at current position
            if (currIdx >= startIdx) {
                const cx = padL + normalizedX[currIdx] * graphW;
                const cyTemp = h - padB - (allTemp[currIdx] / tempScale) * graphH;
                ctx.fillStyle = COLORS.warning;
                ctx.beginPath(); ctx.arc(cx, cyTemp, 4, 0, Math.PI * 2); ctx.fill();
            }
        }

        // Draw damage curve using precomputed normalized X
        ctx.strokeStyle = COLORS.danger; ctx.lineWidth = 2.5; ctx.beginPath();
        let firstD = true;
        for (let i = startIdx; i <= currIdx; i++) {
            const px = padL + normalizedX[i] * graphW;
            const py = h - padB - (allD[i] / maxY) * graphH;
            if (firstD) { ctx.moveTo(px, py); firstD = false; } else ctx.lineTo(px, py);
        }
        ctx.stroke();

        // Draw current position marker (vertical line and damage dot)
        if (currIdx >= startIdx) {
            const cx = padL + normalizedX[currIdx] * graphW;
            const cy = h - padB - (allD[currIdx] / maxY) * graphH;
            ctx.setLineDash([4, 4]); ctx.strokeStyle = COLORS.gray4; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(cx, padT); ctx.lineTo(cx, h - padB); ctx.stroke();
            ctx.setLineDash([]); ctx.fillStyle = COLORS.danger;
            ctx.beginPath(); ctx.arc(cx, cy, 5, 0, Math.PI * 2); ctx.fill();
        }

        // Title with segment info
        const clickIdx = this.selectedSegmentClickIndex !== undefined ? this.selectedSegmentClickIndex : '?';
        ctx.fillStyle = COLORS.text; ctx.font = 'bold 16px sans-serif'; ctx.textAlign = 'left';
        ctx.fillText(`Segment #${clickIdx}`, padL, padT - 18);

        // Legend
        const legendX = padL + 120;
        ctx.fillStyle = COLORS.danger;
        ctx.fillRect(legendX, padT - 28, 14, 14);
        ctx.fillStyle = COLORS.text; ctx.font = '12px sans-serif';
        ctx.fillText('Damage', legendX + 20, padT - 17);

        if (hasTemperature) {
            ctx.fillStyle = COLORS.warning;
            ctx.fillRect(legendX + 85, padT - 28, 14, 14);
            ctx.fillStyle = COLORS.text;
            ctx.fillText('Temp', legendX + 105, padT - 17);
        }
    }

    getWireMaterialPositionAccessor() {
        const positionsData = this.data && this.data.wire_material_positions_mm;
        if (!positionsData) return null;

        const isTyped = positionsData.data && positionsData.shape;
        const numCols = isTyped ? positionsData.shape[1] : 0;

        return {
            getPoint: (frameIndex, segmentIndex) => (
                isTyped
                    ? positionsData.data[frameIndex * numCols + segmentIndex]
                    : (positionsData[frameIndex] ? positionsData[frameIndex][segmentIndex] : undefined)
            ),
            getLength: (frameIndex) => (
                isTyped
                    ? numCols
                    : (positionsData[frameIndex] ? positionsData[frameIndex].length : 0)
            )
        };
    }

    estimateTrackedMaterialDisplacementMM(fromFrameIndex, toFrameIndex) {
        const metadata = this.data && this.data.metadata ? this.data.metadata : {};
        const timeSeries = this.data && this.data.time;
        const unwindingSpeed = Number(metadata.wire_unwinding_speed_mm_per_ms);

        if (
            !Number.isFinite(unwindingSpeed) ||
            !timeSeries ||
            !Number.isFinite(Number(timeSeries[fromFrameIndex])) ||
            !Number.isFinite(Number(timeSeries[toFrameIndex]))
        ) {
            return 0;
        }

        const deltaTimeMs = (Number(timeSeries[toFrameIndex]) - Number(timeSeries[fromFrameIndex])) / 1000;
        return unwindingSpeed * deltaTimeMs;
    }

    getTrackedSegmentSpacingMM(frameIndex, accessor) {
        const metadata = this.data && this.data.metadata ? this.data.metadata : {};
        const metadataSegmentLen = Number(metadata.segment_len_mm);
        if (Number.isFinite(metadataSegmentLen) && metadataSegmentLen > 0) {
            return metadataSegmentLen;
        }

        const segmentCount = accessor.getLength(frameIndex);
        if (segmentCount < 2) {
            return null;
        }

        const sampleA = accessor.getPoint(frameIndex, 0);
        const sampleB = accessor.getPoint(frameIndex, 1);
        const spacing = Math.abs(sampleB - sampleA);
        return Number.isFinite(spacing) && spacing > 0 ? spacing : null;
    }

    estimateTrackedMaterialIndexShift(fromFrameIndex, toFrameIndex, segmentSpacingMM) {
        if (!Number.isFinite(segmentSpacingMM) || segmentSpacingMM <= 0) {
            return null;
        }

        const offsetSeries = this.data && this.data.wire_offset_mm;
        if (
            !offsetSeries ||
            !Number.isFinite(Number(offsetSeries[fromFrameIndex])) ||
            !Number.isFinite(Number(offsetSeries[toFrameIndex]))
        ) {
            return null;
        }

        const displacementMM = this.estimateTrackedMaterialDisplacementMM(fromFrameIndex, toFrameIndex);
        const offsetDeltaMM = Number(offsetSeries[toFrameIndex]) - Number(offsetSeries[fromFrameIndex]);
        return Math.round((displacementMM - offsetDeltaMM) / segmentSpacingMM);
    }

    setSelectedMaterialTracking(trace, anchorFrameIndex, anchorSegmentIndex) {
        this.selectedMaterialTrace = trace instanceof Map && trace.size > 0 ? trace : null;
        this.selectedMaterialAnchor = this.selectedMaterialTrace
            ? {
                frameIndex: anchorFrameIndex,
                segmentIndex: anchorSegmentIndex,
                position: null
            }
            : null;
        this.normalizeSelectedMaterialAnchor();
        this.damagePlotCache = null;
    }

    clearSelectedMaterialTracking() {
        this.selectedMaterialTrace = null;
        this.selectedMaterialAnchor = null;
        this.selectedSegmentClickIndex = null;
        this.damagePlotCache = null;
    }

    normalizeSelectedMaterialAnchor(accessor = this.getWireMaterialPositionAccessor()) {
        if (!this.selectedMaterialTrace || this.selectedMaterialTrace.size === 0 || !accessor) {
            this.selectedMaterialAnchor = null;
            return null;
        }

        let anchorFrameIndex = this.selectedMaterialAnchor?.frameIndex;
        let anchorSegmentIndex = this.selectedMaterialAnchor?.segmentIndex;

        if (!Number.isInteger(anchorFrameIndex) || !this.selectedMaterialTrace.has(anchorFrameIndex)) {
            anchorFrameIndex = null;
        }

        if (
            Number.isInteger(anchorFrameIndex) &&
            !Number.isInteger(anchorSegmentIndex)
        ) {
            anchorSegmentIndex = this.selectedMaterialTrace.get(anchorFrameIndex);
        }

        if (
            Number.isInteger(anchorFrameIndex) &&
            Number.isInteger(anchorSegmentIndex) &&
            anchorSegmentIndex >= 0 &&
            accessor.getLength(anchorFrameIndex) > anchorSegmentIndex
        ) {
            const anchorPosition = accessor.getPoint(anchorFrameIndex, anchorSegmentIndex);
            if (Number.isFinite(anchorPosition)) {
                this.selectedMaterialAnchor = {
                    frameIndex: anchorFrameIndex,
                    segmentIndex: anchorSegmentIndex,
                    position: anchorPosition
                };
                return this.selectedMaterialAnchor;
            }
        }

        const traceFrames = Array.from(this.selectedMaterialTrace.keys()).sort((a, b) => a - b);
        for (const frameIndex of traceFrames) {
            const segmentIndex = this.selectedMaterialTrace.get(frameIndex);
            if (
                !Number.isInteger(segmentIndex) ||
                segmentIndex < 0 ||
                accessor.getLength(frameIndex) <= segmentIndex
            ) {
                continue;
            }

            const anchorPosition = accessor.getPoint(frameIndex, segmentIndex);
            if (!Number.isFinite(anchorPosition)) {
                continue;
            }

            this.selectedMaterialAnchor = {
                frameIndex,
                segmentIndex,
                position: anchorPosition
            };
            return this.selectedMaterialAnchor;
        }

        this.selectedMaterialAnchor = null;
        return null;
    }

    findTrackedSegmentAtFrame(accessor, anchorFrameIndex, toFrameIndex, anchorIndex, anchorPosition) {
        const segmentCount = accessor.getLength(toFrameIndex);
        if (segmentCount <= 0 || !Number.isFinite(anchorPosition)) {
            return null;
        }

        const displacementMM = this.estimateTrackedMaterialDisplacementMM(anchorFrameIndex, toFrameIndex);
        const expectedPosition = anchorPosition + displacementMM;
        const segmentSpacingMM = this.getTrackedSegmentSpacingMM(toFrameIndex, accessor);
        const firstPosition = accessor.getPoint(toFrameIndex, 0);
        const lastPosition = accessor.getPoint(toFrameIndex, segmentCount - 1);
        const minPosition = Math.min(firstPosition, lastPosition);
        const maxPosition = Math.max(firstPosition, lastPosition);
        const boundaryTolerance = Number.isFinite(segmentSpacingMM) && segmentSpacingMM > 0
            ? Math.max(segmentSpacingMM, MATERIAL_TRACKING_FALLBACK_DISTANCE)
            : MATERIAL_TRACKING_FALLBACK_DISTANCE;
        if (
            !Number.isFinite(expectedPosition) ||
            !Number.isFinite(minPosition) ||
            !Number.isFinite(maxPosition) ||
            expectedPosition < minPosition - boundaryTolerance ||
            expectedPosition > maxPosition + boundaryTolerance
        ) {
            return null;
        }
        const predictedIndexShift = this.estimateTrackedMaterialIndexShift(
            anchorFrameIndex,
            toFrameIndex,
            segmentSpacingMM
        );
        const predictedIndex = Number.isInteger(predictedIndexShift)
            ? anchorIndex + predictedIndexShift
            : (
                Number.isFinite(segmentSpacingMM) && segmentSpacingMM > 0
                    ? anchorIndex + Math.round(displacementMM / segmentSpacingMM)
                    : anchorIndex
            );
        const boundaryIndexTolerance = 1;
        if (
            predictedIndex < -boundaryIndexTolerance ||
            predictedIndex > (segmentCount - 1 + boundaryIndexTolerance)
        ) {
            return null;
        }
        let bestIndex = -1;
        let bestDistance = Infinity;

        const searchRadius = MATERIAL_SEARCH_RADIUS;
        if (predictedIndex >= 0 && predictedIndex < segmentCount) {
            const startIndex = Math.max(0, predictedIndex - searchRadius);
            const endIndex = Math.min(segmentCount - 1, predictedIndex + searchRadius);

            for (let segmentIndex = startIndex; segmentIndex <= endIndex; segmentIndex++) {
                const distance = Math.abs(accessor.getPoint(toFrameIndex, segmentIndex) - expectedPosition);
                if (distance < bestDistance) {
                    bestDistance = distance;
                    bestIndex = segmentIndex;
                }
            }
        }

        if (bestIndex === -1 || bestDistance > MATERIAL_TRACKING_FALLBACK_DISTANCE) {
            for (let segmentIndex = 0; segmentIndex < segmentCount; segmentIndex++) {
                const distance = Math.abs(accessor.getPoint(toFrameIndex, segmentIndex) - expectedPosition);
                if (distance < bestDistance) {
                    bestDistance = distance;
                    bestIndex = segmentIndex;
                }
            }
        }

        const maxDistance = Number.isFinite(segmentSpacingMM) && segmentSpacingMM > 0
            ? Math.max(MATERIAL_TRACKING_MAX_DISTANCE, Math.abs(displacementMM) + (2 * segmentSpacingMM))
            : MATERIAL_TRACKING_MAX_DISTANCE;
        if (bestIndex === -1 || bestDistance >= maxDistance) {
            return null;
        }

        return {
            segmentIndex: bestIndex,
            position: accessor.getPoint(toFrameIndex, bestIndex)
        };
    }

    extendSelectedMaterialTraceToLatestFrame() {
        if (!this.selectedMaterialTrace || this.selectedMaterialTrace.size === 0) {
            return false;
        }

        const accessor = this.getWireMaterialPositionAccessor();
        if (!accessor) {
            return false;
        }
        const anchor = this.normalizeSelectedMaterialAnchor(accessor);
        if (!anchor) {
            return false;
        }

        const tracedFrames = Array.from(this.selectedMaterialTrace.keys()).sort((a, b) => a - b);
        if (tracedFrames.length === 0) {
            return false;
        }

        const latestAvailableFrame = this.getTotalFrames() - 1;
        let currentFrame = tracedFrames[tracedFrames.length - 1];
        if (currentFrame >= latestAvailableFrame) {
            return false;
        }

        let extended = false;
        for (let frameIndex = currentFrame + 1; frameIndex <= latestAvailableFrame; frameIndex++) {
            const match = this.findTrackedSegmentAtFrame(
                accessor,
                anchor.frameIndex,
                frameIndex,
                anchor.segmentIndex,
                anchor.position
            );
            if (!match) {
                break;
            }

            this.selectedMaterialTrace.set(frameIndex, match.segmentIndex);
            extended = true;
        }

        if (extended) {
            this.damagePlotCache = null;
        }

        return extended;
    }

    traceMaterial(startFrame, startSegmentIndex) {
        const trace = new Map();
        const accessor = this.getWireMaterialPositionAccessor();
        if (!accessor) return trace;

        const numFrames = this.getTotalFrames();

        if (accessor.getLength(startFrame) <= startSegmentIndex) return trace;
        const anchorPosition = accessor.getPoint(startFrame, startSegmentIndex);
        if (!Number.isFinite(anchorPosition)) return trace;

        trace.set(startFrame, startSegmentIndex);

        // Forward Trace
        for (let f = startFrame + 1; f < numFrames; f++) {
            const match = this.findTrackedSegmentAtFrame(
                accessor,
                startFrame,
                f,
                startSegmentIndex,
                anchorPosition
            );
            if (!match) {
                break;
            }

            trace.set(f, match.segmentIndex);
        }

        // Backward Trace
        for (let f = startFrame - 1; f >= 0; f--) {
            const match = this.findTrackedSegmentAtFrame(
                accessor,
                startFrame,
                f,
                startSegmentIndex,
                anchorPosition
            );
            if (!match) {
                break;
            }

            trace.set(f, match.segmentIndex);
        }

        return trace;
    }

    /**
     * Get segment ID - simply returns the index at the current frame.
     */
    getOriginalSegmentId(trace) {
        if (!trace || trace.size === 0 || !this.data) return null;

        // Just return the current index
        const currentFrame = this.currentFrame;
        if (trace.has(currentFrame)) {
            return trace.get(currentFrame);
        }

        // Fallback to earliest frame index
        const frames = Array.from(trace.keys()).sort((a, b) => a - b);
        return trace.get(frames[0]);
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

        // Link Side View horizontally with Top View
        this.panels.sideView.sharedCamera = this.panels.topView;

        Object.values(this.panels).forEach(panel => {
            panel.controller = this;
            panel.init();
        });

        // Initialize link button icon
        this.updateLinkViewsIcon();

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
        this.updateLinkViewsIcon();

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

    updateLinkViewsIcon() {
        const btn = this.elements.linkViews;
        if (this.viewsLinked) {
            // Linked icon (chain links connected)
            btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
            </svg>`;
            btn.style.color = 'var(--accent)';
        } else {
            // Unlinked icon (broken chain)
            btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
                <line x1="2" y1="2" x2="22" y2="22"/>
            </svg>`;
            btn.style.color = 'var(--text-muted)';
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

            this.setDataSource(new FileDashboardDataSource(this.data));
            this.currentFrame = 0;
            if (this.getTotalFrames() > 0) {
                this.drawFrame(0);
                this.updateTimeDisplay();
            }

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
        if (this.isLiveMode()) {
            return;
        }
        if (!this.data || this.getTotalFrames() === 0) {
            alert('Please load data first');
            return;
        }

        this.isPlaying = !this.isPlaying;
        this.updatePlayPauseIcon();

        if (this.isPlaying) {
            this.play();
        } else {
            this.pause();
        }
    }

    updatePlayPauseIcon() {
        const btn = this.elements.playPause;
        if (this.isPlaying) {
            // Pause icon (two vertical bars)
            btn.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="4" width="4" height="16"/>
                <rect x="14" y="4" width="4" height="16"/>
            </svg>`;
        } else {
            // Play icon (triangle)
            btn.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3"/>
            </svg>`;
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

                if (this.currentFrame >= this.getTotalFrames()) {
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
        if (this.isLiveMode()) {
            return;
        }
        this.pause();
        this.isPlaying = false;
        this.updatePlayPauseIcon();
        this.seekTo(0);
    }

    previousFrame() {
        if (this.isLiveMode()) return;
        if (!this.data) return;
        const frameStep = Math.max(1, Math.round(this.playbackSpeed / TARGET_FPS));
        const prevFrame = Math.max(this.currentFrame - frameStep, 0);
        this.seekToWithAccumulation(prevFrame);
    }

    nextFrame() {
        if (this.isLiveMode()) return;
        if (!this.data) return;
        const frameStep = Math.max(1, Math.round(this.playbackSpeed / TARGET_FPS));
        const nextFrame = Math.min(this.currentFrame + frameStep, this.getTotalFrames() - 1);
        this.seekToWithAccumulation(nextFrame);
    }

    seekTo(frame) {
        if (this.isLiveMode()) return;
        if (!this.data || this.getTotalFrames() === 0) return;

        this.currentFrame = Math.max(0, Math.min(frame, this.getTotalFrames() - 1));
        this.elements.timeline.value = this.currentFrame;
        this.drawFrame(this.currentFrame);
        this.updateTimeDisplay();
    }

    seekToWithAccumulation(targetFrame) {
        if (this.isLiveMode()) return;
        if (!this.data) return;

        const oldFrame = this.currentFrame;
        this.currentFrame = Math.max(0, Math.min(targetFrame, this.getTotalFrames() - 1));
        this.elements.timeline.value = this.currentFrame;

        if (this.currentFrame > oldFrame) {
            this.drawFrameWithAccumulatedSparks(oldFrame, this.currentFrame);
        } else {
            this.drawFrame(this.currentFrame);
        }

        this.updateTimeDisplay();
    }

    drawFrame(frameIndex, options = {}) {
        if (!this.data) return;

        const renderTimeMs = Number.isFinite(options.renderTimeMs) ? options.renderTimeMs : performance.now();
        const frameData = this.isLiveMode()
            ? this.getLiveRenderableFrameData(frameIndex, renderTimeMs)
            : this.getFrameData(frameIndex);

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
            const gapUM = (frameData.workpiece_position || 0) - (frameData.wire_position || 0);

            if (Array.isArray(frameData.spark_events) && frameData.spark_events.length > 0) {
                frameData.spark_events.forEach((sparkEvent) => {
                    accumulatedSparks.push({
                        locationMM: sparkEvent.locationMM,
                        frameIndex: f,
                        timeUS: sparkEvent.timeUS,
                        gapUM
                    });
                });
            } else if (frameData.spark_status && frameData.spark_status[0] === 1 && frameData.spark_status[1] !== null) {
                accumulatedSparks.push({
                    locationMM: frameData.spark_status[1],
                    frameIndex: f,
                    timeUS: Number(frameData.time),
                    gapUM
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
            totalFrames: this.getTotalFrames()
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
                    frameData[key] = value.data.subarray(start, end);
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

    ingestLiveSparks(frameIndex, renderTimeMs = performance.now()) {
        if (!this.data || frameIndex < 0) return;

        const frameData = this.getLiveRenderableFrameData(frameIndex, renderTimeMs);
        if (this.panels.sideView && this.panels.sideView.ingestSparkData) {
            this.panels.sideView.ingestSparkData(frameData, frameIndex);
        }
        if (this.panels.topView && this.panels.topView.ingestSparkData) {
            this.panels.topView.ingestSparkData(frameData, frameIndex);
        }
    }

    updateTimeDisplay() {
        if (!this.data) return;

        const currentTime = Number(this.data.time[this.currentFrame]) / 1000;
        const totalTime = Number(this.data.time[this.getTotalFrames() - 1]) / 1000;

        const formatTime = (ms) => {
            const seconds = Math.floor(ms / 1000);
            const milliseconds = Math.floor(ms % 1000);
            return `${String(seconds).padStart(2, '0')}:${String(milliseconds).padStart(3, '0')}`;
        };

        this.elements.frameCounter.textContent =
            `Frame: ${this.currentFrame + 1} / ${this.getTotalFrames()}`;

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
