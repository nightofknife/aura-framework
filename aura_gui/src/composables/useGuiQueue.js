// === src/composables/useGuiQueue.js ===
import { ref } from 'vue';

const LS_KEY = 'aura_gui_queue_v1';

function uid() {
    return `gq_${Math.random().toString(36).slice(2, 10)}_${Date.now()}`;
}

function load() {
    try {
        const raw = localStorage.getItem(LS_KEY);
        const arr = raw ? JSON.parse(raw) : [];
        return Array.isArray(arr) ? arr : [];
    } catch {
        return [];
    }
}

const items = ref(load());

function persist() {
    try {
        localStorage.setItem(LS_KEY, JSON.stringify(items.value));
    } catch {
        /* ignore */
    }
}

function add(task) {
    items.value.push({
        id: uid(),
        status: 'pending', // pending | pushing | queued
        pushedAt: null,
        lastCid: null,
        ...task,
    });
    persist();
}

function update(id, patch) {
    const idx = items.value.findIndex(i => i.id === id);
    if (idx >= 0) {
        items.value[idx] = { ...items.value[idx], ...patch };
        persist();
    }
}

function remove(id) {
    items.value = items.value.filter(i => i.id !== id);
    persist();
}

function clear() {
    items.value = [];
    persist();
}

function move(id, direction) {
    const idx = items.value.findIndex(i => i.id === id);
    if (idx < 0) return;
    const swapWith = direction === 'up' ? idx - 1 : idx + 1;
    if (swapWith < 0 || swapWith >= items.value.length) return;
    const arr = [...items.value];
    [arr[idx], arr[swapWith]] = [arr[swapWith], arr[idx]];
    items.value = arr;
    persist();
}

export function useGuiQueue() {
    return {
        items,
        add,
        update,
        remove,
        clear,
        move,
    };
}
