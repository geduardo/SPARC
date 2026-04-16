import assert from 'node:assert/strict';

class FakeClassList {
    constructor(initial = []) {
        this.tokens = new Set(initial);
    }

    add(...tokens) {
        tokens.forEach((token) => this.tokens.add(token));
    }

    remove(...tokens) {
        tokens.forEach((token) => this.tokens.delete(token));
    }

    contains(token) {
        return this.tokens.has(token);
    }

    toggle(token, force) {
        if (force === true) {
            this.tokens.add(token);
            return true;
        }
        if (force === false) {
            this.tokens.delete(token);
            return false;
        }
        if (this.tokens.has(token)) {
            this.tokens.delete(token);
            return false;
        }
        this.tokens.add(token);
        return true;
    }

    toString() {
        return Array.from(this.tokens).join(' ');
    }
}

class FakeEventTarget {
    constructor() {
        this.listeners = new Map();
    }

    addEventListener(type, listener) {
        if (!this.listeners.has(type)) {
            this.listeners.set(type, new Set());
        }
        this.listeners.get(type).add(listener);
    }

    removeEventListener(type, listener) {
        this.listeners.get(type)?.delete(listener);
    }

    dispatchEvent(event) {
        const normalizedEvent = event || {};
        normalizedEvent.type = normalizedEvent.type || 'event';
        normalizedEvent.target = normalizedEvent.target || this;
        normalizedEvent.currentTarget = this;
        normalizedEvent.defaultPrevented = false;
        normalizedEvent.preventDefault = normalizedEvent.preventDefault || (() => {
            normalizedEvent.defaultPrevented = true;
        });
        normalizedEvent.stopPropagation = normalizedEvent.stopPropagation || (() => {});

        const listeners = Array.from(this.listeners.get(normalizedEvent.type) || []);
        listeners.forEach((listener) => listener.call(this, normalizedEvent));
        return !normalizedEvent.defaultPrevented;
    }
}

class FakeElement extends FakeEventTarget {
    constructor(id = '', tagName = 'div') {
        super();
        this.id = id;
        this.tagName = tagName.toUpperCase();
        this.style = {};
        this.classList = new FakeClassList();
        this.children = [];
        this.parentElement = null;
        this.textContent = '';
        this.innerHTML = '';
        this.value = '';
        this.checked = false;
        this.disabled = false;
        this.min = '';
        this.max = '';
        this.step = '';
        this.offsetLeft = 0;
        this.offsetTop = 0;
        this.offsetWidth = 120;
        this.offsetHeight = 36;
        this.clientWidth = 120;
        this.clientHeight = 36;
        this._rect = { width: 120, height: 36, left: 0, top: 0 };
    }

    appendChild(child) {
        child.parentElement = this;
        this.children.push(child);
        return child;
    }

    click() {
        this.dispatchEvent({ type: 'click' });
    }

    removeAttribute(name) {
        if (Object.prototype.hasOwnProperty.call(this, name)) {
            this[name] = '';
        }
    }

    setBoundingRect(width, height) {
        this._rect = { width, height, left: 0, top: 0 };
        this.offsetWidth = width;
        this.offsetHeight = height;
        this.clientWidth = width;
        this.clientHeight = height;
    }

    getBoundingClientRect() {
        return {
            width: this._rect.width,
            height: this._rect.height,
            left: this._rect.left,
            top: this._rect.top,
            right: this._rect.left + this._rect.width,
            bottom: this._rect.top + this._rect.height
        };
    }

    querySelector(selector) {
        if (!selector) return null;
        if (selector.startsWith('.')) {
            const className = selector.slice(1);
            return this.findDescendant((child) => child.classList.contains(className));
        }
        if (selector.startsWith('#')) {
            const id = selector.slice(1);
            return this.findDescendant((child) => child.id === id);
        }
        return null;
    }

    findDescendant(predicate) {
        for (const child of this.children) {
            if (predicate(child)) {
                return child;
            }
            const nested = child.findDescendant?.(predicate);
            if (nested) {
                return nested;
            }
        }
        return null;
    }
}

function createGradient() {
    return {
        addColorStop() {}
    };
}

class FakeCanvasContext {
    constructor() {
        return new Proxy(this, {
            get(target, prop) {
                if (prop in target) {
                    return target[prop];
                }
                if (typeof prop === 'string') {
                    return () => {};
                }
                return undefined;
            }
        });
    }

