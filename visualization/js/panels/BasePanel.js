/**
 * Base Panel Class
 * All visualization panels inherit from this class
 */

export class BasePanel {
    /**
     * @param {string} canvasId - DOM ID of the canvas element
     */
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.data = null;
        this.controller = null; // Set by DashboardController
    }

    /**
     * Initialize the panel
     */
    init() {
        this.setupCanvas();
    }

    /**
     * Set canvas resolution to match display size (handles HiDPI)
     */
    setupCanvas() {
        const rect = this.canvas.getBoundingClientRect();
        this.ctx.setTransform(1, 0, 0, 1, 0, 0);
        this.canvas.width = rect.width * window.devicePixelRatio;
        this.canvas.height = rect.height * window.devicePixelRatio;
        this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    }

    /**
     * Set simulation data for this panel
     * @param {Object} data - Simulation data object
     */
    setData(data) {
        this.data = data;
    }

    /**
     * Handle window resize
     */
    onResize() {
        this.setupCanvas();
    }

    /**
     * Clear the canvas
     */
    clear() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }

    /**
     * Helper to draw text with common options
     * @param {string} text - Text to draw
     * @param {number} x - X position
     * @param {number} y - Y position
     * @param {Object} options - Drawing options
     */
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

    /**
     * Get canvas dimensions in CSS pixels (not device pixels)
     * @returns {{width: number, height: number}}
     */
    getCanvasSize() {
        return {
            width: this.canvas.width / window.devicePixelRatio,
            height: this.canvas.height / window.devicePixelRatio
        };
    }

    /**
     * Draw the panel content - override in subclasses
     * @param {Object} frameData - Data for the current frame
     * @param {number} frameIndex - Current frame index
     */
    draw(frameData, frameIndex) {
        this.clear();
        this.drawText('Panel not implemented', 10, 10, { color: '#888' });
    }
}
