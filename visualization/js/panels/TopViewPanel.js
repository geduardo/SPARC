/**
 * Top View Panel
 * Displays wire, kerf, and workpiece from above
 */

import { BasePanel } from './BasePanel.js';
import {
    DEFAULT_WIRE_DIAMETER,
    DEFAULT_ZOOM_LEVEL,
    BASE_SPARK_PERSISTENCE_FRAMES,
    TARGET_FPS,
    COLORS
} from '../utils/constants.js';

export class TopViewPanel extends BasePanel {
    constructor(canvasId) {
        super(canvasId);

        // Default values
        this.wireDiameter = DEFAULT_WIRE_DIAMETER;
        this.initialGap = 50.0; // um

        // Visualization parameters
        this.scale = 1.0;
        this.cameraX = 0;
        this.zoomLevel = 15.0; // Start with wider view
        this.autoPan = true;

        // Mouse interaction state
        this.isDragging = false;
        this.lastMouseX = 0;
        this.lastMouseY = 0;

        // Spark persistence tracking
        this.activeSparks = [];
        this.baseSparkPersistenceFrames = BASE_SPARK_PERSISTENCE_FRAMES;
        this.lastFrameIndex = -1;

        // Spark angle map
        this.sparkAngles = new Map();

        // Spark visibility toggle
        this.showSparks = true;

        this.setupControls();
    }

