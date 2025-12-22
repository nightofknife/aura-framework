// === src/composables/useAuraSockets.js ===
import { ref, onMounted, onUnmounted } from 'vue';
import { getGuiConfig } from '../config.js';

// --- 内部状态与逻辑 ---
function createManagedSocket(url, name) {
    const socket = ref(null);
    const isConnected = ref(false);
    const lastMessage = ref(null);
    const error = ref(null);
    const status = ref('idle');
    const retries = ref(0);
    const nextRetryAt = ref(null);

    let reconnectTimer = null;
    let heartbeatTimer = null;
    let manualClose = false;

    const cfg = getGuiConfig();
    const BASE_DELAY = cfg?.ws?.reconnect?.base_ms ?? 5000;
    const MULTIPLIER = cfg?.ws?.reconnect?.multiplier ?? 2;
    const MAX_DELAY = cfg?.ws?.reconnect?.max_ms ?? 30000;
    const JITTER = cfg?.ws?.reconnect?.jitter ?? 0.2;
    let currentDelay = BASE_DELAY;

    function parseMessage(data) {
        try {
            return JSON.parse(data);
        } catch {
            return { type: 'unknown', payload: String(data) };
        }
    }

    function clearReconnectTimer() {
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    }

    function startHeartbeat() {
        stopHeartbeat();
        const heartbeatMs = cfg?.ws?.heartbeat_ms ?? 25000;
        heartbeatTimer = setInterval(() => {
            if (socket.value && socket.value.readyState === WebSocket.OPEN) {
                try { socket.value.send(JSON.stringify({ type: 'ping', ts: Date.now() })); } catch {}
            }
        }, heartbeatMs);
    }

    function stopHeartbeat() {
        if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
    }

    function scheduleReconnect() {
        if (manualClose) return;
        currentDelay = (retries.value === 0) ? BASE_DELAY : Math.min(MAX_DELAY, currentDelay * MULTIPLIER);
        const jitter = 1 + (Math.random() * 2 - 1) * JITTER;
        const delay = Math.floor(currentDelay * jitter);
        status.value = 'reconnecting';
        nextRetryAt.value = Date.now() + delay;
        clearReconnectTimer();
        reconnectTimer = setTimeout(() => ensureConnected(), delay);
    }

    function bindSocket(ws) {
        ws.onopen = () => {
            isConnected.value = true;
            status.value = 'open';
            error.value = null;
            retries.value = 0;
            currentDelay = BASE_DELAY;
            nextRetryAt.value = null;
            startHeartbeat();
        };
        ws.onmessage = (e) => { lastMessage.value = parseMessage(e.data); };
        ws.onerror = (e) => {
            error.value = `WebSocket (${name}) connection failed.`;
            status.value = 'error';
        };
        ws.onclose = () => {
            isConnected.value = false;
            stopHeartbeat();
            socket.value = null;
            if (manualClose) {
                status.value = 'closed';
                manualClose = false;
                return;
            }
            retries.value += 1;
            scheduleReconnect();
        };
    }

    function ensureConnected() {
        if (socket.value && (socket.value.readyState === WebSocket.OPEN || socket.value.readyState === WebSocket.CONNECTING)) {
            return;
        }
        manualClose = false;
        clearReconnectTimer();
        try {
            status.value = (retries.value > 0) ? 'reconnecting' : 'connecting';
            const ws = new WebSocket(url);
            socket.value = ws;
            bindSocket(ws);
        } catch (e) {
            error.value = `WebSocket (${name}) init failed: ${e?.message}`;
            status.value = 'error';
            scheduleReconnect();
        }
    }

    function disconnect() {
        manualClose = true;
        clearReconnectTimer();
        stopHeartbeat();
        if (socket.value) {
            try { socket.value.close(); } catch {}
            socket.value = null;
        }
        status.value = 'closed';
    }

    function send(data) {
        if (!socket.value || socket.value.readyState !== WebSocket.OPEN) return false;
        try {
            socket.value.send(typeof data === 'string' ? data : JSON.stringify(data));
            return true;
        } catch { return false; }
    }

    return {
        isConnected, lastMessage, error, status, retries, nextRetryAt,
        connect: ensureConnected, disconnect, send,
    };
}

// --- 创建并导出日志 Socket 实例（移除控制通道） ---
const cfg = getGuiConfig();
const VITE_BASE_URL = cfg?.ws?.base_url || (import.meta?.env?.VITE_WS_URL) || 'ws://127.0.0.1:18098';

const logSocketManager = createManagedSocket(`${VITE_BASE_URL}/ws/logs`, 'Logs');

export function useAuraSockets() {
    onMounted(() => {
        logSocketManager.connect();
    });

    onUnmounted(() => {
        // 全局长连，通常不在此处断开
    });

    return {
        logs: logSocketManager,
        // ❌ 移除 control 通道
    };
}
