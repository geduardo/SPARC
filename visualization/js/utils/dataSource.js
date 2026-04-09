const DEFAULT_PROCESS_FRAME_CAPACITY = 1000;
const DEFAULT_PULSE_SAMPLE_CAPACITY = 100000;
const DEFAULT_RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000];

const PROCESS_FRAME_FIELDS = {
    time: ['time', 'time_us'],
    voltage: ['voltage'],
    current: ['current'],
    wire_position: ['wire_position', 'wire_position_um'],
    wire_velocity: ['wire_velocity', 'wire_velocity_um_s'],
    workpiece_position: ['workpiece_position', 'workpiece_position_um'],
    target_delta: ['target_delta'],
    target_voltage: ['target_voltage'],
    current_mode: ['current_mode'],
    ON_time: ['ON_time', 'on_time_us'],
    OFF_time: ['OFF_time', 'off_time_us'],
    spark_events: ['spark_events'],
    is_short_circuit: ['is_short_circuit'],
    flow_rate: ['flow_rate'],
    debris_density: ['debris_density'],
    wire_head_idx: ['wire_head_idx'],
    wire_offset_mm: ['wire_offset_mm'],
    wire_temperature: ['wire_temperature'],
    wire_damage: ['wire_damage'],
    wire_material_positions_mm: ['wire_material_positions_mm']
};

function createEmptyDataShape() {
    return {
        metadata: {},
        time: [],
        voltage: [],
        current: [],
        wire_position: [],
        wire_velocity: [],
        workpiece_position: [],
        target_delta: [],
        target_voltage: [],
        current_mode: [],
        ON_time: [],
        OFF_time: [],
        spark_events: [],
        spark_status: [],
        is_short_circuit: [],
        flow_rate: [],
        debris_density: [],
        wire_temperature: [],
        wire_damage: [],
        wire_material_positions_mm: [],
        wire_head_idx: [],
        wire_offset_mm: [],
        live_session: {
            connectionState: 'disconnected',
            sessionState: 'created',
            supportedParams: [],
            currentParams: {},
            solverLimited: false,
            lastError: null
        }
    };
}

function createEmptyPulseHistory() {
    return {
        baseTimeUs: 0,
        dtUs: 1,
        voltage: [],
        current: [],
        sparkState: []
    };
}

function pickFirstDefined(obj, aliases, fallback = undefined) {
    for (const alias of aliases) {
        if (Object.prototype.hasOwnProperty.call(obj, alias) && obj[alias] !== undefined) {
            return obj[alias];
        }
    }
    return fallback;
}

function cloneVector(value) {
    if (Array.isArray(value)) return value.slice();
    if (ArrayBuffer.isView(value)) return Array.from(value);
    return [];
}

function normalizeSparkStatus(frame) {
    if (Array.isArray(frame.spark_status)) {
        const [state = 0, location = null, extra = 0] = frame.spark_status;
        return [state, location, extra];
    }
    const state = pickFirstDefined(frame, ['spark_state', 'spark_status_state'], 0);
    const location = pickFirstDefined(frame, ['spark_location_mm', 'spark_status_location_mm'], null);
    const extra = pickFirstDefined(frame, ['spark_duration', 'spark_status_extra'], 0);
    return [state, location, extra];
}

function normalizeSparkEvents(frame) {
    const rawEvents = pickFirstDefined(frame, ['spark_events'], []);
    if (!Array.isArray(rawEvents)) return [];

    return rawEvents
        .map((event) => {
            if (!event || typeof event !== 'object') return null;
            const timeUS = Number(pickFirstDefined(event, ['time_us', 'timeUS'], NaN));
            const locationMM = Number(pickFirstDefined(event, ['location_mm', 'locationMM'], NaN));
            if (!Number.isFinite(timeUS) || !Number.isFinite(locationMM)) {
                return null;
            }
            return { timeUS, locationMM };
        })
        .filter(Boolean);
}

function appendProcessFrame(data, frame) {
    for (const [targetKey, aliases] of Object.entries(PROCESS_FRAME_FIELDS)) {
        if (targetKey === 'spark_events') {
            data.spark_events.push(normalizeSparkEvents(frame));
            continue;
        }
        const rawValue = pickFirstDefined(frame, aliases);
        if (targetKey === 'wire_temperature' || targetKey === 'wire_damage' || targetKey === 'wire_material_positions_mm') {
            data[targetKey].push(cloneVector(rawValue));
        } else {
            data[targetKey].push(rawValue ?? null);
        }
    }

    data.spark_status.push(normalizeSparkStatus(frame));
}

function trimProcessData(data, maxFrames) {
    const frameCount = Array.isArray(data.time) ? data.time.length : 0;
    if (frameCount <= maxFrames) return 0;

    const dropCount = frameCount - maxFrames;
    for (const [key, value] of Object.entries(data)) {
        if (key === 'metadata' || key === 'live_session') continue;
        if (Array.isArray(value)) {
            value.splice(0, dropCount);
        }
    }
    return dropCount;
}

