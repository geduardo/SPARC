/**
 * Oscilloscope Panel
 * Displays voltage and current waveforms with oscilloscope-style visualization
 */

import { BasePanel } from './BasePanel.js';
import {
    OSC_HORIZONTAL_DIVISIONS,
    OSC_VERTICAL_DIVISIONS,
    OSC_BACKGROUND_COLOR,
    OSC_CH1_COLOR,
    OSC_CH2_COLOR
} from '../utils/constants.js';

export class OscilloscopePanel extends BasePanel {
    constructor(canvasId) {
        super(canvasId);
        this.mode = 'auto'; // 'auto' | 'manual'
        this.usPerDiv = null; // us per division when manual
        this.divisionsX = OSC_HORIZONTAL_DIVISIONS;
        this.divisionsY = 5;  // horizontal grid lines per channel
        this.windowUs = 100; // updated per timebase
        this.lastDrawnFrame = -1;
        this.sampleStartIndex = 0;
        this.sampleEndIndex = 0;
        this.windowSampleCount = 0;
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

    init() {
        super.init();
        // Draw initial state to set up alignment
        this.draw(null, 0);
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
        if (mode === 'auto') {
            this.autoTimebaseUsPerDiv = null;
        }
    }

    setData(data) {
        super.setData(data);
        this.autoTimebaseUsPerDiv = null;
        this.windowSampleCount = 0;
        this.recomputeWindow(this.controller ? this.controller.currentFrame : 0);
    }

    onResize() {
        super.onResize();
        if (this.controller && this.controller.data) {
            this.controller.drawFrame(this.controller.currentFrame);
        }
    }

    recomputeWindow(frameIndex, frameData = null) {
        const signalHistory = this.getSignalHistory();
        if (!signalHistory) return;

        const voltageSeries = signalHistory.voltage || [];
        const currentSeries = signalHistory.current || [];
        const totalSamples = Math.max(voltageSeries.length, currentSeries.length);
        if (totalSamples <= 0) {
            this.sampleStartIndex = 0;
            this.sampleEndIndex = 0;
            this.windowSampleCount = 0;
            return;
        }

        const dtUs = Math.max(1, Number(signalHistory.dtUs) || 1);
        const usPerDiv = this.resolveUsPerDiv();
        this.windowUs = usPerDiv * this.divisionsX;
        this.windowSampleCount = Math.max(1, Math.ceil(this.windowUs / dtUs));

        const anchorTimeUs = this.resolveAnchorTimeUs(frameIndex, frameData, signalHistory, totalSamples);
        let right = Math.floor((anchorTimeUs - signalHistory.baseTimeUs) / dtUs);
        if (!Number.isFinite(right)) {
            right = totalSamples - 1;
        }
        right = Math.max(0, Math.min(totalSamples - 1, right));

        let left = Math.max(0, right - this.windowSampleCount + 1);
        let end = Math.min(totalSamples - 1, right);
        if (end - left + 1 < this.windowSampleCount) {
            left = Math.max(0, end - this.windowSampleCount + 1);
        }
        this.sampleStartIndex = left;
        this.sampleEndIndex = end;

        if (this.trigger && this.trigger.enabled) {
            const sourceSeries = this.trigger.source === 'ch2' ? currentSeries : voltageSeries;
            const searchLeft = Math.max(0, right - this.windowSampleCount * 5);
            const searchRight = Math.min(totalSamples - 1, right + this.windowSampleCount * 5);
            const trigIdx = this.findTriggerIndex(searchLeft, searchRight, sourceSeries);
            if (trigIdx !== null) {
                const half = Math.floor(this.windowSampleCount / 2);
                const delaySamples = Math.round(Number(this.trigger.delayUs || 0) / dtUs);
                const centerIdx = trigIdx + delaySamples;
                let newLeft = Math.max(0, centerIdx - half);
                let newRight = Math.min(totalSamples - 1, newLeft + this.windowSampleCount - 1);
                if (newRight - newLeft + 1 < this.windowSampleCount) {
                    newLeft = Math.max(0, newRight - this.windowSampleCount + 1);
                }
                this.sampleStartIndex = newLeft;
                this.sampleEndIndex = newRight;
            }
        }
    }

    resolveUsPerDiv() {
        if (this.mode === 'manual' && this.usPerDiv) {
            return this.usPerDiv;
        }

        if (!this.autoTimebaseUsPerDiv) {
            let onUs = 3;
            let offUs = 80;

            if (this.data && this.data.ON_time && this.data.ON_time.length > 0) {
                const validOns = this.data.ON_time.filter(v => typeof v === 'number' && v > 0);
                if (validOns.length > 0) {
                    validOns.sort((a, b) => a - b);
                    onUs = validOns[Math.floor(validOns.length / 2)];
                }
            }

            if (this.data && this.data.OFF_time && this.data.OFF_time.length > 0) {
                const validOffs = this.data.OFF_time.filter(v => typeof v === 'number' && v > 0);
                if (validOffs.length > 0) {
                    validOffs.sort((a, b) => a - b);
                    offUs = validOffs[Math.floor(validOffs.length / 2)];
                }
            }

            const typicalCycleUs = Math.max(onUs + offUs, 20);
            const desiredWindowUs = typicalCycleUs * 12;
            this.autoTimebaseUsPerDiv = Math.max(1, Math.round(desiredWindowUs / this.divisionsX));
        }

        return this.autoTimebaseUsPerDiv;
    }

    resolveAnchorTimeUs(frameIndex, frameData, signalHistory, totalSamples) {
        const frameTime = frameData ? Number(frameData.time) : NaN;
        if (Number.isFinite(frameTime)) {
            return frameTime;
        }

        if (this.data && this.data.time && this.data.time.length > frameIndex) {
            const indexedTime = Number(this.data.time[frameIndex]);
            if (Number.isFinite(indexedTime)) {
                return indexedTime;
            }
        }

        return signalHistory.baseTimeUs + Math.max(0, totalSamples - 1) * (Number(signalHistory.dtUs) || 1);
    }

    getSignalHistory() {
        const dataSource = this.controller && this.controller.dataSource;
        if (dataSource && typeof dataSource.getPulseHistory === 'function') {
            const history = dataSource.getPulseHistory();
            if (history && history.voltage && history.current) {
                return history;
            }
        }

        if (!this.data || !this.data.voltage || !this.data.current) {
            return null;
        }

        return {
            baseTimeUs: this.data.time && this.data.time.length > 0 ? Number(this.data.time[0]) : 0,
            dtUs: 1,
            voltage: this.data.voltage,
            current: this.data.current,
            sparkState: this.data.spark_status_state || []
        };
    }

    findTriggerIndex(start, end, sourceSeries) {
        const level = this.trigger.level;
        const rising = this.trigger.slope !== 'falling';
        for (let i = Math.max(start + 1, 1); i <= end; i++) {
            const prevRaw = sourceSeries[i - 1];
            const currRaw = sourceSeries[i];
            const prev = (typeof prevRaw === 'bigint') ? Number(prevRaw) : prevRaw;
            const curr = (typeof currRaw === 'bigint') ? Number(currRaw) : currRaw;
            if (!Number.isFinite(prev) || !Number.isFinite(curr)) continue;
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

        // Background
        this.ctx.fillStyle = OSC_BACKGROUND_COLOR;
        this.ctx.fillRect(0, 0, w, h);

        // Calculate grid positions for sidebar alignment
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

        this.channelGridPositions = {
            ch1Y0: vTopY0,
            ch1Y1: vTopY1,
            ch2Y0: cBotY0,
            ch2Y1: cBotY1,
            canvasHeight: h
        };

        if (!this.isEnabled) {
            this.drawText('Oscilloscope OFF', w / 2, h / 2, {
                color: '#888', font: 'bold 16px sans-serif', align: 'center', baseline: 'middle'
            });
            this.alignSidebarControls();
            return;
        }

        if (!this.data) {
            this.drawText('Oscilloscope', w / 2, h / 2, {
                color: '#076678', font: 'bold 16px sans-serif', align: 'center', baseline: 'middle'
            });
            this.alignSidebarControls();
            return;
        }

        const signalHistory = this.getSignalHistory();
        if (!signalHistory || !signalHistory.voltage || signalHistory.voltage.length === 0) {
            this.drawText('Waiting for pulse data', w / 2, h / 2, {
                color: '#888', font: 'bold 14px sans-serif', align: 'center', baseline: 'middle'
            });
            this.alignSidebarControls();
            return;
        }

        this.recomputeWindow(frameIndex, frameData);

        const voltageSeries = signalHistory.voltage || [];
        const currentSeries = signalHistory.current || [];

        const start = this.sampleStartIndex;
        const end = this.sampleEndIndex;
        const endForScale = Math.max(end, start + Math.max(1, this.windowSampleCount) - 1);

        const plotX0 = padLeft;
        const plotX1 = w - padRight;
        const plotW = Math.max(1, plotX1 - plotX0);

        const xToPx = (i) => plotX0 + ((i - start) / Math.max(1, (endForScale - start))) * plotW;

        // Voltage Y scale
        let vMin, vMax;
        if (this.vPerDiv === 'auto') {
            vMin = this.vFixedMin - (this.vOffset || 0);
            vMax = this.vFixedMax - (this.vOffset || 0);
        } else {
            const span = Number(this.vPerDiv) * this.divisionsY;
            const center = -(this.vOffset || 0);
            vMin = center - span / 2;
            vMax = center + span / 2;
        }
        const vToPx = (v) => vTopY1 - ((v - vMin) / Math.max(1e-9, vMax - vMin)) * chH;

        // Current Y scale
        let cMin, cTop;
        if (this.iPerDiv === 'auto') {
            const cMM = this.seriesMinMax(currentSeries, start, end, 0, 1);
            cMin = cMM.min - (this.iOffset || 0);
            cTop = cMM.max + 10 - (this.iOffset || 0);
            if (!(cTop > cMin)) { cTop = cMin + 1; }
        } else {
            const span = Number(this.iPerDiv) * this.divisionsY;
            const center = -(this.iOffset || 0);
            cMin = center - span / 2;
            cTop = center + span / 2;
        }
        const cToPx = (c) => cBotY1 - ((c - cMin) / Math.max(1e-9, cTop - cMin)) * chH;

        // Draw grids
        this.drawGridRect(plotX0, vTopY0, plotW, chH);
        this.drawGridRect(plotX0, cBotY0, plotW, chH);

        // Voltage trace
        this.ctx.save();
        this.ctx.beginPath();
        this.ctx.rect(plotX0, vTopY0, plotW, chH);
        this.ctx.clip();
        this.drawSeriesDecimated(voltageSeries, start, end, xToPx, vToPx, OSC_CH1_COLOR, 2.2, 'rgba(79,195,255,0.5)');
        this.ctx.restore();

        // Current trace
        this.ctx.save();
        this.ctx.beginPath();
        this.ctx.rect(plotX0, cBotY0, plotW, chH);
        this.ctx.clip();
        this.drawSeriesDecimated(currentSeries, start, end, xToPx, cToPx, OSC_CH2_COLOR, 2.0, 'rgba(255,106,160,0.45)');
        this.ctx.restore();

        // Trigger centerline
        if (this.trigger && this.trigger.enabled) {
            const centerX = plotX0 + plotW / 2;
            this.drawCenterTimeAxis(centerX, vTopY0, vTopY1, cBotY0, cBotY1);
        }

        // Axis labels
        this.drawText('Ch1 V', plotX0 - 36, vTopY0 - 2 + 10, { color: OSC_CH1_COLOR, font: '10px monospace' });
        this.drawText(`${vMax.toFixed(0)} V`, 6, vTopY0 - 2, { color: '#b3e5ff', font: '10px monospace' });
        this.drawText(`${vMin.toFixed(0)} V`, 6, vTopY1 - 12, { color: '#b3e5ff', font: '10px monospace' });

        this.drawText('Ch2 I', plotX1 + 6, cBotY0 - 2 + 10, { color: OSC_CH2_COLOR, font: '10px monospace' });
        this.drawText(`${cTop.toFixed(2)} A`, plotX1 + 6, cBotY0 - 2, { color: '#ffc1d8', font: '10px monospace' });
        this.drawText(`${cMin.toFixed(2)} A`, plotX1 + 6, cBotY1 - 12, { color: '#ffc1d8', font: '10px monospace' });

        const timebaseLabel = this.mode === 'manual' && this.usPerDiv ? `${this.usPerDiv} us/div` : 'Auto';
        this.drawText(timebaseLabel, w / 2, h - 12, { color: 'rgba(220,220,220,0.8)', font: '10px monospace', align: 'center' });

        this.lastDrawnFrame = frameIndex;
        this.alignSidebarControls();
    }

    alignSidebarControls() {
        const ch1Controls = document.getElementById('ch1Controls');
        const ch2Controls = document.getElementById('ch2Controls');

        if (!ch1Controls || !ch2Controls) return;
        if (!this.channelGridPositions) return;

        const pos = this.channelGridPositions;
        const ch1Center = pos.ch1Y0 + (pos.ch1Y1 - pos.ch1Y0) / 2;
        const ch2Center = pos.ch2Y0 + (pos.ch2Y1 - pos.ch2Y0) / 2;
        const ch1Height = ch1Controls.offsetHeight;
        const ch2Height = ch2Controls.offsetHeight;
        const ch1Top = ch1Center - ch1Height / 2;
        const ch2Top = ch2Center - ch2Height / 2;

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
        this.ctx.strokeStyle = 'rgba(255,255,255,0.08)';
        this.ctx.lineWidth = 1;
        for (let i = 0; i <= this.divisionsY; i++) {
            const yy = y + (height / this.divisionsY) * i;
            this.ctx.beginPath();
            this.ctx.moveTo(x, yy);
            this.ctx.lineTo(x + width, yy);
            this.ctx.stroke();
        }
        for (let i = 0; i <= this.divisionsX; i++) {
            const xx = x + (width / this.divisionsX) * i;
            this.ctx.beginPath();
            this.ctx.moveTo(xx, y);
            this.ctx.lineTo(xx, y + height);
            this.ctx.stroke();
        }
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
            const num = (typeof v === 'bigint') ? Number(v) : v;
            if (!Number.isFinite(num)) continue;
            if (num < min) min = num;
            if (num > max) max = num;
        }
        if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
            min = fallbackMin; max = Math.max(fallbackMax, min + 1);
        }
        return { min, max };
    }

