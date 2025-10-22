// === src/composables/useStagingRunner.js ===
import { ref, watch, effectScope } from 'vue';
import axios from 'axios';
import { useStagingQueue, GUI_STATUS } from './useStagingQueue.js';
import { useToasts } from './useToasts.js';
import { useRuns } from './useRuns.js';
import { useQueueStore } from './useQueueStore.js';

const API_BASE = 'http://127.0.0.1:18098/api';
const api = axios.create({ baseURL: API_BASE, timeout: 10000 });

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

    async function pollActiveRuns() {
        try {
            const { data } = await api.get('/runs/active');
            setRuns(data || []);
        } catch (err) {
            console.error('[Polling] Failed to fetch active runs:', err);
        }
    }

    async function dispatcher() {
        if (!running.value || isDispatching.value) return;

        const nextItem = items.value.find(it => it.toDispatch && it.status === 'pending');
        if (!nextItem) {
            running.value = false;
            return;
        }

        isDispatching.value = true;

        const temp_id = generateTempId();
        updateTask(nextItem.id, { status: 'dispatching', temp_id });
        setGuiStatus(nextItem.id, GUI_STATUS.DISPATCHING);

        const repeatCount = Math.max(1, Math.min(500, nextItem.repeat || 1));

        try {
            const results = [];

            for (let i = 0; i < repeatCount; i++) {
                const { data } = await api.post('/tasks/run', {
                    plan_name: nextItem.plan_name,
                    task_name: nextItem.task_name,
                    inputs: nextItem.inputs || {},
                });

                if (data.status === 'success') {
                    results.push(data.cid);
                } else {
                    throw new Error(data.message || 'Dispatch failed');
                }

                if (repeatCount > 1 && i < repeatCount - 1) {
                    await new Promise(resolve => setTimeout(resolve, DISPATCH_DELAY));
                }
            }

            // ✅ 派发成功 → 标记为 queued（不移除）
            updateTask(nextItem.id, {
                status: 'queued',
                cid: results[0],
                dispatchedAt: Date.now(),
            });
            setGuiStatus(nextItem.id, GUI_STATUS.QUEUED);

            toast({
                type: 'success',
                title: 'Task Dispatched',
                message: `${nextItem.task_name} ×${repeatCount}`
            });
        } catch (err) {
            updateTask(nextItem.id, { status: 'pending' });
            setGuiStatus(nextItem.id, GUI_STATUS.ENQUEUE_FAILED, { error: err.message });
            toast({
                type: 'error',
                title: 'Dispatch Failed',
                message: err.message
            });
        } finally {
            isDispatching.value = false;

            setTimeout(() => {
                if (running.value) {
                    dispatcher();
                }
            }, 0);
        }
    }

    function syncUiWithBackendState() {
        const { runsById } = useRuns();

        for (const localItem of items.value) {
            if (!localItem.cid) continue;

            const backendRun = runsById.value[localItem.cid];

            if (backendRun) {
                // ✅ 后端正在运行
                if (localItem.status !== 'running') {
                    updateTask(localItem.id, { status: 'running' });
                    setGuiStatus(localItem.id, GUI_STATUS.RUNNING);
                }
            } else if (['queued', 'running'].includes(localItem.status)) {
                // ✅ 后端找不到 → 任务完成
                setGuiStatus(localItem.id, GUI_STATUS.SUCCESS, { finishedAt: Date.now() });
                pushHistory({ ...localItem, status: 'success', finishedAt: Date.now() });

                // ✅ 延迟 2 秒后才移除（让用户看到完成状态）
                setTimeout(() => {
                    removeTask(localItem.id);
                }, 2000);
            }
        }
    }

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

    function startBatch() {
        batchUpdate(it => {
            if (it.status === 'pending') {
                it.toDispatch = true;
                if (it.gui_status === GUI_STATUS.IDLE) it.gui_status = GUI_STATUS.SELECTED;
            }
        });
        running.value = true;

        if (!isDispatching.value) {
            dispatcher();
        }
    }

    function pause() {
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
