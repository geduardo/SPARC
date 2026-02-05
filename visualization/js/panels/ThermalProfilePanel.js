/**
 * Thermal Profile Panel
 * Displays wire temperature distribution as a heatmap
 */

import { BasePanel } from './BasePanel.js';
import {
    DEFAULT_WIRE_DIAMETER,
    THERMAL_MIN_TEMP_K,
    THERMAL_MAX_TEMP_K,
    COLORS
} from '../utils/constants.js';

export class ThermalProfilePanel extends BasePanel {
    constructor(canvasId) {
        super(canvasId);

        // Configuration for workpiece dimensions
        this.bufferBottomMM = 30.0;
        this.bufferTopMM = 30.0;
        this.workpieceHeightMM = 100.0;
        this.contactOffsetBottom = 10.0;
        this.contactOffsetTop = 10.0;
        this.wireDiameter = DEFAULT_WIRE_DIAMETER;

        // Visualization settings
        this.showEdges = false;
        this.tempMinC = 0;
        this.tempMaxC = 500;

        // Color map cache
        this.colorMapCache = new Map();

        // Camera controls
        this.cameraY = 0;
        this.zoomY = 1.0;
        this.isDragging = false;
        this.lastMouseY = 0;
        this.selectedSegmentIndex = -1;
        this.lastWireMin = null;
        this.lastWireMax = null;
    }

    init() {
        super.init();

        this.cameraY = this.bufferBottomMM + this.workpieceHeightMM / 2;

        this.canvas.addEventListener('wheel', (e) => this.handleWheel(e));
        this.canvas.addEventListener('mousedown', (e) => this.handleMouseDown(e));
        this.canvas.addEventListener('mousemove', (e) => this.handleMouseMove(e));
        this.canvas.addEventListener('mouseup', (e) => this.handleMouseUp(e));
        this.canvas.addEventListener('mouseleave', (e) => this.handleMouseUp(e));
        this.canvas.addEventListener('dblclick', (e) => this.handleDoubleClick(e));
    }

    handleWheel(e) {
        e.preventDefault();

        const zoomSpeed = 0.1;
        const zoomFactor = e.deltaY > 0 ? (1 + zoomSpeed) : (1 - zoomSpeed);

        this.zoomY = Math.max(0.1, Math.min(5.0, this.zoomY * zoomFactor));
        this.enforceZoomAndPanConstraints();

        if (this.controller) {
            this.controller.drawFrame(this.controller.currentFrame);
        }
    }

    handleMouseDown(e) {
        this.isDragging = true;
        this.lastMouseY = e.offsetY;

        if (this.controller && this.controller.data) {
            this.checkForSegmentClick(e.offsetX, e.offsetY);
        }
    }

