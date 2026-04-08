// === src/composables/useBackendQueue.js ===
import { ref } from 'vue';
import axios from 'axios';
import { getGuiConfig } from '../config.js';

const cfg = getGuiConfig();
const api = axios.create({
    baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
    timeout: cfg?.api?.timeout_ms || 5000,
});

const readyQueue = ref([]);
const overview = ref(null);
const activeRuns = ref([]);

async function fetchReady() {
    try {
        const limit = cfg?.api?.queue_list_limit || 200;
        const { data } = await api.get('/queue/list', { params: { state: 'ready', limit } });
        readyQueue.value = data?.items || [];
        console.log('[BackendQueue] ready items:', readyQueue.value.length, readyQueue.value);
        const invalid = readyQueue.value.filter(it => !it.cid);
        if (invalid.length) {
            console.warn('[BackendQueue] items without cid:', invalid);
        }
    } catch (e) {
        readyQueue.value = [];
    }
}

async function fetchOverview() {
    try {
        const { data } = await api.get('/queue/overview');
        overview.value = data || null;
    } catch (e) {
        overview.value = null;
    }
}

async function fetchActiveRuns() {
    try {
        const { data } = await api.get('/runs/active');
        activeRuns.value = data || [];
        console.log('[BackendQueue] active runs:', activeRuns.value.length, activeRuns.value);
    } catch (e) {
        activeRuns.value = [];
    }
}

async function remove(cid) {
    await api.delete(`/queue/${cid}`);
}

async function moveFront(cid) {
    await api.post(`/queue/${cid}/move-to-front`);
}

async function clear() {
    await api.delete('/queue/clear');
}

export function useBackendQueue() {
    return {
        readyQueue,
        overview,
        fetchReady,
        fetchOverview,
        activeRuns,
        fetchActiveRuns,
        remove,
        moveFront,
        clear,
    };
}
