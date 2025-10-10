// src/composables/useQueueStore.js
import {ref} from 'vue';
import axios from 'axios';

// 统一 key：优先 run_id，退化到 plan/task + enqueued_at
function keyOf(p) {
    if (p.run_id) return p.run_id;
    const t = p.enqueued_at ?? p.delay_until ?? Date.now() / 1000;
    return `${p.plan_name || ''}/${p.task_name || ''}:${t}`;
}

function normalizeItem(p) {
    const it = {...p};
    it.__key = keyOf(p);
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

    // batch 合并
    if (evt.name === 'queue.batch' && Array.isArray(p.events)) {
        p.events.forEach(e => ingest(e));
        return;
    }

    if (evt.name === 'queue.enqueued') {
        const it = normalizeItem(p);
        if (p.delay_until) upsert(delayed, it);
        else upsert(ready, it);
    } else if (evt.name === 'queue.promoted') {
        const k = keyOf(p);
        removeByKey(delayed, k);
        upsert(ready, normalizeItem(p));
    } else if (evt.name === 'queue.dequeued') {
        const k = keyOf(p);
        removeByKey(ready, k);
    } else if (evt.name === 'queue.requeued') {
        upsert(ready, normalizeItem(p));
    } else if (evt.name === 'queue.dropped') {
        const k = keyOf(p);
        removeByKey(ready, k);
        removeByKey(delayed, k);
    }
    // 任务开始也可以认为 ready -> dequeue
    else if (evt.name === 'task.started') {
        const k = keyOf(p);
        removeByKey(ready, k);
    }
}

export function useQueueStore() {
    return {overview, ready, delayed, fetchOverview, fetchList, ingest};
}
