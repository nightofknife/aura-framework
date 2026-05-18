// === src/composables/useBackendQueue.js ===
import { ref } from 'vue';
import { getGuiConfig } from '../config.js';
import { api } from '../api/client.js';

const cfg = getGuiConfig();

const readyQueue = ref([]);
const overview = ref(null);
const activeRuns = ref([]);

async function fetchReady() {
    try {
        const limit = cfg?.api?.queue_list_limit || 200;
        const data = await api.get('/queue/list', { params: { state: 'ready', limit } });
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
        overview.value = await api.get('/queue/overview') || null;
    } catch (e) {
        overview.value = null;
    }
}

async function fetchActiveRuns() {
    try {
        activeRuns.value = await api.get('/runs/active') || [];
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