    checkForSegmentClick(mx, my) {
        const frameData = this.controller.getFrameData(this.controller.currentFrame);
        if (!frameData || !frameData.wire_material_positions_mm) return;

        const positions = frameData.wire_material_positions_mm;
        const nSegments = positions.length;
        if (nSegments === 0) return;

        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;
        const marginLeft = 90;
        const marginRight = 100;
        const marginTop = 40;
        const marginBottom = 45;
        const plotWidth = w - marginLeft - marginRight;
        const plotHeight = h - marginTop - marginBottom;

        const baseVisibleHeightMM = this.workpieceHeightMM + 10;
        const visibleHeightMM = baseVisibleHeightMM * this.zoomY;
        const visibleMinPos = this.cameraY - visibleHeightMM / 2;
        const visibleMaxPos = this.cameraY + visibleHeightMM / 2;

        const yScale = plotHeight / (visibleMaxPos - visibleMinPos);
        const posToY = (posMM) => marginTop + (posMM - visibleMinPos) * yScale;

        const wireVisWidth = plotWidth * 0.35;
        const wireVisCenterX = marginLeft + wireVisWidth / 2;
        const visualThickness = this.wireDiameter * 25 * yScale;

        if (Math.abs(mx - wireVisCenterX) > visualThickness / 2) return;

        let segmentLenMM = 0.2;
        if (nSegments > 1) {
            const sortedPos = [...positions].sort((a, b) => a - b);
            const diffs = [];
            for (let i = 1; i < sortedPos.length; i++) {
                const diff = sortedPos[i] - sortedPos[i - 1];
                if (diff > 1e-6) diffs.push(diff);
            }
            if (diffs.length > 0) {
                diffs.sort((a, b) => a - b);
                segmentLenMM = diffs[Math.floor(diffs.length / 2)];
            }
        }

        const segmentHeightViz = segmentLenMM * yScale * 1.05;

        for (let i = 0; i < nSegments; i++) {
            const pos = positions[i];
            const y = posToY(pos);
            const rectH = Math.ceil(segmentHeightViz) + 2;

            if (my >= y && my <= y + rectH) {
                if (this.controller) {
                    const trace = this.controller.traceMaterial(this.controller.currentFrame, i);
                    this.controller.selectedMaterialTrace = trace;
                    // Use the segment's index at the earliest frame for a consistent ID
                    this.controller.selectedSegmentClickIndex = this.controller.getOriginalSegmentId(trace);
                    this.controller.showDamagePlot();
                    this.controller.drawFrame(this.controller.currentFrame);
                }
                return;
            }
        }
    }

    handleMouseMove(e) {
        if (!this.isDragging) return;

        const deltaY = e.offsetY - this.lastMouseY;
        this.lastMouseY = e.offsetY;

        const h = this.canvas.height / window.devicePixelRatio;
        const visibleHeightMM = (this.workpieceHeightMM + 10) * this.zoomY;
        const mmPerPixel = visibleHeightMM / h;

        const deltaY_mm = deltaY * mmPerPixel;
        this.cameraY -= deltaY_mm;
        this.enforceZoomAndPanConstraints();

        if (this.controller) {
            this.controller.drawFrame(this.controller.currentFrame);
        }
    }

    handleMouseUp() {
        this.isDragging = false;
    }

    handleDoubleClick() {
        this.cameraY = this.bufferBottomMM + this.workpieceHeightMM / 2;
        this.zoomY = 1.0;
        this.enforceZoomAndPanConstraints();

        if (this.controller) {
            this.controller.drawFrame(this.controller.currentFrame);
        }
    }

    setData(data) {
        super.setData(data);

        if (data && data.metadata) {
            if (data.metadata.workpiece_height !== undefined) {
                this.workpieceHeightMM = data.metadata.workpiece_height;
            }
            if (data.metadata.buffer_len_bottom !== undefined) {
                this.bufferBottomMM = data.metadata.buffer_len_bottom;
            }
            if (data.metadata.buffer_len_top !== undefined) {
                this.bufferTopMM = data.metadata.buffer_len_top;
            }
            if (data.metadata.contact_offset_bottom !== undefined) {
                this.contactOffsetBottom = data.metadata.contact_offset_bottom;
            }
            if (data.metadata.contact_offset_top !== undefined) {
                this.contactOffsetTop = data.metadata.contact_offset_top;
            }
        }

        this.cameraY = this.bufferBottomMM + this.workpieceHeightMM / 2;
        this.zoomY = 1.0;
        this.enforceZoomAndPanConstraints();
    }