    createLinearGradient() {
        return createGradient();
    }

    createRadialGradient() {
        return createGradient();
    }
}

class FakeCanvasElement extends FakeElement {
    constructor(id, width, height) {
        super(id, 'canvas');
        this.width = width;
        this.height = height;
        this.setBoundingRect(width, height);
        this._context = new FakeCanvasContext();
    }

    getContext(type) {
        if (type !== '2d') {
            return null;
        }
        return this._context;
    }
}

class FakeDocument {
    constructor() {
        this.elements = new Map();
        this.body = new FakeElement('body', 'body');
        this.body.classList.add('mode-file');
        this.activeElement = null;
    }

    register(element) {
        if (element.id) {
            this.elements.set(element.id, element);
        }
        return element;
    }

    getElementById(id) {
        return this.elements.get(id) || null;
    }
}

class FakeResizeObserver {
    constructor(callback) {
        this.callback = callback;
        this.targets = [];
    }

    observe(target) {
        this.targets.push(target);
    }

    disconnect() {}
}

let fakeNowMs = 0;
let nextAnimationFrameId = 1;
const animationFrameQueue = new Map();

function requestAnimationFrameFake(callback) {
    const id = nextAnimationFrameId++;
    animationFrameQueue.set(id, callback);
    return id;
}

function cancelAnimationFrameFake(id) {
    animationFrameQueue.delete(id);
}

function flushAnimationFrames(count = 1, stepMs = 16.67) {
    for (let i = 0; i < count; i++) {
        const callbacks = Array.from(animationFrameQueue.values());
        animationFrameQueue.clear();
        fakeNowMs += stepMs;
        callbacks.forEach((callback) => callback(fakeNowMs));
    }
}

class FakeWindow extends FakeEventTarget {
    constructor(document) {
        super();
        this.document = document;
        this.devicePixelRatio = 1;
        this.location = { search: '' };
    }

    requestAnimationFrame(callback) {
        return requestAnimationFrameFake(callback);
    }

    cancelAnimationFrame(id) {
        cancelAnimationFrameFake(id);
    }
}

class FakeWebSocket extends FakeEventTarget {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;
    static instances = [];

    constructor(url) {
        super();
        this.url = url;
        this.readyState = FakeWebSocket.CONNECTING;
        this.sent = [];
        FakeWebSocket.instances.push(this);
        queueMicrotask(() => {
            this.readyState = FakeWebSocket.OPEN;
            this.dispatchEvent({ type: 'open' });
        });
    }

    send(payload) {
        this.sent.push(JSON.parse(payload));
    }

    emitMessage(message) {
        this.dispatchEvent({
            type: 'message',
            data: JSON.stringify(message)
        });
    }

    close(code = 1000, reason = '') {
        if (this.readyState === FakeWebSocket.CLOSED) {
            return;
        }
        this.readyState = FakeWebSocket.CLOSED;
        this.dispatchEvent({ type: 'close', code, reason });
    }
}

function createElement(document, id, tagName = 'div', width = 120, height = 36) {
    const element = new FakeElement(id, tagName);
    element.setBoundingRect(width, height);
    return document.register(element);
}

function createCanvas(document, id, width, height) {
    return document.register(new FakeCanvasElement(id, width, height));
}