    drawSeriesDecimated(series, start, end, xToPx, yToPx, color, lineWidth, glowColor) {
        const w = this.canvas.width / window.devicePixelRatio;
        const plotWidthPx = Math.max(50, w - 80);
        const span = end - start + 1;
        if (span <= 1) return;

        const maxBuckets = Math.floor(plotWidthPx * 2);
        const targetBuckets = Math.min(maxBuckets, this.maxPointsPerSeries);
        const bucketSize = Math.max(1, Math.ceil(span / targetBuckets));

        this.ctx.strokeStyle = color;
        this.ctx.lineWidth = lineWidth;

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

            for (let j = i; j <= bucketEnd; j++) {
                const v = series[j];
                const num = (typeof v === 'bigint') ? Number(v) : v;
                if (Number.isFinite(num)) {
                    if (num < bucketMin) bucketMin = num;
                    if (num > bucketMax) bucketMax = num;
                }
            }

            if (!Number.isFinite(bucketMin)) continue;

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

    drawCenterTimeAxis(centerX, topY0, topY1, botY0, botY1) {
        const drawAxis = (y0, y1) => {
            this.ctx.save();
            this.ctx.strokeStyle = 'rgba(255,255,255,0.35)';
            this.ctx.lineWidth = 1.8;
            const inset = 1.5;
            this.ctx.beginPath();
            this.ctx.moveTo(centerX, y0 + inset);
            this.ctx.lineTo(centerX, y1 - inset);
            this.ctx.stroke();

            const h = y1 - y0;
            const majorCount = this.divisionsY;
            const majorStep = h / majorCount;
            const minorStep = majorStep / 2;
            const majorLen = 8;
            const minorLen = 5;

            this.ctx.lineWidth = 1.3;
            for (let i = 0; i <= majorCount; i++) {
                const yy = y0 + majorStep * i;
                if (yy <= y0 + 2 || yy >= y1 - 2) continue;
                this.ctx.beginPath();
                this.ctx.moveTo(centerX - majorLen, yy);
                this.ctx.lineTo(centerX + majorLen, yy);
                this.ctx.stroke();
            }
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