function normalizeSessionHeader(message) {
    const payload = message.payload || message.data || message.header || message;
    const metadata = payload.metadata || {};
    return {
        metadata,
        supportedParams: payload.supported_params || payload.supportedParams || [],
        currentParams: payload.current_params || payload.currentParams || {},
        sessionState: payload.state || payload.session_state || 'created'
    };
}

function normalizePulseChunk(message) {
    const payload = message.payload || message.data || message.chunk || message;
    return {
        base_time_us: pickFirstDefined(payload, ['base_time_us', 'baseTimeUs'], 0),
        dt_us: pickFirstDefined(payload, ['dt_us', 'dtUs'], 1),
        voltage: cloneVector(payload.voltage || []),
        current: cloneVector(payload.current || []),
        spark_state: cloneVector(payload.spark_state || payload.sparkState || [])
    };
}

export class DashboardDataSource {
    constructor() {
        this.data = createEmptyDataShape();
        this.listeners = new Set();
        this.isLive = false;
    }

    subscribe(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    unsubscribe(listener) {
        this.listeners.delete(listener);
    }

    emit(event) {
        this.listeners.forEach((listener) => listener(event));
    }

    getData() {
        return this.data;
    }

    getFrameCount() {
        const time = this.data && this.data.time;
        return Array.isArray(time) || ArrayBuffer.isView(time) ? time.length : 0;
    }

    async connect() {
        return this;
    }

    getPulseChunks() {
        return [];
    }

    getPulseHistory() {
        return null;
    }

    disconnect() {}
}

export class FileDashboardDataSource extends DashboardDataSource {
    constructor(data) {
        super();
        this.data = data || createEmptyDataShape();
        if (!this.data.metadata) {
            this.data.metadata = {};
        }
        if (!this.data.live_session) {
            this.data.live_session = {
                connectionState: 'file',
                sessionState: 'stopped',
                supportedParams: [],
                currentParams: {},
                solverLimited: false,
                lastError: null
            };
        }
    }

    getPulseHistory() {
        const voltage = this.data && this.data.voltage;
        const current = this.data && this.data.current;
        if (!(Array.isArray(voltage) || ArrayBuffer.isView(voltage)) ||
            !(Array.isArray(current) || ArrayBuffer.isView(current))) {
            return null;
        }

        const time = this.data && this.data.time;
        const baseTimeUs = time && time.length > 0 ? Number(time[0]) : 0;
        let dtUs = 1;
        if (time && time.length > 1) {
            const inferredDt = Number(time[1]) - Number(time[0]);
            if (Number.isFinite(inferredDt) && inferredDt > 0) {
                dtUs = inferredDt;
            }
        }

        const sparkState = this.data.spark_status_state || this.data.sparkState || [];
        return {
            baseTimeUs,
            dtUs,
            voltage,
            current,
            sparkState
        };
    }
}

export class LiveDashboardDataSource extends DashboardDataSource {
    constructor(url, options = {}) {
        super();
        this.url = url;
        this.isLive = true;
        this.maxProcessFrames = options.maxProcessFrames || DEFAULT_PROCESS_FRAME_CAPACITY;
        this.maxPulseSamples = options.maxPulseSamples || DEFAULT_PULSE_SAMPLE_CAPACITY;
        this.reconnectDelaysMs = options.reconnectDelaysMs || DEFAULT_RECONNECT_DELAYS_MS;
        this.WebSocketImpl = options.WebSocketImpl || WebSocket;
        this.socket = null;
        this.pulseChunks = [];
        this.pulseHistory = createEmptyPulseHistory();
        this.totalPulseSamples = 0;
        this.manualDisconnect = false;
        this.reconnectTimer = null;
        this.reconnectAttempt = 0;
    }

    async connect() {
        this.manualDisconnect = false;
        return this.openSocket();
    }

    getPulseChunks() {
        return this.pulseChunks;
    }

    getPulseHistory() {
        return this.pulseHistory;
    }

    disconnect() {
        this.manualDisconnect = true;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.socket) {
            this.socket.close();
            this.socket = null;
        }
        this.data.live_session.connectionState = 'disconnected';
        this.emit({ type: 'disconnected', manual: true });
    }

    send(message) {
        if (!this.socket || this.socket.readyState !== this.WebSocketImpl.OPEN) {
            return false;
        }
        this.socket.send(JSON.stringify(message));
        return true;
    }

    openSocket() {
        return new Promise((resolve, reject) => {
            let settled = false;
            const socket = new this.WebSocketImpl(this.url);
            this.socket = socket;
            this.data.live_session.connectionState = 'connecting';

            socket.addEventListener('open', () => {
                this.reconnectAttempt = 0;
                this.data.live_session.connectionState = 'connected';
                this.emit({ type: 'connected' });
                if (!settled) {
                    settled = true;
                    resolve(this);
                }
            });

            socket.addEventListener('message', (event) => {
                try {
                    this.handleSocketMessage(event.data);
                } catch (error) {
                    console.error('Live data source message handling failed:', error);
                    this.emit({ type: 'error', error });
                }
            });

            socket.addEventListener('error', (event) => {
                this.emit({ type: 'error', error: event });
                if (!settled) {
                    settled = true;
                    reject(new Error('WebSocket connection failed'));
                }
            });

            socket.addEventListener('close', () => {
                this.data.live_session.connectionState = 'disconnected';
                this.emit({ type: 'disconnected', manual: this.manualDisconnect });
                if (!this.manualDisconnect) {
                    this.scheduleReconnect();
                }
            });
        });
    }