    enforceZoomAndPanConstraints() {
        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;

        const marginLeft = 90;
        const marginRight = 100;
        const marginTop = 40;
        const marginBottom = 45;
        const plotWidth = Math.max(10, w - marginLeft - marginRight);
        const plotHeight = Math.max(10, h - marginTop - marginBottom);

        const baseVisibleHeightMM = this.workpieceHeightMM + 10;

        const wireVisWidth = plotWidth * 0.35;
        const allowedWidthPx = Math.max(4, wireVisWidth - 8);
        const thicknessK = this.wireDiameter * 25;
        const minZoomForThickness = (thicknessK * plotHeight) / (allowedWidthPx * baseVisibleHeightMM);

        const fallbackMin = (this.bufferBottomMM - this.contactOffsetBottom - 10);
        const fallbackMax = (this.bufferBottomMM + this.workpieceHeightMM + this.contactOffsetTop + 10);
        const wireMin = (this.lastWireMin != null) ? this.lastWireMin : fallbackMin;
        const wireMax = (this.lastWireMax != null) ? this.lastWireMax : fallbackMax;
        const totalWireSpan = Math.max(1e-3, wireMax - wireMin);
        const maxVisible = Math.max(1e-3, totalWireSpan - 10);
        const maxZoomForSpan = Math.max(0.105, maxVisible / baseVisibleHeightMM);

        const lower = Math.max(0.105, minZoomForThickness || 0.105);
        const upper = Math.max(lower, Math.min(5.0, maxZoomForSpan || 5.0));
        this.zoomY = Math.max(lower, Math.min(upper, this.zoomY));

        const visibleHeightMM = baseVisibleHeightMM * this.zoomY;
        const minCenter = wireMin + 5 + visibleHeightMM / 2;
        const maxCenter = wireMax - 5 - visibleHeightMM / 2;
        if (minCenter <= maxCenter) {
            this.cameraY = Math.max(minCenter, Math.min(maxCenter, this.cameraY));
        }
    }

    getHotColor(tempC, minC, maxC) {
        const normalized = Math.max(0, Math.min(1, (tempC - minC) / (maxC - minC)));

        const cacheKey = normalized.toFixed(4);
        if (this.colorMapCache.has(cacheKey)) {
            return this.colorMapCache.get(cacheKey);
        }

        let r, g, b;

        if (normalized < 0.33) {
            const t = normalized / 0.33;
            r = Math.floor(255 * t);
            g = 0;
            b = 0;
        } else if (normalized < 0.66) {
            const t = (normalized - 0.33) / 0.33;
            r = 255;
            g = Math.floor(255 * t);
            b = 0;
        } else {
            const t = (normalized - 0.66) / 0.34;
            r = 255;
            g = 255;
            b = Math.floor(255 * t);
        }

        const color = `rgb(${r}, ${g}, ${b})`;
        this.colorMapCache.set(cacheKey, color);
        return color;
    }

