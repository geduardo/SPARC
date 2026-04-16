/**
 * SPARC Visualization Dashboard - Entry Point
 * Initializes the dashboard when the DOM is ready
 */

import { DashboardController } from './DashboardController.js';

// Global reference for debugging
let dashboard;

function getLiveUrlFromQuery() {
    const params = new URLSearchParams(window.location.search);
    const liveUrl = params.get('live');
    return liveUrl && liveUrl.trim() ? liveUrl.trim() : null;
}

window.addEventListener('DOMContentLoaded', async () => {
    dashboard = new DashboardController();

    // Expose for debugging
    window.dashboard = dashboard;

    const liveUrl = getLiveUrlFromQuery();
    if (!liveUrl) {
        return;
    }

    try {
        await dashboard.connectLiveStream(liveUrl);
        console.info(`Connected dashboard live stream: ${liveUrl}`);
    } catch (error) {
        console.error(`Failed to connect dashboard live stream: ${liveUrl}`, error);
        window.dashboardLiveConnectError = error;
    }
});