function setupDom() {
    const document = new FakeDocument();
    const window = new FakeWindow(document);

    const ids = [
        'modeBadge',
        'recordingControls',
        'loadData',
        'fileInput',
        'playPause',
        'reset',
        'prevFrame',
        'nextFrame',
        'timeline',
        'frameCounter',
        'timeDisplay',
        'liveControls',
        'liveConnectionState',
        'liveSessionState',
        'liveControllerType',
        'liveSimTime',
        'liveFrameBuffer',
        'liveControllerSelect',
        'liveSetpointLabel',
        'liveSetpointValue',
        'liveSlowdownFactor',
        'liveGeneratorVoltage',
        'liveCurrentMode',
        'liveOffTime',
        'livePauseResume',
        'liveRestart',
        'liveStop',
        'liveControlNote',
        'loadingOverlay',
        'speedControl',
        'timebaseControl',
        'linkViews',
        'toggleSideViewSparks',
        'toggleTopViewSparks',
        'toggleOscilloscope',
        'triggerEnable',
        'triggerSource',
        'triggerSlope',
        'triggerLevel',
        'triggerDelay',
        'voltageOffset',
        'currentOffset',
        'vPerDiv',
        'iPerDiv',
        'damagePlotWindow',
        'closePlotWindow',
        'damagePlotCanvas',
        'ch1Controls',
        'ch2Controls'
    ];

    ids.forEach((id) => createElement(document, id));
    document.getElementById('toggleSideViewSparks').textContent = 'Sparks ON';
    document.getElementById('toggleTopViewSparks').textContent = 'Sparks ON';
    document.getElementById('toggleOscilloscope').textContent = 'OFF';
    document.getElementById('speedControl').value = '60';
    document.getElementById('timebaseControl').value = 'auto';
    document.getElementById('triggerSource').value = 'ch1';
    document.getElementById('triggerSlope').value = 'rising';
    document.getElementById('triggerLevel').value = '50';
    document.getElementById('triggerDelay').value = '0';
    document.getElementById('vPerDiv').value = 'auto';
    document.getElementById('iPerDiv').value = 'auto';
    document.getElementById('liveControllerSelect').value = 'gap';
    document.getElementById('liveSetpointValue').value = '5';
    document.getElementById('liveSlowdownFactor').value = '10000';
    document.getElementById('liveGeneratorVoltage').value = '80';
    document.getElementById('liveCurrentMode').value = '7';
    document.getElementById('liveOffTime').value = '33';
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('liveControls').classList.add('live-disabled');
    document.getElementById('damagePlotWindow').style.display = 'none';
    document.getElementById('ch1Controls').offsetHeight = 72;
    document.getElementById('ch2Controls').offsetHeight = 72;

    const damageWindow = document.getElementById('damagePlotWindow');
    damageWindow.offsetLeft = 0;
    damageWindow.offsetTop = 0;
    damageWindow.setBoundingRect(640, 420);
    const damageHeader = new FakeElement('', 'div');
    damageHeader.classList.add('window-header');
    damageWindow.appendChild(damageHeader);
    damageWindow.appendChild(document.getElementById('closePlotWindow'));
    const damageContent = new FakeElement('', 'div');
    damageContent.classList.add('window-content');
    damageContent.setBoundingRect(600, 320);
    damageWindow.appendChild(damageContent);
    const damageCanvas = createCanvas(document, 'damagePlotCanvas', 600, 320);
    damageContent.appendChild(damageCanvas);

    const sideContainer = new FakeElement('', 'div');
    sideContainer.setBoundingRect(640, 280);
    const sideCanvas = createCanvas(document, 'sideViewCanvas', 640, 280);
    sideContainer.appendChild(sideCanvas);

    const thermalContainer = new FakeElement('', 'div');
    thermalContainer.setBoundingRect(640, 280);
    const thermalCanvas = createCanvas(document, 'thermalCanvas', 640, 280);
    thermalContainer.appendChild(thermalCanvas);

    const topContainer = new FakeElement('', 'div');
    topContainer.setBoundingRect(640, 280);
    const topCanvas = createCanvas(document, 'topViewCanvas', 640, 280);
    topContainer.appendChild(topCanvas);

    const oscContainer = new FakeElement('', 'div');
    oscContainer.setBoundingRect(900, 320);
    const oscCanvas = createCanvas(document, 'oscilloscopeCanvas', 900, 320);
    oscContainer.appendChild(oscCanvas);

    globalThis.document = document;
    globalThis.window = window;
    globalThis.ResizeObserver = FakeResizeObserver;
    globalThis.requestAnimationFrame = requestAnimationFrameFake;
    globalThis.cancelAnimationFrame = cancelAnimationFrameFake;
    globalThis.alert = () => {};
    globalThis.confirm = () => true;
    globalThis.FileReader = class {};
    Object.defineProperty(globalThis, 'performance', {
        configurable: true,
        value: { now: () => fakeNowMs }
    });

    return { document, window };
}