    draw(frameData, frameIndex) {
        this.clear();

        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;

        this.ctx.fillStyle = COLORS.bgThermal;
        this.ctx.fillRect(0, 0, w, h);

        if (!frameData || !frameData.wire_temperature || !frameData.wire_material_positions_mm) {
            this.drawText('No wire temperature data available', w / 2, h / 2 + 10, {
                color: COLORS.danger,
                font: '14px sans-serif',
                align: 'center',
                baseline: 'middle'
            });
            this.drawText('Ensure log_strategy="full_field" when running simulation', w / 2, h / 2 + 35, {
                color: COLORS.textMuted,
                font: '12px sans-serif',
                align: 'center',
                baseline: 'middle'
            });
            return;
        }

        const wireTemperatures = frameData.wire_temperature;
        const wirePositions = frameData.wire_material_positions_mm;
        const nSegments = wireTemperatures.length;
        this.lastWireMin = Math.min(...wirePositions);
        this.lastWireMax = Math.max(...wirePositions);

        if (nSegments === 0) {
            this.drawText('No wire segments', w / 2, h / 2, {
                color: '#9d0006',
                font: '14px sans-serif',
                align: 'center',
                baseline: 'middle'
            });
            return;
        }

        let segmentLenMM = 0.2;
        if (nSegments > 1) {
            const sortedPos = [...wirePositions].sort((a, b) => a - b);
            const diffs = [];
            for (let i = 1; i < sortedPos.length; i++) {
                const diff = sortedPos[i] - sortedPos[i - 1];
                if (diff > 1e-6) {
                    diffs.push(diff);
                }
            }
            if (diffs.length > 0) {
                diffs.sort((a, b) => a - b);
                segmentLenMM = diffs[Math.floor(diffs.length / 2)];
            }
        }

        const segmentSizeUm = segmentLenMM * 1000;

        const marginLeft = 90;
        const marginRight = 100;
        const marginTop = 40;
        const marginBottom = 45;
        const plotWidth = w - marginLeft - marginRight;
        const plotHeight = h - marginTop - marginBottom;

        const baseVisibleHeightMM = this.workpieceHeightMM + 10;
        const visibleHeightMM = baseVisibleHeightMM * this.zoomY;
        let visibleMinPos = this.cameraY - visibleHeightMM / 2;
        let visibleMaxPos = this.cameraY + visibleHeightMM / 2;

        const yScale = plotHeight / (visibleMaxPos - visibleMinPos);
        const posToY = (posMM) => {
            return marginTop + (posMM - visibleMinPos) * yScale;
        };

        const tempsC = wireTemperatures.map(t => t - 273.15);
        this.tempMinC = 0;
        this.tempMaxC = 500;

        const wireVisWidth = plotWidth * 0.35;
        const wireVisCenterX = marginLeft + wireVisWidth / 2;
        const visualThickness = this.wireDiameter * 25 * yScale;
        const segmentHeightViz = segmentLenMM * yScale * 1.05;

        // Draw wire segments
        for (let i = 0; i < nSegments; i++) {
            const pos = wirePositions[i];
            const tempC = tempsC[i];
            const y = posToY(pos);
            const color = this.getHotColor(tempC, this.tempMinC, this.tempMaxC);

            this.ctx.fillStyle = color;
            const x = wireVisCenterX - visualThickness / 2;
            const rectHeight = Math.ceil(segmentHeightViz) + 2;

            this.ctx.fillRect(
                Math.floor(x),
                Math.floor(y),
                Math.ceil(visualThickness),
                rectHeight
            );

            if (i === this.selectedSegmentIndex) {
                this.ctx.strokeStyle = '#ffffff';
                this.ctx.lineWidth = 2;
                this.ctx.strokeRect(
                    Math.floor(x),
                    Math.floor(y),
                    Math.ceil(visualThickness),
                    rectHeight
                );
            }

            if (this.showEdges) {
                this.ctx.strokeStyle = 'black';
                this.ctx.lineWidth = 0.5;
                this.ctx.strokeRect(
                    Math.floor(x),
                    Math.floor(y),
                    Math.ceil(visualThickness),
                    rectHeight
                );
            }
        }

        // Workpiece boundaries
        const workpieceBottomY = posToY(this.bufferBottomMM);
        const workpieceTopY = posToY(this.bufferBottomMM + this.workpieceHeightMM);

        this.ctx.strokeStyle = COLORS.textMuted;
        this.ctx.lineWidth = 2;
        this.ctx.setLineDash([5, 5]);
        this.ctx.beginPath();
        this.ctx.moveTo(marginLeft, workpieceBottomY);
        this.ctx.lineTo(marginLeft + wireVisWidth, workpieceBottomY);
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.moveTo(marginLeft, workpieceTopY);
        this.ctx.lineTo(marginLeft + wireVisWidth, workpieceTopY);
        this.ctx.stroke();
        this.ctx.setLineDash([]);

        // Contact lines
        const contactBottomPosMM = this.bufferBottomMM - this.contactOffsetBottom;
        const contactTopPosMM = this.bufferBottomMM + this.workpieceHeightMM + this.contactOffsetTop;
        const contactBottomY = posToY(contactBottomPosMM);
        const contactTopY = posToY(contactTopPosMM);

        this.ctx.strokeStyle = COLORS.textMuted;
        this.ctx.lineWidth = 1.5;
        this.ctx.setLineDash([2, 4]);
        this.ctx.beginPath();
        this.ctx.moveTo(marginLeft, contactBottomY);
        this.ctx.lineTo(marginLeft + wireVisWidth, contactBottomY);
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.moveTo(marginLeft, contactTopY);
        this.ctx.lineTo(marginLeft + wireVisWidth, contactTopY);
        this.ctx.stroke();
        this.ctx.setLineDash([]);

        // Temperature profile
        const profileGap = 60;
        const profileX = marginLeft + wireVisWidth + profileGap;
        const profileWidth = plotWidth - wireVisWidth - profileGap;

        const tempScale = profileWidth / (this.tempMaxC - this.tempMinC);
        const tempToX = (tempC) => {
            return profileX + (tempC - this.tempMinC) * tempScale;
        };

        // Shaded workpiece region
        this.ctx.fillStyle = 'rgba(108, 117, 125, 0.1)';
        this.ctx.fillRect(profileX, workpieceTopY, profileWidth, workpieceBottomY - workpieceTopY);

        // Sort for line plot
        const sortedIndices = [...Array(nSegments).keys()].sort((a, b) =>
            wirePositions[a] - wirePositions[b]
        );
        const sortedPositions = sortedIndices.map(i => wirePositions[i]);
        const sortedTemps = sortedIndices.map(i => tempsC[i]);

        // Temperature profile line
        this.ctx.strokeStyle = COLORS.warning;
        this.ctx.lineWidth = 2.5;
        this.ctx.beginPath();
        for (let i = 0; i < sortedPositions.length; i++) {
            const x = tempToX(sortedTemps[i]);
            const y = posToY(sortedPositions[i]);
            if (i === 0) {
                this.ctx.moveTo(x, y);
            } else {
                this.ctx.lineTo(x, y);
            }
        }
        this.ctx.stroke();

        // Axes
        this.ctx.strokeStyle = COLORS.text;
        this.ctx.lineWidth = 1.5;
        this.ctx.beginPath();
        this.ctx.moveTo(profileX, marginTop);
        this.ctx.lineTo(profileX, h - marginBottom);
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.moveTo(profileX, h - marginBottom);
        this.ctx.lineTo(w - marginRight, h - marginBottom);
        this.ctx.stroke();

        // Y-axis ticks
        const numYTicks = 6;
        for (let i = 0; i <= numYTicks; i++) {
            const posMM = visibleMinPos + (i / numYTicks) * (visibleMaxPos - visibleMinPos);
            const y = posToY(posMM);

            this.ctx.beginPath();
            this.ctx.moveTo(profileX - 5, y);
            this.ctx.lineTo(profileX, y);
            this.ctx.stroke();

            this.drawText(posMM.toFixed(1), profileX - 10, y, {
                color: COLORS.text,
                font: '11px sans-serif',
                align: 'right',
                baseline: 'middle'
            });
        }

        // X-axis ticks
        for (let tempC = 0; tempC <= 500; tempC += 50) {
            const x = tempToX(tempC);

            this.ctx.beginPath();
            this.ctx.moveTo(x, h - marginBottom);
            this.ctx.lineTo(x, h - marginBottom + 5);
            this.ctx.stroke();

            this.drawText(tempC.toFixed(0), x, h - marginBottom + 10, {
                color: COLORS.text,
                font: '11px sans-serif',
                align: 'center',
                baseline: 'top'
            });
        }

        // Axis labels
        this.ctx.save();
        this.ctx.translate(marginLeft + wireVisWidth + profileGap / 2 - 12, marginTop + plotHeight / 2);
        this.ctx.rotate(-Math.PI / 2);
        this.ctx.fillStyle = COLORS.text;
        this.ctx.font = 'bold 14px sans-serif';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        this.ctx.fillText('Position (mm)', 0, 0);
        this.ctx.restore();

        this.drawText('Temperature (C)', profileX + profileWidth / 2, h - marginBottom + 30, {
            color: COLORS.text,
            font: 'bold 14px sans-serif',
            align: 'center'
        });

        // Colorbar
        const colorbarX = w - marginRight + 30;
        const colorbarWidth = 20;
        const colorbarHeight = plotHeight;
        const colorbarY = marginTop;

        const numColorSteps = 50;
        const stepHeight = colorbarHeight / numColorSteps;
        for (let i = 0; i < numColorSteps; i++) {
            const fraction = i / numColorSteps;
            const tempC = this.tempMinC + fraction * (this.tempMaxC - this.tempMinC);
            const color = this.getHotColor(tempC, this.tempMinC, this.tempMaxC);
            const y = colorbarY + colorbarHeight - (i + 1) * stepHeight;

            this.ctx.fillStyle = color;
            this.ctx.fillRect(colorbarX, y, colorbarWidth, stepHeight);
        }

        this.ctx.strokeStyle = COLORS.text;
        this.ctx.lineWidth = 1;
        this.ctx.strokeRect(colorbarX, colorbarY, colorbarWidth, colorbarHeight);

        const numColorbarTicks = 5;
        for (let i = 0; i <= numColorbarTicks; i++) {
            const tempC = this.tempMinC + (i / numColorbarTicks) * (this.tempMaxC - this.tempMinC);
            const y = colorbarY + colorbarHeight - (i / numColorbarTicks) * colorbarHeight;

            this.ctx.beginPath();
            this.ctx.moveTo(colorbarX + colorbarWidth, y);
            this.ctx.lineTo(colorbarX + colorbarWidth + 5, y);
            this.ctx.stroke();

            this.drawText(tempC.toFixed(0) + 'C', colorbarX + colorbarWidth + 10, y, {
                color: COLORS.text,
                font: '10px sans-serif',
                align: 'left',
                baseline: 'middle'
            });
        }

        // Stats
        const avgTempC = tempsC.reduce((a, b) => a + b, 0) / tempsC.length;
        const actualMaxTempC = Math.max(...tempsC);
        const statsText = `Segments: ${nSegments} | Segment size: ${segmentSizeUm.toFixed(1)} um | Avg: ${avgTempC.toFixed(1)}C | Max: ${actualMaxTempC.toFixed(1)}C`;
        const statsX = w - 10;
        const statsY = 10;
        this.drawText(statsText, statsX, statsY, {
            color: '#7c6f64',
            font: '11px monospace',
            align: 'right',
            baseline: 'top'
        });

        // Selection highlight
        const trace = this.controller.selectedMaterialTrace;
        if (trace && trace.has(frameIndex)) {
            const segIdx = trace.get(frameIndex);
            const pos = wirePositions[segIdx];
            const y = posToY(pos);
            const rectH = Math.ceil(segmentHeightViz) + 2;
            const x = wireVisCenterX - visualThickness / 2;

            // Draw "TRACKING" text with arrow
            const centerY = Math.floor(y) + rectH / 2;
            this.ctx.fillStyle = COLORS.text;
            this.ctx.font = 'bold 11px sans-serif';
            this.ctx.textAlign = 'right';
            this.ctx.textBaseline = 'middle';
            this.ctx.fillText("TRACKING", Math.floor(x) - 18, centerY);

            // Draw arrow pointing right (to the segment)
            const arrowX = Math.floor(x) - 14;
            const arrowSize = 5;
            this.ctx.beginPath();
            this.ctx.moveTo(arrowX, centerY);
            this.ctx.lineTo(arrowX + arrowSize + 3, centerY);
            this.ctx.strokeStyle = COLORS.text;
            this.ctx.lineWidth = 2;
            this.ctx.stroke();
            // Arrow head
            this.ctx.beginPath();
            this.ctx.moveTo(arrowX + arrowSize + 3, centerY);
            this.ctx.lineTo(arrowX + arrowSize - 2, centerY - 4);
            this.ctx.lineTo(arrowX + arrowSize - 2, centerY + 4);
            this.ctx.closePath();
            this.ctx.fillStyle = COLORS.text;
            this.ctx.fill();
        }
    }
}
