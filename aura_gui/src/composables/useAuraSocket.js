// src/composables/useAuraSocket.js
import {ref, onMounted, onUnmounted} from 'vue';

const socket = ref(null);
const isConnected = ref(false);
const lastMessage = ref(null);
const error = ref(null);

function parseEventData(data) {
    try {
        const raw = JSON.parse(data);
        if (raw && raw.type === 'event' && raw.payload) return raw.payload;
        return raw;
    } catch {
        return {name: 'unknown', payload: {message: String(data)}};
    }
}

function bindSocket(ws) {
    ws.onopen = () => {
        isConnected.value = true;
        error.value = null;
    };
    ws.onmessage = (e) => {
        lastMessage.value = parseEventData(e.data);
    };
    ws.onerror = () => {
        error.value = 'WebSocket connection failed.';
    };
    ws.onclose = () => {
        isConnected.value = false;
    };
}

function ensureConnected() {
    if (socket.value && socket.value.readyState <= 1) return;
    const url = (import.meta?.env?.VITE_WS_URL) || 'ws://127.0.0.1:8000/ws/events';
    socket.value = new WebSocket(url);
    bindSocket(socket.value);
}

export function useAuraSocket() {
    onMounted(() => {
        ensureConnected();
    });
    onUnmounted(() => { /* 可选：不主动关闭以便全局复用 */
    });
    return {isConnected, lastMessage, error, connect: ensureConnected};
}