    setupControls() {
        this.canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const zoomDelta = e.deltaY > 0 ? 1.2 : 0.8;
            this.zoomLevel *= zoomDelta;
            this.zoomLevel = Math.max(0.05, Math.min(10000, this.zoomLevel));

            if (this.controller && this.controller.data) {
                this.controller.drawFrame(this.controller.currentFrame);
            }
        });

        this.canvas.addEventListener('mousedown', (e) => {
            this.isDragging = true;
            this.autoPan = false;
            this.lastMouseX = e.offsetX;
            this.lastMouseY = e.offsetY;
            this.canvas.style.cursor = 'grabbing';
        });

        this.canvas.addEventListener('mousemove', (e) => {
            if (this.isDragging) {
                const dx = e.offsetX - this.lastMouseX;
                this.cameraX -= dx / this.scale;
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

        this.canvas.addEventListener('dblclick', () => {
            this.zoomLevel = 15.0;
            this.autoPan = true;
            this.cameraX = 0;

            if (this.controller && this.controller.data) {
                this.controller.drawFrame(this.controller.currentFrame);
            }
        });
    }

    setData(data) {
        super.setData(data);

        if (data.metadata) {
            this.wireDiameter = data.metadata.wire_diameter || DEFAULT_WIRE_DIAMETER;
            this.initialGap = data.metadata.initial_gap || 50.0;
            this.baseOvercut = data.metadata.base_overcut || 0.030;

            if (data.metadata.workpiece_height_mm !== undefined) {
                this.workpieceHeightMM = data.metadata.workpiece_height_mm;
            } else if (data.metadata.workpiece_height !== undefined) {
                this.workpieceHeightMM = data.metadata.workpiece_height;
            } else {
                this.workpieceHeightMM = 20.0;
            }
        }

        this.precomputeSparkAngles(data);
    }

    precomputeSparkAngles(data) {
        this.sparkAngles = new Map();

        if (!data) return;
        const hasLegacySpark = Array.isArray(data.spark_status);
        const hasSplitSpark = (data.spark_status_state && (Array.isArray(data.spark_status_state) || ArrayBuffer.isView(data.spark_status_state))) &&
            (data.spark_status_location_mm && (Array.isArray(data.spark_status_location_mm) || ArrayBuffer.isView(data.spark_status_location_mm)));
        if (!hasLegacySpark && !hasSplitSpark) return;
        if (!data.wire_position || !data.workpiece_position) return;

        const baseOvercutPerSideUM = (this.baseOvercut || 0.026) * 1000;
        const threshold = baseOvercutPerSideUM;
        const transitionRange = 5.0;

        const sampleAngle = (gapUM) => {
            let pSides;

            if (gapUM < threshold - transitionRange) {
                pSides = 0.0;
            } else if (gapUM > threshold + transitionRange) {
                pSides = 1.0;
            } else {
                pSides = (gapUM - (threshold - transitionRange)) / (2 * transitionRange);
                pSides = Math.max(0, Math.min(1, pSides));
            }

            const useSidesMode = Math.random() < pSides;
            let angle;

            if (useSidesMode) {
                const u = Math.random();
                const k = 20.0;
                const pole = Math.random() < 0.5 ? Math.PI / 2 : -Math.PI / 2;
                let offset;
                if (u < 0.5) {
                    offset = -Math.log(1 - 2 * u * (1 - Math.exp(-k * Math.PI / 2))) / k;
                } else {
                    offset = Math.log(2 * (u - 0.5) * (1 - Math.exp(-k * Math.PI / 2)) + Math.exp(-k * Math.PI / 2)) / k;
                }
                angle = pole + offset;
                if (angle > Math.PI) angle -= 2 * Math.PI;
                if (angle < -Math.PI) angle += 2 * Math.PI;
            } else {
                const u = Math.random();
                const k = 5.0;
                if (u < 0.5) {
                    angle = -Math.log(1 - 2 * u * (1 - Math.exp(-k * Math.PI / 2))) / k;
                } else {
                    angle = Math.log(2 * (u - 0.5) * (1 - Math.exp(-k * Math.PI / 2)) + Math.exp(-k * Math.PI / 2)) / k;
                }
                angle = Math.max(-Math.PI / 2 + 0.001, Math.min(Math.PI / 2 - 0.001, angle));
            }

            return angle;
        };

        const totalFrames = data.time ? data.time.length : (hasLegacySpark ? data.spark_status.length : data.spark_status_state.length);
        if (hasLegacySpark) {
            data.spark_status.forEach((status, frameIndex) => {
                if (status && status[0] === 1 && status[1] !== null) {
                    const wirePos = data.wire_position[frameIndex] || 0;
                    const workpiecePos = data.workpiece_position[frameIndex] || 0;
                    const gapUM = workpiecePos - wirePos;
                    const angle = sampleAngle(gapUM);
                    this.sparkAngles.set(frameIndex, angle);
                }
            });
        } else if (hasSplitSpark) {
            const s = data.spark_status_state;
            for (let frameIndex = 0; frameIndex < totalFrames; frameIndex++) {
                const state = s[frameIndex];
                if (state === 1) {
                    const wirePos = data.wire_position[frameIndex] || 0;
                    const workpiecePos = data.workpiece_position[frameIndex] || 0;
                    const gapUM = workpiecePos - wirePos;
                    const angle = sampleAngle(gapUM);
                    this.sparkAngles.set(frameIndex, angle);
                }
            }
        }
    }

    draw(frameData, frameIndex) {
        this.clear();

        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;

        // Background
        this.ctx.fillStyle = COLORS.bgCanvas;
        this.ctx.fillRect(0, 0, w, h);

        // Auto-scale based on zoom level
        const viewWidth = this.wireDiameter * this.zoomLevel;
        this.scale = (w * 0.8) / viewWidth;

        if (!frameData) {
            this.drawText('Top View - No Data', w / 2, h / 2, {
                color: COLORS.textMuted,
                font: '14px sans-serif',
                align: 'center',
                baseline: 'middle'
            });
            return;
        }

        const wireEdgePos = frameData.wire_position || 0;
        const workpieceEdgePos = frameData.workpiece_position || 0;
        const wireRadius = this.wireDiameter / 2;
        const kerfWidth = ((this.baseOvercut || 0.05)) + this.wireDiameter + 0.01;
        const frontierRadius = kerfWidth / 2;
        const wireCenterX = (wireEdgePos / 1000) - wireRadius;
        const frontierCenterX = (workpieceEdgePos / 1000) - frontierRadius;
        const gapUM = workpieceEdgePos - wireEdgePos;

        // Auto-pan
        if (this.autoPan) {
            const wireScreenX = (wireCenterX - this.cameraX) * this.scale + w / 2;
            const edgeThreshold = w * 0.1;

            if (wireScreenX < edgeThreshold) {
                this.cameraX = wireCenterX - (edgeThreshold / this.scale) + (w / 2 / this.scale);
            } else if (wireScreenX > w - edgeThreshold) {
                this.cameraX = wireCenterX + (edgeThreshold / this.scale) - (w / 2 / this.scale);
            }
        }

        this.ctx.save();
        this.ctx.translate(w / 2, h / 2);
        this.ctx.translate(-this.cameraX * this.scale, 0);

        // Handle spark persistence
        if (frameIndex < this.lastFrameIndex) {
            this.activeSparks = [];
        }
        this.lastFrameIndex = frameIndex;

        if (frameData.accumulatedSparks && frameData.accumulatedSparks.length > 0) {
            frameData.accumulatedSparks.forEach(spark => {
                this.activeSparks.push({
                    locationMM: spark.locationMM,
                    startFrame: spark.frameIndex,
                    intensity: 1.0
                });
            });
        }

        if (frameData.spark_status && frameData.spark_status[0] === 1 && frameData.spark_status[1] !== null) {
            const sparkLocationMM = frameData.spark_status[1];
            this.activeSparks.push({
                locationMM: sparkLocationMM,
                startFrame: frameIndex,
                intensity: 1.0
            });
        }

        const playbackSpeed = this.controller ? this.controller.playbackSpeed : TARGET_FPS;
        const framesPerDisplayFrame = Math.max(1, Math.round(playbackSpeed / TARGET_FPS));
        const sparkPersistenceFrames = Math.max(this.baseSparkPersistenceFrames, framesPerDisplayFrame * 12);

        this.activeSparks = this.activeSparks.filter(
            spark => (frameIndex - spark.startFrame) < sparkPersistenceFrames
        );

        // Draw layers
        this.drawKerf(wireCenterX, wireRadius, frontierCenterX, frontierRadius);

        if (this.showSparks) {
            this.activeSparks.forEach(spark => {
                const age = frameIndex - spark.startFrame;
                const decayFactor = 1.0 - (age / sparkPersistenceFrames);
                this.drawSpark(wireCenterX, wireRadius, spark.locationMM, gapUM, decayFactor, spark.startFrame);
            });
        }

        this.drawWorkpiece(frontierCenterX, frontierRadius, wireCenterX, wireRadius);
        this.drawWire(wireCenterX, wireRadius, frameData);

        this.ctx.restore();
        this.drawInfoOverlay(w, h, gapUM, wireEdgePos, workpieceEdgePos, frontierRadius, frameData);
    }

    drawWire(wireX, wireRadius, frameData) {
        const wireCenterX = wireX * this.scale;
        const radiusPx = wireRadius * this.scale;

        this.ctx.fillStyle = '#d79921';
        this.ctx.beginPath();
        this.ctx.arc(wireCenterX, 0, radiusPx, 0, Math.PI * 2);
        this.ctx.fill();

        this.ctx.strokeStyle = '#b57614';
        this.ctx.lineWidth = 1.5;
        this.ctx.stroke();

        if (frameData.wire_average_temperature) {
            const tempC = frameData.wire_average_temperature - 273.15;
            const tempRatio = Math.min(tempC / 500, 1);

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
        const frontierCenterXPx = frontierCenterX * this.scale;
        const frontierRadiusPx = frontierRadius * this.scale;
        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;
        const maxDim = Math.max(w, h) * 2;
        const cutChannelHalfHeight = frontierRadiusPx;

        this.ctx.fillStyle = COLORS.water;
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
        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;
        const maxDim = Math.max(w, h) * 2;
        const cutChannelHalfHeight = frontierRadiusPx;
        const blockThickness = maxDim;

        this.ctx.fillStyle = COLORS.workpiece;

        // Top block
        this.ctx.fillRect(
            -maxDim,
            cutChannelHalfHeight,
            frontierCenterXPx + maxDim + maxDim,
            blockThickness
        );

        // Bottom block
        this.ctx.fillRect(
            -maxDim,
            -cutChannelHalfHeight - blockThickness,
            frontierCenterXPx + maxDim + maxDim,
            blockThickness
        );

        // Frontier face
        this.ctx.beginPath();
        this.ctx.arc(frontierCenterXPx, 0, frontierRadiusPx, -Math.PI / 2, Math.PI / 2);
        this.ctx.lineTo(frontierCenterXPx + maxDim, frontierRadiusPx);
        this.ctx.lineTo(frontierCenterXPx + maxDim, -frontierRadiusPx);
        this.ctx.closePath();
        this.ctx.fill();

        // Draw edges
        this.ctx.strokeStyle = COLORS.workpieceStroke;
        this.ctx.lineWidth = 2.5;

        this.ctx.beginPath();
        this.ctx.moveTo(-maxDim, cutChannelHalfHeight);
        this.ctx.lineTo(frontierCenterXPx, cutChannelHalfHeight);
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.moveTo(-maxDim, -cutChannelHalfHeight);
        this.ctx.lineTo(frontierCenterXPx, -cutChannelHalfHeight);
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.arc(frontierCenterXPx, 0, frontierRadiusPx, -Math.PI / 2, Math.PI / 2);
        this.ctx.stroke();

        // Texture lines
        this.ctx.strokeStyle = 'rgba(60, 56, 54, 0.15)';
        this.ctx.lineWidth = 0.5;
        const gridSpacing = 10 * this.scale;

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
        const angle = this.sparkAngles.get(sparkFrameIndex) || 0;

        const extensionFactor = 0.4;
        const sparkStartRadiusMM = -wireRadius * extensionFactor;
        const gapMM = gapUM / 1000.0;
        const sparkEndRadiusMM = wireRadius + gapMM + wireRadius * extensionFactor;

        const sparkStartX = wireCenterXPx + (sparkStartRadiusMM * this.scale) * Math.cos(angle);
        const sparkStartY = (sparkStartRadiusMM * this.scale) * Math.sin(angle);
        const sparkEndX = wireCenterXPx + (sparkEndRadiusMM * this.scale) * Math.cos(angle);
        const sparkEndY = (sparkEndRadiusMM * this.scale) * Math.sin(angle);

        const sparkDiameter = 0.04;
        const sparkRadiusPx = (sparkDiameter / 2) * this.scale;
        const brightness = decayFactor;
        const alpha = Math.pow(brightness, 0.5);

        this.ctx.lineCap = 'butt';

        // Layer 1
        this.ctx.strokeStyle = `rgba(150, 200, 255, ${alpha * 0.4})`;
        this.ctx.lineWidth = sparkRadiusPx * 2 * 3.0;
        this.ctx.shadowBlur = 15;
        this.ctx.shadowColor = `rgba(180, 220, 255, ${alpha * 0.8})`;
        this.ctx.beginPath();
        this.ctx.moveTo(sparkStartX, sparkStartY);
        this.ctx.lineTo(sparkEndX, sparkEndY);
        this.ctx.stroke();

        // Layer 2
        this.ctx.strokeStyle = `rgba(200, 230, 255, ${alpha * 0.7})`;
        this.ctx.lineWidth = sparkRadiusPx * 2 * 2.0;
        this.ctx.shadowBlur = 10;
        this.ctx.shadowColor = `rgba(220, 240, 255, ${alpha})`;
        this.ctx.beginPath();
        this.ctx.moveTo(sparkStartX, sparkStartY);
        this.ctx.lineTo(sparkEndX, sparkEndY);
        this.ctx.stroke();

        // Layer 3
        this.ctx.strokeStyle = `rgba(240, 250, 255, ${alpha * 0.95})`;
        this.ctx.lineWidth = sparkRadiusPx * 2;
        this.ctx.shadowBlur = 5;
        this.ctx.shadowColor = `rgba(255, 255, 255, ${alpha})`;
        this.ctx.beginPath();
        this.ctx.moveTo(sparkStartX, sparkStartY);
        this.ctx.lineTo(sparkEndX, sparkEndY);
        this.ctx.stroke();

        this.ctx.shadowBlur = 0;
        this.ctx.lineCap = 'round';
    }

    drawInfoOverlay(w, h, gap, wirePos, workpiecePos, frontierRadius, frameData) {
        const padding = 10;

        // Scale reference
        let scaleBarLength, scaleBarLabel;
        if (this.zoomLevel < 2.0) {
            scaleBarLength = 1.0;
            scaleBarLabel = '1 mm';
        } else {
            scaleBarLength = 0.1;
            scaleBarLabel = '100 um';
        }

        const scaleBarLengthPx = scaleBarLength * this.scale;
        const scaleBarX = w - padding - scaleBarLengthPx;
        const scaleBarY = h - padding - 20;

        this.ctx.strokeStyle = COLORS.textMuted;
        this.ctx.lineWidth = 2;
        this.ctx.beginPath();
        this.ctx.moveTo(scaleBarX, scaleBarY);
        this.ctx.lineTo(scaleBarX + scaleBarLengthPx, scaleBarY);
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.moveTo(scaleBarX, scaleBarY - 3);
        this.ctx.lineTo(scaleBarX, scaleBarY + 3);
        this.ctx.moveTo(scaleBarX + scaleBarLengthPx, scaleBarY - 3);
        this.ctx.lineTo(scaleBarX + scaleBarLengthPx, scaleBarY + 3);
        this.ctx.stroke();

        this.drawText(scaleBarLabel, scaleBarX + scaleBarLengthPx / 2, scaleBarY + 10, {
            color: COLORS.textMuted,
            font: '10px sans-serif',
            align: 'center'
        });

        const hintsY = h - padding - 30;
        this.drawText('Scroll: Zoom | Drag: Pan | Double-click: Reset', padding, hintsY, {
            color: COLORS.textMuted,
            font: '9px sans-serif'
        });

        if (!this.autoPan) {
            this.drawText('Manual Mode', padding, hintsY + 12, {
                color: '#d65d0e',
                font: 'bold 9px sans-serif'
            });
        }
    }
}
