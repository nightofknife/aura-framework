// === src/composables/useStagingRunner.js ===
import { ref, watch, nextTick, effectScope, computed } from 'vue';
import axios from 'axios';
import { useStagingQueue, GUI_STATUS } from './useStagingQueue.js';
import { useToasts } from './useToasts.js';
import { useRuns } from './useRuns.js';
import { useQueueStore } from './useQueueStore.js';

// --- 配置 ---
const API_BASE = 'http://127.0.0.1:18098/api';
const api = axios.create({ baseURL: API_BASE, timeout: 10000 });

// --- 内部状态 ---
const running = ref(false);
const autoMode = ref(false);
const isDispatching = ref(false);

const AUTO_LS = 'aura_runner_auto';
try { autoMode.value = JSON.parse(localStorage.getItem(AUTO_LS) || 'false'); } catch {}

let booted = false;
let scope = null;
let pollingTimer = null;

const POLL_INTERVAL = 1000;
const DISPATCH_DELAY = 50;

function generateTempId() {
    return `temp_${Math.random().toString(36).slice(2, 11)}_${Date.now()}`;
}

export function useStagingRunner() {
    const { items, updateTask, removeTask, pushHistory, batchUpdate, setGuiStatus } = useStagingQueue();
    const { push: toast } = useToasts();
    const { setRuns } = useRuns();
    const { fetchOverview } = useQueueStore();

    // --- 轮询活跃任务 ---
    async function pollActiveRuns() {
        try {
            const { data } = await api.get('/runs/active');
            setRuns(data || []);
        } catch (err) {
            console.error('[Polling] Failed to fetch active runs:', err);
        }
    }

    // --- 核心工作流：派发器 ---
    async function dispatcher() {
        console.log('[Dispatcher] Called', { running: running.value, isDispatching: isDispatching.value });

        if (!running.value) {
            console.log('[Dispatcher] Not running, exit');
            return;
        }

        if (isDispatching.value) {
            console.log('[Dispatcher] Already dispatching, exit');
            return;
        }

        const nextItem = items.value.find(it => it.toDispatch && it.status === 'pending');
        console.log('[Dispatcher] Next item:', nextItem ? `${nextItem.plan_name}/${nextItem.task_name}` : 'none');

        if (!nextItem) {
            console.log('[Dispatcher] Queue empty, stopping');
            running.value = false;
            return;
        }

        isDispatching.value = true;
        console.log('[Dispatcher] Start dispatching:', nextItem.task_name);

        const temp_id = generateTempId();
        updateTask(nextItem.id, { status: 'dispatching', temp_id });
        setGuiStatus(nextItem.id, GUI_STATUS.DISPATCHING);

        const repeatCount = Math.max(1, Math.min(500, nextItem.repeat || 1));
        console.log('[Dispatcher] Repeat count:', repeatCount);

        try {
            const results = [];

            for (let i = 0; i < repeatCount; i++) {
                console.log(`[Dispatcher] Dispatching ${i + 1}/${repeatCount}`);
                const { data } = await api.post('/tasks/run', {
                    plan_name: nextItem.plan_name,
                    task_name: nextItem.task_name,
                    inputs: nextItem.inputs || {},
                });

                if (data.status === 'success') {
                    results.push(data.cid);
                    console.log(`[Dispatcher] Success ${i + 1}/${repeatCount}, cid:`, data.cid);
                } else {
                    throw new Error(data.message || 'Dispatch failed');
                }

                if (repeatCount > 1 && i < repeatCount - 1) {
                    await new Promise(resolve => setTimeout(resolve, DISPATCH_DELAY));
                }
            }

            updateTask(nextItem.id, {
                status: 'dispatched',
                cid: results[0],
                dispatchedAt: Date.now(),
            });
            setGuiStatus(nextItem.id, GUI_STATUS.QUEUED, { handoff: true });
            toast({
                type: 'success',
                title: 'Task Dispatched',
                message: `${nextItem.task_name} ×${repeatCount}`
            });
            console.log('[Dispatcher] Task completed successfully');
        } catch (err) {
            console.error('[Dispatcher] Error:', err);
            updateTask(nextItem.id, { status: 'pending' });
            setGuiStatus(nextItem.id, GUI_STATUS.ENQUEUE_FAILED, { error: err.message });
            toast({
                type: 'error',
                title: 'Dispatch Failed',
                message: err.message
            });
        } finally {
            console.log('[Dispatcher] Finally block, releasing lock');
            isDispatching.value = false;

            // ✅ 立即检查是否有更多任务
            const hasMore = items.value.some(it => it.toDispatch && it.status === 'pending');
            console.log('[Dispatcher] Has more tasks?', hasMore);

            if (running.value && hasMore) {
                console.log('[Dispatcher] Scheduling next dispatch');
                // ✅ 使用 setTimeout(0) 确保当前调用栈完成
                setTimeout(() => {
                    console.log('[Dispatcher] Calling dispatcher again');
                    dispatcher();
                }, 0);
            } else {
                console.log('[Dispatcher] No more tasks or not running');
                running.value = false;
            }
        }
    }

    // --- 状态同步 ---
    function syncUiWithBackendState() {
        const { runsById } = useRuns();

        for (const localItem of items.value) {
            if (!localItem.cid) continue;

            const backendRun = runsById.value[localItem.cid];

            if (backendRun) {
                if (localItem.status !== 'running') {
                    updateTask(localItem.id, { status: 'running' });
                    setGuiStatus(localItem.id, GUI_STATUS.RUNNING, { handoff: true });
                }
            } else if (['dispatched', 'running'].includes(localItem.status)) {
                setGuiStatus(localItem.id, GUI_STATUS.SUCCESS, { finishedAt: Date.now() });
                pushHistory({ ...localItem, status: 'success', finishedAt: Date.now() });
                removeTask(localItem.id);
            }
        }
    }

    // --- 启动轮询 ---
    function startPolling() {
        if (pollingTimer) return;
        pollingTimer = setInterval(async () => {
            await pollActiveRuns();
            await fetchOverview();
            syncUiWithBackendState();
        }, POLL_INTERVAL);
    }

    function stopPolling() {
        if (pollingTimer) {
            clearInterval(pollingTimer);
            pollingTimer = null;
        }
    }

    // --- 对外暴露的控制函数 ---
    function startBatch() {
        console.log('[startBatch] Called');
        batchUpdate(it => {
            if (it.status === 'pending') {
                it.toDispatch = true;
                if (it.gui_status === GUI_STATUS.IDLE) it.gui_status = GUI_STATUS.SELECTED;
            }
        });
        running.value = true;

        if (!isDispatching.value) {
            console.log('[startBatch] Starting dispatcher');
            dispatcher();
        }
    }

    function pause() {
        console.log('[pause] Called');
        running.value = false;
        batchUpdate(it => {
            if (it.toDispatch && it.status === 'pending') it.toDispatch = false;
        });
    }

    function setAuto(v) {
        autoMode.value = !!v;
        localStorage.setItem(AUTO_LS, JSON.stringify(autoMode.value));
        if (autoMode.value) {
            running.value = true;
            if (!isDispatching.value) {
                dispatcher();
            }
        } else {
            running.value = false;
        }
    }

    function forceStop() {
        pause();
        toast({ type: 'info', title: 'Paused', message: 'Queue dispatch paused.' });
    }

    // --- 启动与监听 ---
    function bootOnce() {
        if (booted) return;
        booted = true;

        scope = effectScope();
        scope.run(() => {
            startPolling();

            watch(items, () => {
                if (autoMode.value) {
                    batchUpdate(it => {
                        if (it.status === 'pending' && !it.toDispatch) it.toDispatch = true;
                    });
                    if (!running.value) {
                        running.value = true;
                        if (!isDispatching.value) {
                            dispatcher();
                        }
                    }
                }
            }, { deep: true });
        });

        if (import.meta.hot) {
            import.meta.hot.dispose(() => {
                stopPolling();
                scope?.stop();
            });
        }
    }

    bootOnce();

    return {
        running,
        autoMode,
        startBatch,
        pause,
        setAuto,
        forceStop,
    };
}
