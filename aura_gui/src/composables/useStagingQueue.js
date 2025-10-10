// src/composables/useStagingQueue.js
import {ref} from 'vue';

const LS_KEY = 'aura_staging_queue_v1';
const LS_KEY_HISTORY = 'aura_staging_history_v1';

function readLS() {
    try {
        const raw = localStorage.getItem(LS_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        const arr = Array.isArray(parsed) ? parsed : [];
        return arr.filter(it => it && typeof it === 'object').map(it => ({
            id: it.id || ('q_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36)),
            plan_name: it.plan_name ?? '',
            task_name: it.task_name ?? '',
            inputs: (it.inputs && typeof it.inputs === 'object') ? it.inputs : {},
            priority: it.priority ?? null,
            note: it.note ?? '',
            status: it.status || 'pending',
            toDispatch: !!it.toDispatch,
            dispatchedAt: it.dispatchedAt ?? null,
            run_id: it.run_id ?? null,
        }));
    } catch {
        return [];
    }
}

function writeLS(arr) {
    try {
        localStorage.setItem(LS_KEY, JSON.stringify(arr));
    } catch {
    }
}

function readHistory() {
    try {
        const raw = localStorage.getItem(LS_KEY_HISTORY);
        const arr = raw ? JSON.parse(raw) : [];
        return Array.isArray(arr) ? arr : [];
    } catch {
        return [];
    }
}

function writeHistory(arr) {
    try {
        localStorage.setItem(LS_KEY_HISTORY, JSON.stringify(arr));
    } catch {
    }
}

const items = ref(readLS());
const history = ref(readHistory());

function persist() {
    writeLS(items.value);
}

function persistHistory() {
    writeHistory(history.value);
}

function uid() {
    return 'q_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

function addTask({plan_name, task_name, inputs = {}, priority = null, note = ''} = {}) {
    const it = {
        id: uid(),
        plan_name,
        task_name,
        inputs,
        priority,
        note,
        status: 'pending',
        toDispatch: false,
        dispatchedAt: null,
        run_id: null
    };
    items.value = [...items.value, it];
    persist();
    return it.id;
}

// ✅ 关键修复：原地合并，保持对象实例不变（保留 _awaiting/_awaitingTimer）
function updateTask(id, patch) {
    const idx = items.value.findIndex(x => x.id === id);
    if (idx >= 0) {
        Object.assign(items.value[idx], patch);
        items.value = [...items.value]; // 触发响应式
        persist();
    }
}

function removeTask(id) {
    items.value = items.value.filter(x => x.id !== id);
    persist();
}

function clear() {
    items.value = [];
    persist();
}

function duplicate(id) {
    const i = items.value.findIndex(x => x.id === id);
    if (i < 0) return;
    const copy = {...items.value[i], id: uid(), status: 'pending', toDispatch: false, dispatchedAt: null, run_id: null};
    const arr = items.value.slice();
    arr.splice(i + 1, 0, copy);
    items.value = arr;
    persist();
    return copy.id;
}

function move(id, dir = -1) {
    const i = items.value.findIndex(x => x.id === id);
    if (i < 0) return;
    const j = Math.min(items.value.length - 1, Math.max(0, i + dir));
    if (i === j) return;
    const arr = items.value.slice();
    const [it] = arr.splice(i, 1);
    arr.splice(j, 0, it);
    items.value = arr;
    persist();
}

// —— History —— //
function pushHistory(entry, max = 300) {
    const rec = {
        id: entry.id || uid(),
        plan_name: entry.plan_name || '',
        task_name: entry.task_name || '',
        inputs: entry.inputs || {},
        priority: entry.priority ?? null,
        note: entry.note || '',
        status: entry.status || 'success',
        run_id: entry.run_id || null,
        finishedAt: entry.finishedAt || Date.now(),
    };
    history.value = [rec, ...history.value].slice(0, max);
    persistHistory();
}

function clearHistory() {
    history.value = [];
    persistHistory();
}

export function useStagingQueue() {
    return {
        items, addTask, updateTask, removeTask, clear, duplicate, move, persist,
        history, pushHistory, clearHistory
    };
}
