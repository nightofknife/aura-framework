import { ref, onMounted, onUnmounted } from 'vue';

const socket = ref(null);
const isConnected = ref(false);
const lastMessage = ref(null);
const error = ref(null);

function normalizeName(v) {
    return String(v || '')
        .trim()
        .toLowerCase()
        .replace(/[_\s:-]+/g, '.')
        .replace(/\.+/g, '.'); // 合并多余的点
}

/** 统一成 { name:'task.finished', payload:{...} } / { name:'log', payload:{...} } */
function parseEventData(data) {
    try {
        const raw = JSON.parse(data);
        if (raw && typeof raw === 'object') {
            if (raw.type === 'event' && raw.payload) {
                const inner = raw.payload || {};
                const name = normalizeName(inner.name || inner.event || inner.type || '');
                const payload = inner.payload ?? inner.data ??
                    Object.fromEntries(Object.entries(inner).filter(([k]) => !['name','event','type'].includes(k)));
                return { name, payload };
            }
            if (raw.type === 'log' && raw.payload) return { name: 'log', payload: raw.payload };

            const name = normalizeName(raw.name || raw.event || raw.type || '');
            const payload = raw.payload ?? raw.data ?? raw;
            return { name, payload };
        }
        return { name: '', payload: raw };
    } catch {
        return { name: 'unknown', payload: { message: String(data) } };
    }
}

function bindSocket(ws) {
    ws.onopen = () => { isConnected.value = true; error.value = null; };
    ws.onmessage = (e) => { lastMessage.value = parseEventData(e.data); };
    ws.onerror = () => { error.value = 'WebSocket connection failed.'; };
    ws.onclose = () => { isConnected.value = false; };
}

function ensureConnected() {
    if (socket.value && socket.value.readyState <= 1) return;
    const url = (import.meta?.env?.VITE_WS_URL) || 'ws://127.0.0.1:8000/ws/events';
    const ws = new WebSocket(url);
    socket.value = ws;
    bindSocket(ws);
}

export function useAuraSocket() {
    onMounted(() => { ensureConnected(); });
    onUnmounted(() => { /* 保持长连 */ });
    return { isConnected, lastMessage, error, connect: ensureConnected };
}