function buildSessionHeader() {
    return {
        v: 1,
        type: 'session_header',
        payload: {
            state: 'created',
            metadata: {
                workpiece_height_mm: 20.0,
                wire_diameter: 0.25,
                wire_diameter_um: 250,
                wire_unwinding_speed_mm_per_ms: 0.2,
                buffer_len_bottom: 30.0,
                buffer_len_top: 30.0,
                contact_offset_bottom: 10.0,
                contact_offset_top: 10.0,
                segment_len_mm: 0.2,
                control_mode: 'servo',
                controller_strategy: 'gap',
                dt_us: 1,
                servo_interval_us: 1000
            },
            supported_params: [
                'controller_type',
                'target_gap',
                'target_avg_voltage',
                'fixed_servo',
                'generator_voltage',
                'current_mode',
                'off_time',
                'slowdown_factor'
            ],
            current_params: {
                controller_type: 'gap',
                target_gap: 5.0,
                target_avg_voltage: 50.0,
                fixed_servo: 0.0,
                generator_voltage: 80.0,
                current_mode: 7,
                on_time: 2.0,
                off_time: 33.0,
                slowdown_factor: 100.0
            },
            requested_slowdown_factor: 100.0,
            min_slowdown_factor: 12.5,
            max_sim_us_per_wall_second: 80000.0,
            control_compute_wall_s: 0.002
        }
    };
}

function buildSessionState(overrides = {}) {
    return {
        v: 1,
        type: 'session_state',
        payload: {
            state: 'running',
            slowdown_factor: 100.0,
            requested_slowdown_factor: 100.0,
            solver_limited: false,
            min_slowdown_factor: 12.5,
            max_sim_us_per_wall_second: 80000.0,
            control_compute_wall_s: 0.002,
            simulated_time_us: 0,
            control_steps: 0,
            wall_time_s: 0.0,
            termination_reason: null,
            current_params: {
                controller_type: 'gap',
                target_gap: 5.0,
                target_avg_voltage: 50.0,
                fixed_servo: 0.0,
                generator_voltage: 80.0,
                current_mode: 7,
                on_time: 2.0,
                off_time: 33.0,
                slowdown_factor: 100.0
            },
            ...overrides
        }
    };
}

function buildPulseChunk(baseTimeUs) {
    return {
        v: 1,
        type: 'pulse_chunk',
        payload: {
            base_time_us: baseTimeUs,
            dt_us: 1,
            voltage: [0, 80, 0, 80, 0, 80],
            current: [0, 6, 0, 6, 0, 6],
            spark_state: [0, 1, 0, 1, 0, 1]
        }
    };
}

function buildProcessFrame(frameIndex, offTimeUs = 33) {
    const timeUs = (frameIndex + 1) * 1000;
    const basePosition = 10 + (frameIndex * 0.2);
    return {
        v: 1,
        type: 'process_frame',
        payload: {
            time_us: timeUs,
            wire_position_um: 10000 + frameIndex * 40,
            wire_velocity_um_s: 200000,
            workpiece_position_um: 70000,
            target_delta: 5.0,
            target_voltage: 50.0,
            current_mode: 'I7',
            on_time_us: 2.0,
            off_time_us: offTimeUs,
            voltage: 42.0 + frameIndex,
            current: 6.0,
            spark_state: 1,
            spark_location_mm: 40 + frameIndex,
            spark_duration: 1,
            is_short_circuit: false,
            debris_density: 0.12,
            flow_rate: 1.0,
            wire_head_idx: 0,
            wire_offset_mm: frameIndex * 0.2,
            is_wire_broken: false,
            spark_events: [
                {
                    time_us: timeUs - 100,
                    location_mm: 40 + frameIndex
                }
            ],
            wire_temperature: [
                320 + frameIndex,
                325 + frameIndex,
                330 + frameIndex,
                335 + frameIndex,
                340 + frameIndex
            ],
            wire_damage: [
                0.01 * (frameIndex + 1),
                0.02 * (frameIndex + 1),
                0.03 * (frameIndex + 1),
                0.04 * (frameIndex + 1),
                0.05 * (frameIndex + 1)
            ],
            wire_material_positions_mm: [
                basePosition,
                basePosition + 0.2,
                basePosition + 0.4,
                basePosition + 0.6,
                basePosition + 0.8
            ]
        }
    };
}

setupDom();

const { DashboardController } = await import('../visualization/js/DashboardController.js');

