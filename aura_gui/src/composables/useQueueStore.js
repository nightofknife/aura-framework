import { ref } from 'vue';
import axios from 'axios';

// 纯粹的数据存储
const overview = ref(null);
const ready = ref([]);
const delayed = ref([]);

const api = axios.create({ baseURL: 'http://127.0.0.1:18098/api', timeout: 5000 });

/**
 * 主动获取队列概览。
 * 这个函数现在是获取概览数据的唯一方式。
 */
async function fetchOverview() {
    try {
        const { data } = await api.get('/queue/overview');
        overview.value = data || null;
    } catch (e) {
        console.warn('Failed to fetch queue overview', e);
        overview.value = null;
    }
}

/**
 * 主动获取队列列表。
 */
async function fetchList(state) { // 'ready'|'delayed'
    try {
        const { data } = await api.get('/queue/list', { params: { state, limit: 200 } });
        const arr = data?.items || [];
        if (state === 'ready') ready.value = arr;
        if (state === 'delayed') delayed.value = arr;
    } catch (e) {
        console.warn(`Failed to fetch queue list for state: ${state}`, e);
    }
}

/**
 * 由外部（useStagingRunner）调用的函数，用于设置队列数据。
 * @param {string} state - 'ready' or 'delayed'
 * @param {Array} items - 新的队列项目列表
 */
function setQueueState(state, items) {
    if (state === 'ready') {
        ready.value = items;
    } else if (state === 'delayed') {
        delayed.value = items;
    }
}

export function useQueueStore() {
    // 不再导出 ingest
    return {
        overview,
        ready,
        delayed,
        fetchOverview,
        fetchList,
        setQueueState, // 暴露给 useStagingRunner
    };
}
