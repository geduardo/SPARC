/**
 * SPARC Visualization Dashboard - Entry Point
 * Initializes the dashboard when the DOM is ready
 */

import { DashboardController } from './DashboardController.js';

// Global reference for debugging
let dashboard;

window.addEventListener('DOMContentLoaded', () => {
    dashboard = new DashboardController();

    // Expose for debugging
    window.dashboard = dashboard;
});
