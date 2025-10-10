// src/composables/useRuns.js
import {ref} from 'vue';

const runsById = ref({});   // id -> run
const activeRuns = ref([]); // running
const recentRuns = ref([]); // finished/queued

function makeIdFromStarted(p) {
    // 兼容旧事件：用 start_time 作为唯一性区分
    if (p.run_id) return p.run_id;
    return `${p.plan_name}/${p.task_name}:${p.start_time}`;
}

function makeIdFromFinished(p) {
    if (p.run_id) return p.run_id;
    const start = (p.end_time && p.duration) ? (p.end_time - p.duration) : 'unknown';
    return `${p.plan_name}/${p.task_name}:${start}`;
}

function ensureRun(id, p) {
    if (!runsById.value[id]) {
        runsById.value[id] = {
            id,
            plan: p.plan_name,
            task: p.task_name,
            status: 'queued',
            startedAt: null,
            finishedAt: null,
            logs: [],
            timeline: {nodes: []}, // 节点时间线
        };
    }
    const r = runsById.value[id];
    if (p.plan_name) r.plan = p.plan_name;
    if (p.task_name) r.task = p.task_name;
    return r;
}

function upsertNode(r, node) {
    const arr = r.timeline.nodes;
    const idx = arr.findIndex(n => (n.node_id || n.id) === (node.node_id || node.id));
    if (idx >= 0) arr[idx] = {...arr[idx], ...node};
    else arr.push({...node});
}

function resort() {
    const all = Object.values(runsById.value);
    activeRuns.value = all
        .filter(r => r.status === 'running')
        .sort((a, b) => (b.startedAt || 0) - (a.startedAt || 0));
    recentRuns.value = all
        .filter(r => r.status !== 'running')
        .sort((a, b) => (b.finishedAt || b.startedAt || 0) - (a.finishedAt || a.startedAt || 0))
        .slice(0, 200);
}

function toMs(v) {
    if (v == null) return null;
    return v > 1e12 ? v : Math.floor(v * 1000);
}

// 入口：摄取“事件对象”本身（已经是 {id, name, timestamp, payload} 这一层）
function ingest(evt) {
    if (!evt || !evt.name) return;
    const name = evt.name;
    const p = evt.payload || {};

    if (name === 'task.started') {
        const id = makeIdFromStarted(p);
        const r = ensureRun(id, p);
        r.status = 'running';
        r.startedAt = toMs(p.start_time);

    } else if (name === 'task.finished') {
        const id = makeIdFromFinished(p);
        const r = ensureRun(id, p);
        const ok = (p.final_status || '').toUpperCase() === 'SUCCESS';
        r.status = ok ? 'success' : 'error';
        r.finishedAt = toMs(p.end_time);
        if (!ok) {
            r.logs.push({
                ts: r.finishedAt || Date.now(),
                level: 'error',
                message: (p.final_result && p.final_result.error) ? String(p.final_result.error) : (p.error_message || 'Task failed'),
            });
        }

    } else if (name === 'node.started') {
        const id = p.run_id ? p.run_id : `${p.plan_name}/${p.task_name}:${p.start_time || '?'}`;
        const r = ensureRun(id, p);
        upsertNode(r, {
            node_id: p.node_id || p.step_name || 'node',
            startMs: toMs(p.start_time ?? p.ts),
            status: 'running'
        });

    } else if (name === 'node.heartbeat') {
        const id = p.run_id ? p.run_id : `${p.plan_name}/${p.task_name}:${p.start_time || '?'}`;
        const r = ensureRun(id, p);
        upsertNode(r, {node_id: p.node_id || 'node', progress: p.progress ?? null});

    } else if (name === 'node.finished') {
        const id = p.run_id ? p.run_id : `${p.plan_name}/${p.task_name}:${p.start_time || '?'}`;
        const r = ensureRun(id, p);
        const status = (p.status || 'success').toLowerCase();
        upsertNode(r, {node_id: p.node_id || 'node', endMs: toMs(p.end_time ?? p.ts), status});

    } else {
        // ignore
    }

    resort();
}

export function useRuns() {
    return {activeRuns, recentRuns, runsById, ingest};
}