    scheduleReconnect() {
        if (this.reconnectTimer) return;

        const delay = this.reconnectDelaysMs[
            Math.min(this.reconnectAttempt, this.reconnectDelaysMs.length - 1)
        ];
        this.reconnectAttempt += 1;
        this.emit({ type: 'reconnecting', attempt: this.reconnectAttempt, delayMs: delay });
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.connect().catch((error) => {
                console.error('Live data source reconnect failed:', error);
            });
        }, delay);
    }

    handleSocketMessage(rawMessage) {
        let message = rawMessage;
        if (typeof rawMessage === 'string') {
            message = JSON.parse(rawMessage);
        } else if (rawMessage instanceof ArrayBuffer) {
            throw new Error('Binary live messages are not supported yet');
        } else if (rawMessage && typeof rawMessage.text === 'function') {
            throw new Error('Blob live messages are not supported yet');
        }

        const type = message.type || message.event;
        switch (type) {
            case 'session_header':
                this.handleSessionHeader(message);
                break;
            case 'process_frame':
                this.handleProcessFrame(message);
                break;
            case 'pulse_chunk':
                this.handlePulseChunk(message);
                break;
            case 'session_state':
                this.handleSessionState(message);
                break;
            case 'error':
                this.data.live_session.lastError = message.payload?.message || message.message || 'live session error';
                this.emit({ type: 'error', error: message });
                break;
            default:
                this.emit({ type: 'message', message });
                break;
        }
    }

    handleSessionHeader(message) {
        const header = normalizeSessionHeader(message);
        this.data.metadata = Object.assign({}, this.data.metadata, header.metadata);
        this.data.live_session.supportedParams = header.supportedParams;
        this.data.live_session.currentParams = header.currentParams;
        this.data.live_session.sessionState = header.sessionState;
        this.data.live_session.lastError = null;
        this.emit({ type: 'header', header });
    }

    handleProcessFrame(message) {
        const frame = message.payload || message.data || message.frame || message;
        appendProcessFrame(this.data, frame);
        const dropped = trimProcessData(this.data, this.maxProcessFrames);
        this.emit({
            type: 'process_frame',
            frame,
            frameCount: this.getFrameCount(),
            droppedFrames: dropped
        });
        if (dropped > 0) {
            this.emit({ type: 'backpressure', droppedFrames: dropped });
        }
    }

    handlePulseChunk(message) {
        const chunk = normalizePulseChunk(message);
        let droppedSamples = 0;

        this.pulseChunks.push(chunk);
        this.pulseHistory.dtUs = chunk.dt_us || this.pulseHistory.dtUs || 1;
        if (this.totalPulseSamples === 0) {
            this.pulseHistory.baseTimeUs = chunk.base_time_us;
        }
        this.pulseHistory.voltage.push(...chunk.voltage);
        this.pulseHistory.current.push(...chunk.current);
        this.pulseHistory.sparkState.push(...chunk.spark_state);
        this.totalPulseSamples += chunk.voltage.length;

        while (this.totalPulseSamples > this.maxPulseSamples && this.pulseChunks.length > 0) {
            const dropped = this.pulseChunks.shift();
            this.totalPulseSamples -= dropped.voltage.length;
            droppedSamples += dropped.voltage.length;
        }

        if (droppedSamples > 0) {
            this.pulseHistory.voltage.splice(0, droppedSamples);
            this.pulseHistory.current.splice(0, droppedSamples);
            this.pulseHistory.sparkState.splice(0, droppedSamples);
        }

        if (this.pulseChunks.length > 0) {
            this.pulseHistory.baseTimeUs = this.pulseChunks[0].base_time_us;
        } else if (this.totalPulseSamples === 0) {
            this.pulseHistory.baseTimeUs = 0;
        }

        this.emit({
            type: 'pulse_chunk',
            chunk,
            totalPulseSamples: this.totalPulseSamples,
            droppedSamples
        });
    }

    handleSessionState(message) {
        const payload = message.payload || message.data || message;
        const state = payload.state || payload.session_state || payload.status || 'running';
        const currentParams = payload.current_params || payload.currentParams;
        this.data.live_session.sessionState = state;
        if (currentParams && typeof currentParams === 'object') {
            this.data.live_session.currentParams = currentParams;
        }
        this.data.live_session.solverLimited = !!(payload.solver_limited || payload.solverLimited);
        this.data.live_session.lastError = null;
        this.emit({ type: 'session_state', state, payload });
    }
}
