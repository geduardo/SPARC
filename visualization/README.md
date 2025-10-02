# SPARC Web Dashboard

A lightweight, zero-dependency web-based visualization dashboard for Wire EDM simulation data.

## Features

- **4 synchronized panels:**
  - Side View: Wire + Workpiece + Spark visualization
  - Virtual Oscilloscope: Voltage/Current traces
  - Top View: Debris concentration
  - Thermal Profile: Wire temperature distribution

- **Interactive timeline controls:**
  - Play/Pause animation
  - Scrub through timeline
  - Real-time display

- **Modular architecture:**
  - Each panel is independent
  - Easy to extend with new panels
  - Pure HTML/Canvas/JavaScript (no dependencies)

## Quick Start

### 1. Generate Simulation Data

Run the demo script to generate JSON data:

```bash
python examples/dashboard_demo.py
```

This will:
- Run a Wire EDM simulation
- Log relevant signals
- Export to `visualization/data/simulation_data.json`
- Automatically open the dashboard in your browser

### 2. Open Dashboard

Open `dashboard.html` in your web browser:
- Double-click the file, or
- Right-click → Open with → Browser, or
- Use a local web server:
  ```bash
  cd visualization
  python -m http.server 8000
  # Then open http://localhost:8000/dashboard.html
  ```

### 3. Load Data

Click "📁 Load Data" and select your JSON file (e.g., `data/simulation_data.json`)

### 4. Play Animation

Use the timeline controls:
- **▶ Play**: Start animation
- **⏸ Pause**: Pause animation
- **↻ Reset**: Jump to start
- **Timeline slider**: Scrub to specific time

## Architecture

```
dashboard.html              # Main HTML structure & styling
dashboard.js                # Controller + Panel modules
├── DashboardController     # Coordinates everything
├── BasePanel               # Base class for all panels
├── SideViewPanel           # Panel 1: Side view
├── OscilloscopePanel       # Panel 2: Oscilloscope
├── TopViewPanel            # Panel 3: Top view
└── ThermalProfilePanel     # Panel 4: Thermal profile
```

## Data Format

The dashboard expects JSON with this structure:

```json
{
  "time": [0, 1, 2, ...],              // Array of timestamps (µs)
  "voltage": [80.0, 79.8, ...],        // Scalar arrays
  "current": [5.2, 5.3, ...],
  "wire_position": [0, 0.2, ...],
  "workpiece_position": [0, 0.5, ...],
  "spark_status": [[0, null, 0], ...], // Array of arrays
  "wire_temperature": [[293, ...], ...], // 2D array
  ...
}
```

## Customizing Panels

Each panel is a self-contained module that inherits from `BasePanel`:

```javascript
class MyCustomPanel extends BasePanel {
    draw(frameData, frameIndex) {
        this.clear();

        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;

        // Your drawing code here
        this.ctx.fillStyle = '#00ff88';
        this.ctx.fillRect(0, 0, w, h);

        // Access frame data
        if (frameData.voltage !== undefined) {
            this.drawText(`V: ${frameData.voltage}`, 10, 10);
        }
    }
}
```

Then register in `DashboardController.initializePanels()`:

```javascript
this.panels.myCustom = new MyCustomPanel('myCustomCanvas');
```

## Adding New Panels

1. Add canvas element to `dashboard.html`
2. Create new panel class in `dashboard.js`
3. Register in `DashboardController.initializePanels()`
4. Panel will automatically receive:
   - Frame data
   - Resize events
   - Drawing context

## File Size

- **HTML**: ~4KB
- **JS**: ~10KB
- **Total**: ~14KB (uncompressed)

No external dependencies!

## Browser Compatibility

Works in all modern browsers:
- Chrome/Edge 90+
- Firefox 88+
- Safari 14+

## Performance

- Hardware-accelerated Canvas rendering
- 60 FPS playback
- Handles datasets with 10k+ frames smoothly

## Troubleshooting

**Dashboard loads but shows "Please load data first":**
- Click "📁 Load Data" and select your JSON file

**"Error loading data" message:**
- Check console (F12) for details
- Verify JSON format matches expected structure
- Ensure `time` array exists

**Animation is choppy:**
- Reduce logging frequency in Python
- Use fewer data points
- Close other browser tabs

**Can't load JSON file:**
- If using `file://` protocol, some browsers restrict file access
- Use a local web server instead (see Quick Start #2)

## Future Enhancements

- [ ] Add zoom/pan for each panel
- [ ] Export animation to video
- [ ] Real-time mode (WebSocket connection)
- [ ] Multi-signal selection for oscilloscope
- [ ] Heatmap colormaps for thermal panel

## Contributing

To add features:
1. Panels are modular - extend `BasePanel`
2. Use pure JavaScript (no frameworks)
3. Keep dependencies at zero
4. Test in multiple browsers
