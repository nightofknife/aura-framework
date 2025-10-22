// === src/composables/useStagingQueue.js ===
import {ref} from 'vue';

/**
 * GUI 独立状态集（与引擎内部状态解耦）
 */
export const GUI_STATUS = {
    IDLE: 'IDLE',
    SELECTED: 'SELECTED',
    WAITING_ENGINE: 'WAITING_ENGINE',
    DISPATCHING: 'DISPATCHING',
    ENQUEUE_FAILED: 'ENQUEUE_FAILED',

    QUEUED: 'QUEUED',        // ✅ 已在后端队列中等待
    DEQUEUED: 'DEQUEUED',

    RUNNING: 'RUNNING',      // ✅ 后端执行中

    SUCCESS: 'SUCCESS',
    ERROR: 'ERROR',
};

// ✅ 新增：状态对应的中文标签
export const STATUS_LABELS = {
    [GUI_STATUS.IDLE]: '待派发',
    [GUI_STATUS.SELECTED]: '已选中',
    [GUI_STATUS.WAITING_ENGINE]: '等待引擎',
    [GUI_STATUS.DISPATCHING]: '派发中...',
    [GUI_STATUS.ENQUEUE_FAILED]: '入队失败',
    [GUI_STATUS.QUEUED]: '队列中',
    [GUI_STATUS.DEQUEUED]: '已出队',
    [GUI_STATUS.RUNNING]: '执行中',
    [GUI_STATUS.SUCCESS]: '已完成',
    [GUI_STATUS.ERROR]: '失败',
};

// ✅ 新增：状态对应的颜色
export const STATUS_COLORS = {
    [GUI_STATUS.IDLE]: '#6c757d',
    [GUI_STATUS.SELECTED]: '#007bff',
    [GUI_STATUS.WAITING_ENGINE]: '#ffc107',
    [GUI_STATUS.DISPATCHING]: '#fd7e14',
    [GUI_STATUS.ENQUEUE_FAILED]: '#dc3545',
    [GUI_STATUS.QUEUED]: '#17a2b8',
    [GUI_STATUS.DEQUEUED]: '#20c997',
    [GUI_STATUS.RUNNING]: '#28a745',
    [GUI_STATUS.SUCCESS]: '#218838',
    [GUI_STATUS.ERROR]: '#c82333',
};

export const GUI_PHASE = {
    PRE: 'pre',
    QUEUED: 'queued',
    ENGINE: 'engine',
    POST: 'post',
};

const LS_KEY = 'aura_staging_queue_v1';
const LS_KEY_HISTORY = 'aura_staging_history_v1';

