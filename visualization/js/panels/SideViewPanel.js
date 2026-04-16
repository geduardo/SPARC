/**
 * Side View Panel
 * Displays wire, workpiece, nozzles, and sparks from a side perspective
 */

import { BasePanel } from './BasePanel.js';
import {
    DEFAULT_WIRE_DIAMETER,
    DEFAULT_WORKPIECE_THICKNESS,
    DEFAULT_ZOOM_LEVEL,
    BASE_SPARK_PERSISTENCE_FRAMES,
    SPARK_VISIBILITY_MS,
    TARGET_FPS,
    NOZZLE_WIDTH_MM,
    NOZZLE_HEIGHT_MM,
    NOZZLE_NARROW_MM,
    NOZZLE_BUFFER_DISTANCE_MM,
    VIEW_MARGIN_MM,
    COLORS
} from '../utils/constants.js';

export class SideViewPanel extends BasePanel {
    constructor(canvasId) {
        super(canvasId);

        // Default values
        this.wireDiameter = DEFAULT_WIRE_DIAMETER;
        this.workpieceThickness = DEFAULT_WORKPIECE_THICKNESS;

        // Shared camera with TopView (will be set by DashboardController)
        this.sharedCamera = null;

        // Independent camera for unlinked mode
        this.useIndependentCamera = false;
        this.independentZoomLevel = DEFAULT_ZOOM_LEVEL;
        this.independentCameraX = 0; // mm

        // Vertical camera offset (independent from TopView)
        this.cameraY = 0; // mm

        // Mouse interaction state
        this.isDragging = false;
        this.lastMouseX = 0;
        this.lastMouseY = 0;

        // Spark persistence tracking
        this.activeSparks = []; // Array of {locationMM, startFrame, intensity}
        this.baseSparkPersistenceFrames = BASE_SPARK_PERSISTENCE_FRAMES;
        this.lastFrameIndex = -1; // Track frame changes for detecting backward seeks
        this.lastProcessedSparkTimeUs = -Infinity;

        // Spark visibility toggle
        this.showSparks = true;

        // Setup controls
        this.setupControls();
    }

    ingestSparkData(frameData, frameIndex) {
        if (!frameData) return;

        if (frameIndex < this.lastFrameIndex) {
            this.activeSparks = [];
            this.lastProcessedSparkTimeUs = -Infinity;
        }
        this.lastFrameIndex = frameIndex;

        const liveRenderTimeMs = Number(frameData.liveRenderTimeMs);
        const isLiveRender = Number.isFinite(liveRenderTimeMs);

        if (frameData.accumulatedSparks && frameData.accumulatedSparks.length > 0) {
            frameData.accumulatedSparks.forEach(spark => {
                if (!Number.isFinite(spark.timeUS) || spark.timeUS > this.lastProcessedSparkTimeUs) {
                    this.activeSparks.push({
                        locationMM: spark.locationMM,
                        startFrame: spark.frameIndex,
                        startRenderTimeMs: isLiveRender ? liveRenderTimeMs : null,
                        intensity: 1.0
                    });
                    if (Number.isFinite(spark.timeUS)) {
                        this.lastProcessedSparkTimeUs = Math.max(this.lastProcessedSparkTimeUs, spark.timeUS);
                    }
                }
            });
        }

        if (Array.isArray(frameData.spark_events) && frameData.spark_events.length > 0) {
            frameData.spark_events.forEach((sparkEvent) => {
                if (!Number.isFinite(sparkEvent.timeUS) || sparkEvent.timeUS > this.lastProcessedSparkTimeUs) {
                    this.activeSparks.push({
                        locationMM: sparkEvent.locationMM,
                        startFrame: frameIndex,
                        startRenderTimeMs: isLiveRender ? liveRenderTimeMs : null,
                        intensity: 1.0
                    });
                    if (Number.isFinite(sparkEvent.timeUS)) {
                        this.lastProcessedSparkTimeUs = Math.max(this.lastProcessedSparkTimeUs, sparkEvent.timeUS);
                    }
                }
            });
        } else if (frameData.spark_status && frameData.spark_status[0] === 1 && frameData.spark_status[1] !== null) {
            const sparkLocationMM = frameData.spark_status[1];
            const sparkSeed = Number.isFinite(frameData.time) ? Number(frameData.time) : frameIndex;
            if (sparkSeed > this.lastProcessedSparkTimeUs) {
                this.activeSparks.push({
                    locationMM: sparkLocationMM,
                    startFrame: frameIndex,
                    startRenderTimeMs: isLiveRender ? liveRenderTimeMs : null,
                    intensity: 1.0
                });
                this.lastProcessedSparkTimeUs = Math.max(this.lastProcessedSparkTimeUs, sparkSeed);
            }
        }
    }

