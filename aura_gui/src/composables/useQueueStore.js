// src/composables/useQueueStore.js
import {ref} from 'vue';
import axios from 'axios';

// 统一 key：优先 run_id，退化到 plan/task + enqueued_at
function keyOf(p) {
    if (p.run_id) return p.run_id;
    const t = p.enqueued_at ?? p.delay_until ?? Date.now() / 1000;
    return `${p.plan_name || ''}/${p.task_name || ''}:${t}`;
}

// src/composables/useQueueStore.js
function normalizeItem(p) {
    const it = {...p};
    it.__key = keyOf(p);
    // 新增：入队时就确定一个初始状态（用于 UI 展示）
    it.status = p.status
        || (p.delay_until ? 'DELAYED' : 'READY');
    return it;
}


const overview = ref({});
const ready = ref([]);
const delayed = ref([]);

const api = axios.create({baseURL: 'http://127.0.0.1:8000/api', timeout: 5000});

async function fetchOverview() {
    try {
        const {data} = await api.get('/queue/overview');
        overview.value = data || {};
    } catch (e) {
        // 后端未实现也不报错，留空
        // console.warn('queue overview not available', e);
    }
}

async function fetchList(state) { // 'ready'|'delayed'
    try {
        const {data} = await api.get('/queue/list', {params: {state, limit: 200}});
        const arr = (data?.items || []).map(normalizeItem);
        if (state === 'ready') ready.value = arr;
        if (state === 'delayed') delayed.value = arr;
    } catch (e) {
        // 未实现时忽略
    }
}

function upsert(listRef, item) {
    const arr = listRef.value.slice();
    const idx = arr.findIndex(x => x.__key === item.__key);
    if (idx >= 0) arr[idx] = item; else arr.unshift(item);
    listRef.value = arr;
}

function removeByKey(listRef, __key) {
    listRef.value = listRef.value.filter(x => x.__key !== __key);
}

function ingest(evt) {
    if (!evt || !evt.name) return;
    const p = evt.payload || {};

    // 批合并
    if (evt.name === 'queue.batch' && Array.isArray(p.events)) {
        p.events.forEach(e => ingest(e));
        return;
    }

    if (evt.name === 'queue.enqueued') {
        const it = normalizeItem(p);
        it.status = it.delay_until ? 'DELAYED' : 'READY';
        if (p.delay_until) upsert(delayed, it);
        else upsert(ready, it);

    } else if (evt.name === 'queue.promoted') {
        const k = keyOf(p);
        removeByKey(delayed, k);
        const it = normalizeItem(p);
        it.status = 'READY';
        upsert(ready, it);

    } else if (evt.name === 'queue.dequeued') {
        const k = keyOf(p);
        // 可选：瞬时展示一下 DEQUEUED 再移除（UI 复杂度会高一点）
        removeByKey(ready, k);

    } else if (evt.name === 'queue.requeued') {
        const it = normalizeItem(p);
        it.status = 'READY';
        upsert(ready, it);

    } else if (evt.name === 'queue.dropped') {
        const k = keyOf(p);
        removeByKey(ready, k);
        removeByKey(delayed, k);

    } else if (evt.name === 'task.started') {
        // 任务真正开始执行时，从 Ready 移除即可；如需，也可以标记 RUNNING 然后在 UI 的“运行中”区显示
        const k = keyOf(p);
        removeByKey(ready, k);
    }
}


export function useQueueStore() {
    return {overview, ready, delayed, fetchOverview, fetchList, ingest};
}
