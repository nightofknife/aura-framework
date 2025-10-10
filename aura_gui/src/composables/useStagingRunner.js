// src/composables/useStagingRunner.js
import {ref, watch, nextTick, effectScope} from 'vue';
import axios from 'axios';
import {useStagingQueue} from './useStagingQueue.js';
import {useAuraSocket} from './useAuraSocket.js';
import {useToasts} from './useToasts.js';

const api = axios.create({baseURL: 'http://127.0.0.1:8000/api', timeout: 5000});

// —— 单例状态 —— //
const running = ref(false);
const autoMode = ref(false);
const batchId = ref(null);
const snapshotIds = ref([]);
const pointer = ref(0);
const currentId = ref(null);

const AUTO_LS = 'aura_runner_auto';
try {
    autoMode.value = JSON.parse(localStorage.getItem(AUTO_LS) || 'false');
} catch {
}

let booted = false;
let scope = null;

function toMs(v) {
    if (v == null) return 0;
    return v > 1e12 ? v : Math.floor(v * 1000);
}

export function useStagingRunner() {
    const {items, updateTask, removeTask, pushHistory} = useStagingQueue();
    const {lastMessage, connect} = useAuraSocket();
    const {push: toast} = useToasts();

    function markSnapshot() {
        batchId.value = 'b_' + Date.now();
        snapshotIds.value = items.value.map(x => x.id);
        pointer.value = 0;
        for (const id of snapshotIds.value) {
            updateTask(id, {toDispatch: true, status: 'pending'});
        }
    }

    async function startBatch() {
        if (running.value) return;
        markSnapshot();
        running.value = true;
        processNext();
    }

    function pause() {
        running.value = false;
    }

    function setAuto(v) {
        autoMode.value = !!v;
        try {
            localStorage.setItem(AUTO_LS, JSON.stringify(autoMode.value));
        } catch {
        }
        if (autoMode.value && !running.value) processAutoIfIdle();
    }

    function forceStop() {
        pause();
        toast({type: 'info', title: 'Force stop', message: 'Paused queue dispatch.'});
    }

    function processAutoIfIdle() {
        if (running.value) return;
        const next = items.value.find(x => !x.toDispatch && (x.status === 'pending' || !x.status));
        if (!next) return;
        batchId.value = null;
        snapshotIds.value = [next.id];
        pointer.value = 0;
        running.value = true;
        processNext();
    }

    async function processNext() {
        if (!running.value) return;

        let nextId = null;
        if (batchId.value) {
            // 批量：在 snapshotIds 中找需要投递或仍在进行中的项
            for (; pointer.value < snapshotIds.value.length; pointer.value++) {
                const id = snapshotIds.value[pointer.value];
                const it = items.value.find(x => x.id === id);
                if (!it) continue;
                const s = (it.status || 'pending').toLowerCase();
                if (it.toDispatch && !['running', 'dispatching', 'dispatched', 'success', 'error'].includes(s)) {
                    nextId = id;
                    break;
                }
                if (it.toDispatch && (s === 'dispatching' || s === 'dispatched' || s === 'running')) {
                    nextId = id;
                    break;
                }
            }
        } else {
            // 自动：挑第一条 pending 且未标记 toDispatch 的
            const it = items.value.find(x => !x.toDispatch && (x.status === 'pending' || !x.status));
            if (it) nextId = it.id;
        }

        if (!nextId) {
            running.value = false;
            if (!autoMode.value) {
                batchId.value = null;
                snapshotIds.value = [];
            }
            return;
        }

        currentId.value = nextId;
        const item = items.value.find(x => x.id === nextId);
        if (!item) return stepDone();

        const cur = (item.status || '').toLowerCase();
        if (['dispatching', 'dispatched', 'running'].includes(cur)) {
            await waitForFinish(item);
            return stepDone();
        }

        updateTask(item.id, {status: 'dispatching'});
        try {
            await api.post('/tasks/run', {
                plan_name: item.plan_name,
                task_name: item.task_name,
                inputs: item.inputs || {}
            });
            updateTask(item.id, {status: 'dispatched', dispatchedAt: Date.now()});
            await waitForFinish(item);
        } catch (e) {
            updateTask(item.id, {status: 'error'});
            toast({type: 'error', title: 'Failed to enqueue', message: `${item.plan_name} / ${item.task_name}`});
        }
        stepDone();

        function stepDone() {
            if (batchId.value) pointer.value++;
            nextTick(() => processNext());
        }
    }

    function waitForFinish(item) {
        return new Promise(resolve => {
            item._awaiting = resolve;
            item._awaitingTimer = setTimeout(() => resolve(), 30 * 60 * 1000); // 兜底 30min
        });
    }

    // —— 只注册一次 —— //
    function bootOnce() {
        if (booted) return;
        booted = true;
        connect?.();

        scope = effectScope();
        scope.run(() => {
            watch(lastMessage, evt => {
                if (!evt) return;
                const name = (evt.name || '').toLowerCase();
                const p = evt.payload || {};

                if (name === 'task.started') {
                    const candidates = items.value.filter(x =>
                        (x.status === 'dispatched' || x.status === 'dispatching') &&
                        x.plan_name === p.plan_name && x.task_name === p.task_name
                    );
                    if (candidates.length) {
                        let best = null, bestDiff = 1e15;
                        const startMs = toMs(p.start_time);
                        for (const it of candidates) {
                            const d = Math.abs((it.dispatchedAt || 0) - startMs);
                            if (d < bestDiff) {
                                best = it;
                                bestDiff = d;
                            }
                        }
                        if (best) updateTask(best.id, {status: 'running', run_id: p.run_id || null});
                    }

                } else if (name === 'task.finished') {
                    let target = null;
                    if (p.run_id) target = items.value.find(x => x.run_id === p.run_id);
                    if (!target) {
                        const c = items.value.filter(x =>
                            (x.status === 'running' || x.status === 'dispatched' || x.status === 'dispatching') &&
                            x.plan_name === p.plan_name && x.task_name === p.task_name
                        );
                        if (c.length) target = c[0];
                    }
                    if (!target) return;

                    const ok = String(p.final_status || '').toUpperCase() === 'SUCCESS';
                    const finishedAt = toMs(p.end_time) || Date.now();

                    // ✅ 先 resolve，再改状态/移除 —— 保证 Promise 一定被释放
                    const resolver = target._awaiting;
                    const timer = target._awaitingTimer;
                    if (timer) clearTimeout(timer);
                    if (resolver) {
                        target._awaiting = null;
                        resolver();
                    }

                    if (ok) {
                        pushHistory({
                            ...target,
                            status: 'success',
                            run_id: p.run_id || target.run_id || null,
                            finishedAt
                        });
                        removeTask(target.id); // 成功：从 Staging 移除
                    } else {
                        updateTask(target.id, {status: 'error'}); // 失败：留在 Staging 方便重试
                    }
                }
            });

            // Auto：有新 pending 且空闲时自动启动
            watch([autoMode, items], () => {
                if (autoMode.value && !running.value) {
                    const hasPending = items.value.some(x => !x.toDispatch && (x.status === 'pending' || !x.status));
                    if (hasPending) processAutoIfIdle();
                }
            }, {deep: true});
        });
    }

    bootOnce();

    return {running, autoMode, currentId, startBatch, pause, setAuto, forceStop, batchId};
}