const controller = new DashboardController();
const drawCounts = {};
for (const [panelName, panel] of Object.entries(controller.panels)) {
    drawCounts[panelName] = 0;
    const originalDraw = panel.draw.bind(panel);
    panel.draw = (...args) => {
        drawCounts[panelName] += 1;
        return originalDraw(...args);
    };
}

controller.elements.toggleOscilloscope.click();

await controller.connectLiveStream('ws://fake-live-session', {
    WebSocketImpl: FakeWebSocket,
    maxProcessFrames: 3,
    maxPulseSamples: 12,
    reconnectDelaysMs: [5]
});

const socket = FakeWebSocket.instances.at(-1);
assert.ok(socket, 'expected a fake websocket instance');

socket.emitMessage(buildSessionHeader());
socket.emitMessage(buildSessionState());

for (let frameIndex = 0; frameIndex < 4; frameIndex++) {
    socket.emitMessage(buildPulseChunk(1 + frameIndex * 6));
    socket.emitMessage(buildProcessFrame(frameIndex));
}

flushAnimationFrames(3);

assert.equal(controller.isLiveMode(), true);
assert.equal(controller.getTotalFrames(), 3);
assert.equal(controller.currentFrame, 2);
assert.equal(controller.dataSource.getPulseHistory().voltage.length, 12);
assert.equal(controller.dataSource.getPulseHistory().baseTimeUs, 13);
assert.match(controller.elements.modeBadge.textContent, /^Live$/);
assert.match(controller.elements.liveFrameBuffer.textContent, /Buffered frames: 3/);
assert.ok(drawCounts.sideView > 0, 'side view should render in live mode');
assert.ok(drawCounts.topView > 0, 'top view should render in live mode');
assert.ok(drawCounts.thermal > 0, 'thermal panel should render in live mode');
assert.ok(drawCounts.oscilloscope > 0, 'oscilloscope should render in live mode');

controller.elements.liveOffTime.value = '17';
controller.elements.liveOffTime.dispatchEvent({ type: 'change' });

assert.deepEqual(socket.sent.at(-1), {
    v: 1,
    type: 'set_param',
    payload: { name: 'off_time', value: 17 }
});

socket.emitMessage(buildSessionState({
    current_params: {
        controller_type: 'gap',
        target_gap: 5.0,
        target_avg_voltage: 50.0,
        fixed_servo: 0.0,
        generator_voltage: 80.0,
        current_mode: 7,
        on_time: 2.0,
        off_time: 17.0,
        slowdown_factor: 100.0
    }
}));
socket.emitMessage(buildPulseChunk(25));
socket.emitMessage(buildProcessFrame(4, 17));
flushAnimationFrames(2);

assert.equal(controller.data.live_session.currentParams.off_time, 17.0);
assert.equal(controller.getFrameData(controller.getTotalFrames() - 1).OFF_time, 17.0);

controller.elements.livePauseResume.click();
assert.equal(socket.sent.at(-1).type, 'pause');

socket.emitMessage(buildSessionState({
    state: 'paused',
    simulated_time_us: 5000,
    control_steps: 5,
    current_params: {
        controller_type: 'gap',
        target_gap: 5.0,
        target_avg_voltage: 50.0,
        fixed_servo: 0.0,
        generator_voltage: 80.0,
        current_mode: 7,
        on_time: 2.0,
        off_time: 17.0,
        slowdown_factor: 100.0
    }
}));

assert.equal(controller.elements.livePauseResume.textContent, 'Resume');

controller.elements.livePauseResume.click();
assert.equal(socket.sent.at(-1).type, 'resume');

socket.emitMessage(buildSessionState({
    state: 'running',
    simulated_time_us: 6000,
    control_steps: 6,
    current_params: {
        controller_type: 'gap',
        target_gap: 5.0,
        target_avg_voltage: 50.0,
        fixed_servo: 0.0,
        generator_voltage: 80.0,
        current_mode: 7,
        on_time: 2.0,
        off_time: 17.0,
        slowdown_factor: 100.0
    }
}));

flushAnimationFrames(1);

assert.equal(controller.data.live_session.sessionState, 'running');
assert.equal(controller.elements.livePauseResume.textContent, 'Pause');
assert.equal(controller.dataSource.getFrameCount(), 3);

console.log('dashboard live integration harness passed');