    onHistoryTrim(droppedFrames) {
        if (!Number.isFinite(droppedFrames) || droppedFrames <= 0) return;

        this.activeSparks = this.activeSparks
            .map((spark) => ({
                ...spark,
                startFrame: spark.startFrame - droppedFrames
            }))
            .filter((spark) => spark.startFrame >= 0);
        this.lastFrameIndex = Math.max(-1, this.lastFrameIndex - droppedFrames);
        if (this.activeSparks.length === 0) {
            this.lastProcessedSparkTimeUs = -Infinity;
        }
    }

    setData(data) {
        super.setData(data);
        this.activeSparks = [];
        this.lastFrameIndex = -1;
        this.lastProcessedSparkTimeUs = -Infinity;

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
    }

    setupControls() {
        // Mouse wheel for zoom
        this.canvas.addEventListener('wheel', (e) => {
            e.preventDefault();

            const zoomDelta = e.deltaY > 0 ? 1.2 : 0.8;

            if (this.useIndependentCamera) {
                this.independentZoomLevel *= zoomDelta;
                const minViewHeight = (this.workpieceThickness / 2) + NOZZLE_BUFFER_DISTANCE_MM + VIEW_MARGIN_MM;
                const maxZoom = minViewHeight / this.wireDiameter;
                this.independentZoomLevel = Math.max(0.05, Math.min(maxZoom, this.independentZoomLevel));
            } else if (this.sharedCamera) {
                this.sharedCamera.zoomLevel *= zoomDelta;
                const minViewHeight = (this.workpieceThickness / 2) + NOZZLE_BUFFER_DISTANCE_MM + VIEW_MARGIN_MM;
                const maxZoom = minViewHeight / this.wireDiameter;
                this.sharedCamera.zoomLevel = Math.max(0.05, Math.min(maxZoom, this.sharedCamera.zoomLevel));
            }

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

                const zoomLevel = this.useIndependentCamera ? this.independentZoomLevel :
                    (this.sharedCamera ? this.sharedCamera.zoomLevel : DEFAULT_ZOOM_LEVEL);
                const w = this.canvas.width / window.devicePixelRatio;
                const viewWidth = this.wireDiameter * zoomLevel;
                const scale = (w * 0.8) / viewWidth;

                const deltaY_mm = dy / scale;
                this.cameraY -= deltaY_mm;

                if (this.useIndependentCamera) {
                    this.independentCameraX -= dx / scale;
                }

                this.lastMouseX = e.offsetX;
                this.lastMouseY = e.offsetY;

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
                this.independentZoomLevel = DEFAULT_ZOOM_LEVEL;
            }

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
        this.ctx.fillStyle = COLORS.bgCanvas;
        this.ctx.fillRect(0, 0, w, h);

        if (!frameData) {
            this.drawText('Side View', w / 2, h / 2, {
                color: COLORS.textMuted,
                font: 'bold 16px sans-serif',
                align: 'center',
                baseline: 'middle'
            });
            return;
        }

        // Get camera position
        const cameraX = this.useIndependentCamera ? this.independentCameraX :
            (this.sharedCamera ? this.sharedCamera.cameraX : 0);
        const zoomLevel = this.useIndependentCamera ? this.independentZoomLevel :
            (this.sharedCamera ? this.sharedCamera.zoomLevel : DEFAULT_ZOOM_LEVEL);

        // Scale calculation
        const viewWidth = this.wireDiameter * zoomLevel;
        const scale = (w * 0.8) / viewWidth;

        // Wire position
        const wireEdgePos = frameData.wire_position || 0;
        const wireRadius = this.wireDiameter / 2;
        const wireCenterX = (wireEdgePos / 1000) - wireRadius;

        // Draw static water background
        this.drawWaterScreen(w, h);

        this.ctx.save();
        this.ctx.translate(w / 2, h / 2);
        this.ctx.translate(-cameraX * scale, -this.cameraY * scale);

        const workpieceEdgePos = frameData.workpiece_position || 0;
        const workpieceEdgeX = workpieceEdgePos / 1000;

        this.drawCutMaterial(workpieceEdgeX, scale, h);
        this.drawWorkpiece(workpieceEdgeX, scale, h);
        this.drawNozzles(wireCenterX, wireRadius, scale);
        this.drawWire(wireCenterX, wireRadius, scale, frameData);

        // Handle spark persistence
        this.ingestSparkData(frameData, frameIndex);
        const liveRenderTimeMs = Number(frameData.liveRenderTimeMs);
        const isLiveRender = Number.isFinite(liveRenderTimeMs);

        const playbackSpeed = this.controller ? this.controller.playbackSpeed : TARGET_FPS;
        const framesPerDisplayFrame = Math.max(1, Math.round(playbackSpeed / TARGET_FPS));
        const sparkPersistenceFrames = Math.max(this.baseSparkPersistenceFrames, framesPerDisplayFrame * 12);
        const sparkPersistenceMs = SPARK_VISIBILITY_MS;

        this.activeSparks = this.activeSparks.filter((spark) => {
            if (isLiveRender && Number.isFinite(spark.startRenderTimeMs)) {
                return (liveRenderTimeMs - spark.startRenderTimeMs) < sparkPersistenceMs;
            }
            return (frameIndex - spark.startFrame) < sparkPersistenceFrames;
        });

        if (this.showSparks) {
            const gap = (frameData.workpiece_position || 0) - (frameData.wire_position || 0);
            this.activeSparks.forEach(spark => {
                let decayFactor;
                if (isLiveRender && Number.isFinite(spark.startRenderTimeMs)) {
                    const ageMs = liveRenderTimeMs - spark.startRenderTimeMs;
                    decayFactor = 1.0 - (ageMs / sparkPersistenceMs);
                } else {
                    const age = frameIndex - spark.startFrame;
                    decayFactor = 1.0 - (age / sparkPersistenceFrames);
                }
                this.drawSpark(wireCenterX, wireRadius, workpieceEdgeX, scale, spark.locationMM, gap, decayFactor);
            });
        }

        this.ctx.restore();
        this.drawInfoOverlay(w, h, frameData);
    }

    drawWorkpiece(workpieceEdgeX, scale, canvasHeight) {
        const maxDim = canvasHeight * 2;
        const workpieceHalfThickness = (this.workpieceThickness / 2) * scale;
        const workpieceEdgeXPx = workpieceEdgeX * scale;

        this.ctx.fillStyle = COLORS.workpiece;
        this.ctx.fillRect(
            workpieceEdgeXPx,
            -workpieceHalfThickness,
            maxDim * 4,
            this.workpieceThickness * scale
        );

        this.ctx.strokeStyle = COLORS.workpieceStroke;
        this.ctx.lineWidth = 2.5;
        this.ctx.beginPath();
        this.ctx.moveTo(workpieceEdgeXPx, -workpieceHalfThickness);
        this.ctx.lineTo(workpieceEdgeXPx, workpieceHalfThickness);
        this.ctx.stroke();

        this.ctx.lineWidth = 2;
        this.ctx.beginPath();
        this.ctx.moveTo(workpieceEdgeXPx, -workpieceHalfThickness);
        this.ctx.lineTo(workpieceEdgeXPx + maxDim * 4, -workpieceHalfThickness);
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.moveTo(workpieceEdgeXPx, workpieceHalfThickness);
        this.ctx.lineTo(workpieceEdgeXPx + maxDim * 4, workpieceHalfThickness);
        this.ctx.stroke();

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
        this.ctx.fillStyle = COLORS.water;
        this.ctx.fillRect(0, 0, canvasWidth, canvasHeight);
    }

    drawCutMaterial(workpieceEdgeX, scale, canvasHeight) {
        const maxDim = canvasHeight * 2;
        const workpieceHalfThickness = (this.workpieceThickness / 2) * scale;
        const workpieceEdgeXPx = workpieceEdgeX * scale;

        this.ctx.fillStyle = 'rgba(192, 192, 192, 0.3)';
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

        this.ctx.fillStyle = '#d79921';
        this.ctx.fillRect(
            wireCenterXPx - radiusPx,
            -workpieceHalfThickness - radiusPx,
            radiusPx * 2,
            (workpieceHalfThickness * 2) + (radiusPx * 2)
        );

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

        const wireTopEnd = -workpieceHalfThickness - radiusPx;
        const wireBottomEnd = workpieceHalfThickness + radiusPx;

        const nozzleWidth = NOZZLE_WIDTH_MM * scale;
        const nozzleHeight = NOZZLE_HEIGHT_MM * scale;
        const nozzleTopWidth = NOZZLE_NARROW_MM * scale;

        // Upper nozzle
        this.ctx.fillStyle = '#7c6f64';
        this.ctx.beginPath();
        this.ctx.moveTo(wireCenterXPx - nozzleWidth / 2, wireTopEnd - nozzleHeight);
        this.ctx.lineTo(wireCenterXPx + nozzleWidth / 2, wireTopEnd - nozzleHeight);
        this.ctx.lineTo(wireCenterXPx + nozzleTopWidth / 2, wireTopEnd);
        this.ctx.lineTo(wireCenterXPx - nozzleTopWidth / 2, wireTopEnd);
        this.ctx.closePath();
        this.ctx.fill();

        this.ctx.strokeStyle = '#504945';
        this.ctx.lineWidth = 1.5;
        this.ctx.stroke();

        // Upper black rectangle
        const extensionLength = 100.0 * scale;
        const upperRectTop = wireTopEnd - nozzleHeight;
        this.ctx.fillStyle = '#000000';
        this.ctx.fillRect(
            wireCenterXPx - nozzleWidth / 2,
            upperRectTop - extensionLength,
            nozzleWidth,
            extensionLength
        );
        this.ctx.strokeStyle = '#1d2021';
        this.ctx.lineWidth = 1.5;
        this.ctx.strokeRect(
            wireCenterXPx - nozzleWidth / 2,
            upperRectTop - extensionLength,
            nozzleWidth,
            extensionLength
        );

        // Lower nozzle
        this.ctx.fillStyle = '#7c6f64';
        this.ctx.beginPath();
        this.ctx.moveTo(wireCenterXPx - nozzleWidth / 2, wireBottomEnd + nozzleHeight);
        this.ctx.lineTo(wireCenterXPx + nozzleWidth / 2, wireBottomEnd + nozzleHeight);
        this.ctx.lineTo(wireCenterXPx + nozzleTopWidth / 2, wireBottomEnd);
        this.ctx.lineTo(wireCenterXPx - nozzleTopWidth / 2, wireBottomEnd);
        this.ctx.closePath();
        this.ctx.fill();

        this.ctx.strokeStyle = '#504945';
        this.ctx.lineWidth = 1.5;
        this.ctx.stroke();

        // Lower black rectangle
        const lowerRectBottom = wireBottomEnd + nozzleHeight;
        this.ctx.fillStyle = '#000000';
        this.ctx.fillRect(
            wireCenterXPx - nozzleWidth / 2,
            lowerRectBottom,
            nozzleWidth,
            extensionLength
        );
        this.ctx.strokeStyle = '#1d2021';
        this.ctx.lineWidth = 1.5;
        this.ctx.strokeRect(
            wireCenterXPx - nozzleWidth / 2,
            lowerRectBottom,
            nozzleWidth,
            extensionLength
        );
    }

    drawSpark(wireCenterX, wireRadius, workpieceEdgeX, scale, sparkLocationMM, gapUM, decayFactor) {
        const wireCenterXPx = wireCenterX * scale;
        const radiusPx = wireRadius * scale;
        const wireRightEdge = wireCenterXPx + radiusPx;

        const minSparkLengthUM = 50.0;
        const actualGapMM = gapUM / 1000.0;
        const minSparkLengthMM = minSparkLengthUM / 1000.0;
        const sparkLengthMM = Math.max(actualGapMM, minSparkLengthMM);
        const sparkEndX = wireRightEdge + (sparkLengthMM * scale);

        const thicknessMM = this.workpieceThickness;
        const workpieceHalfThickness = thicknessMM / 2;
        const sparkY = (sparkLocationMM - workpieceHalfThickness) * scale;

        const brightness = decayFactor;
        const alpha = Math.pow(brightness, 0.5);

        const sparkVerticalMM = 0.1;
        const sparkVerticalPx = sparkVerticalMM * scale;
        const sparkHorizontalScaledPx = sparkVerticalMM * scale;
        const sparkHorizontalFixedPx = Math.max(3.0, sparkHorizontalScaledPx);

        // Layer 1: Wide outer glow
        this.ctx.strokeStyle = `rgba(150, 200, 255, ${alpha * 0.2})`;
        this.ctx.lineWidth = sparkHorizontalFixedPx * 5.0;
        this.ctx.shadowBlur = 20;
        this.ctx.shadowColor = `rgba(180, 220, 255, ${alpha * 0.3})`;
        this.ctx.lineCap = 'round';
        this.ctx.beginPath();
        this.ctx.moveTo(wireRightEdge, sparkY);
        this.ctx.lineTo(sparkEndX, sparkY);
        this.ctx.stroke();

        // Layer 2: Medium glow
        this.ctx.strokeStyle = `rgba(200, 230, 255, ${alpha * 0.4})`;
        this.ctx.lineWidth = sparkHorizontalFixedPx * 3.0;
        this.ctx.shadowBlur = 15;
        this.ctx.shadowColor = `rgba(220, 240, 255, ${alpha * 0.5})`;
        this.ctx.beginPath();
        this.ctx.moveTo(wireRightEdge, sparkY);
        this.ctx.lineTo(sparkEndX, sparkY);
        this.ctx.stroke();

        // Layer 3: Bright core
        this.ctx.strokeStyle = `rgba(255, 255, 255, ${alpha})`;
        this.ctx.lineWidth = sparkHorizontalFixedPx * 0.8;
        this.ctx.shadowBlur = 8;
        this.ctx.shadowColor = `rgba(255, 255, 255, ${alpha})`;
        this.ctx.beginPath();
        this.ctx.moveTo(wireRightEdge, sparkY);
        this.ctx.lineTo(sparkEndX, sparkY);
        this.ctx.stroke();

        this.ctx.shadowBlur = 0;
    }

    drawInfoOverlay(w, h, frameData) {
        const padding = 10;
        const lineHeight = 16;
        let y = padding;

        const wireEdgePos = frameData.wire_position || 0;
        const workpieceEdgePos = frameData.workpiece_position || 0;
        const gap = workpieceEdgePos - wireEdgePos;

        this.drawText(`Wire D: ${this.wireDiameter.toFixed(3)} mm`, padding, y, { color: COLORS.textMuted, font: '11px monospace' });
        y += lineHeight;

        this.drawText(`Wire Pos: ${wireEdgePos.toFixed(1)} um`, padding, y, { color: COLORS.textMuted, font: '11px monospace' });
        y += lineHeight;

        this.drawText(`WP Pos: ${workpieceEdgePos.toFixed(1)} um`, padding, y, { color: COLORS.textMuted, font: '11px monospace' });
        y += lineHeight;

        this.drawText(`Gap: ${gap.toFixed(1)} um`, padding, y, { color: COLORS.textMuted, font: '11px monospace' });
        y += lineHeight;

        this.drawText(`WP Thickness: ${this.workpieceThickness.toFixed(1)} mm`, padding, y, { color: COLORS.textMuted, font: '11px monospace' });
        y += lineHeight;

        if (frameData.debris_density !== undefined) {
            const debrisPercent = (frameData.debris_density * 100).toFixed(1);
            this.drawText(`Debris: ${debrisPercent}%`, padding, y, { color: COLORS.textMuted, font: '11px monospace' });
        }
    }
}