function readLS() {
    try {
        const raw = localStorage.getItem(LS_KEY);
        const arr = raw ? JSON.parse(raw) : [];
        return (Array.isArray(arr) ? arr : []).map(it => ({
            id: it.id || uid(),
            plan_name: it.plan_name ?? '',
            task_name: it.task_name ?? '',
            inputs: (it.inputs && typeof it.inputs === 'object') ? it.inputs : {},

            priority: it.priority ?? null,
            note: it.note ?? '',
            repeat: Math.max(1, Math.min(500, it.repeat || 1)),

            status: it.status || 'pending',

            toDispatch: !!it.toDispatch,
            toDispatchEpoch: it.toDispatchEpoch ?? null,

            run_id: it.run_id ?? null,
            cid: it.cid ?? null, // ✅ 添加 cid

            gui_status: it.gui_status || GUI_STATUS.IDLE,
            phase: it.phase || GUI_PHASE.PRE,
            handoff: !!it.handoff,

            selectedAt: it.selectedAt ?? null,
            dispatchedAt: it.dispatchedAt ?? null,
            enqueuedAt: it.enqueuedAt ?? null,
            dequeuedAt: it.dequeuedAt ?? null,
            startedAt: it.startedAt ?? null,
            finishedAt: it.finishedAt ?? null,
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

function addTask({plan_name, task_name, inputs = {}, priority = null, note = '', repeat = 1} = {}) {
    const it = {
        id: uid(),
        temp_id: null,
        cid: null,
        plan_name,
        task_name,
        inputs,
        priority,
        note,
        repeat: Math.max(1, Math.min(500, repeat || 1)),

        status: 'pending',

        toDispatch: false,
        toDispatchEpoch: null,

        run_id: null,

        gui_status: GUI_STATUS.IDLE,
        phase: GUI_PHASE.PRE,
        handoff: false,

        selectedAt: null,
        dispatchedAt: null,
        enqueuedAt: null,
        dequeuedAt: null,
        startedAt: null,
        finishedAt: null,
    };
    items.value = [...items.value, it];
    persist();
    return it.id;
}

function updateTask(id, patch) {
    const idx = items.value.findIndex(x => x.id === id);
    if (idx >= 0) {
        Object.assign(items.value[idx], patch);
        items.value = [...items.value];
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
    const it = items.value[i];
    const copy = {
        ...it,
        id: uid(),
        repeat: it.repeat || 1,
        status: 'pending',
        toDispatch: false,
        toDispatchEpoch: null,
        run_id: null,
        cid: null,

        gui_status: GUI_STATUS.IDLE,
        phase: GUI_PHASE.PRE,
        handoff: false,

        selectedAt: null,
        dispatchedAt: null,
        enqueuedAt: null,
        dequeuedAt: null,
        startedAt: null,
        finishedAt: null,
    };
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

function batchUpdate(mutator) {
    const arr = items.value;
    let changed = false;

    const set = (obj, key, val) => {
        if (obj[key] !== val) {
            obj[key] = val;
            return true;
        }
        return false;
    };

    for (const it of arr) {
        try {
            changed = mutator(it, set) || changed;
        } catch {
        }
    }

    if (changed) {
        items.value = [...arr];
        persist();
    }
}

function setGuiStatus(id, gui_status, extraPatch = {}) {
    const now = Date.now();

    const phase =
        (gui_status === GUI_STATUS.QUEUED || gui_status === GUI_STATUS.DEQUEUED) ? GUI_PHASE.QUEUED :
            (gui_status === GUI_STATUS.RUNNING) ? GUI_PHASE.ENGINE :
                (gui_status === GUI_STATUS.SUCCESS || gui_status === GUI_STATUS.ERROR) ? GUI_PHASE.POST :
                    GUI_PHASE.PRE;

    const handoff =
        gui_status === GUI_STATUS.QUEUED ||
        gui_status === GUI_STATUS.DEQUEUED ||
        gui_status === GUI_STATUS.RUNNING ||
        gui_status === GUI_STATUS.SUCCESS ||
        gui_status === GUI_STATUS.ERROR;

    batchUpdate((it, set) => {
        if (it.id !== id) return false;
        let c = false;

        c = set(it, 'gui_status', gui_status) || c;
        c = set(it, 'phase', phase) || c;
        c = set(it, 'handoff', handoff) || c;

        if (gui_status === GUI_STATUS.SELECTED && !it.selectedAt) {
            it.selectedAt = now;
            c = true;
        }
        if (gui_status === GUI_STATUS.DISPATCHING && !it.dispatchedAt) {
            it.dispatchedAt = now;
            c = true;
        }
        if (gui_status === GUI_STATUS.QUEUED && !it.enqueuedAt) {
            it.enqueuedAt = now;
            c = true;
        }
        if (gui_status === GUI_STATUS.DEQUEUED && !it.dequeuedAt) {
            it.dequeuedAt = now;
            c = true;
        }
        if (gui_status === GUI_STATUS.RUNNING && !it.startedAt) {
            it.startedAt = now;
            c = true;
        }
        if ((gui_status === GUI_STATUS.SUCCESS || gui_status === GUI_STATUS.ERROR) && !it.finishedAt) {
            it.finishedAt = now;
            c = true;
        }

        for (const k in (extraPatch || {})) {
            c = set(it, k, extraPatch[k]) || c;
        }
        return c;
    });
}

function pushHistory(entry, max = 300) {
    const rec = {
        id: entry.id || uid(),
        plan_name: entry.plan_name || '',
        task_name: entry.task_name || '',
        inputs: entry.inputs || {},
        priority: entry.priority ?? null,
        note: entry.note || '',
        repeat: entry.repeat || 1,
        status: entry.status || 'success',
        run_id: entry.run_id || null,
        cid: entry.cid || null,
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
        items,
        addTask, updateTask, removeTask, clear, duplicate, move, persist,
        history, pushHistory, clearHistory,
        batchUpdate, setGuiStatus,
    };
}
