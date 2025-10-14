import { ref, watch, nextTick, effectScope } from 'vue';
import axios from 'axios';
import { useStagingQueue, GUI_STATUS } from './useStagingQueue.js';
import { useAuraSocket } from './useAuraSocket.js';
import { useToasts } from './useToasts.js';

const api = axios.create({ baseURL: 'http://127.0.0.1:8000/api', timeout: 8000 });

// 运行器内部状态
const running = ref(false);
const autoMode = ref(false);

const batchEpoch = ref(null);
const snapshotIds = ref([]);
const pointer = ref(0);

const currentId = ref(null);

// 等待表 + 早到缓存
const waitMap = new Map();   // 'run:<rid>' | 'task:<id>' -> { resolve, timer, promise }
const earlyFinish = new Set();

const AUTO_LS = 'aura_runner_auto';
try { autoMode.value = JSON.parse(localStorage.getItem(AUTO_LS) || 'false'); } catch {}

let booted = false;
let scope = null;

function toMs(v){ if(v==null) return 0; return v>1e12 ? v : Math.floor(v*1000); }
function createDeferred(ms=30*60*1000){ let resolve; const p = new Promise(r => resolve = r); const timer = setTimeout(()=>{ try{ resolve(); }catch{} }, ms); return {promise:p, resolve, timer}; }

export function useStagingRunner(){
    const { items, updateTask, removeTask, pushHistory, batchUpdate, setGuiStatus } = useStagingQueue();
    const { lastMessage, connect } = useAuraSocket();
    const { push: toast } = useToasts();

    // ---------- 批次：一次性打标 + 快照 ----------
    function markSnapshotAndTagAll(){
        const epoch = Date.now();
        batchEpoch.value = epoch;
        snapshotIds.value = items.value.map(x => x.id);
        pointer.value = 0;

        batchUpdate((it, set) => {
            const s = (it.status || 'pending').toLowerCase();
            if (!(s === 'pending' || !it.status)) return false;

            let c = false;
            c = set(it, 'toDispatch', true) || c;
            c = set(it, 'toDispatchEpoch', epoch) || c;
            c = set(it, 'status', 'pending') || c;

            if (it.gui_status === GUI_STATUS.IDLE) {
                c = set(it, 'gui_status', GUI_STATUS.SELECTED) || c;
                if (!it.selectedAt) { it.selectedAt = Date.now(); c = true; }
            }
            return c;
        });
    }

    async function startBatch(){
        if (running.value) return;
        running.value = true;
        markSnapshotAndTagAll();
        processNext();
    }

    function pause(){
        running.value = false;
        const cur = currentId.value;
        batchUpdate((it, set) => {
            if (it.id === cur || !it.toDispatch) return false;
            let c = false;
            c = set(it, 'toDispatch', false) || c;
            c = set(it, 'toDispatchEpoch', null) || c;
            if (!it.handoff && it.gui_status !== GUI_STATUS.IDLE) {
                c = set(it, 'gui_status', GUI_STATUS.SELECTED) || c;
            }
            return c;
        });
    }

    function setAuto(v){
        autoMode.value = !!v;
        try { localStorage.setItem(AUTO_LS, JSON.stringify(autoMode.value)); } catch {}
        if (autoMode.value) {
            batchUpdate((it, set) => {
                const s = (it.status || 'pending').toLowerCase();
                if (it.toDispatch || !(s === 'pending' || !it.status)) return false;

                let c = false;
                c = set(it, 'toDispatch', true) || c;
                c = set(it, 'status', 'pending') || c;
                if (it.gui_status === GUI_STATUS.IDLE) {
                    c = set(it, 'gui_status', GUI_STATUS.SELECTED) || c;
                    if (!it.selectedAt) { it.selectedAt = Date.now(); c = true; }
                }
                return c;
            });

            if (!running.value) processAutoIfIdle();
        }
    }

    function forceStop(){
        pause();
        toast({ type: 'info', title: 'Paused', message: 'Queue dispatch paused.' });
    }

    function processAutoIfIdle(){
        if (running.value) return;
        const nxt = items.value.find(x => x.toDispatch && ((x.status || 'pending').toLowerCase()==='pending' || !x.status));
        if (!nxt) return;
        batchEpoch.value = null; snapshotIds.value = []; pointer.value = 0;
        running.value = true;
        processNext();
    }

    // ---------- 主推进 ----------
    async function processNext(){
        if (!running.value) return;

        let nextId = null;

        if (batchEpoch.value) {
            for (; pointer.value < snapshotIds.value.length; pointer.value++) {
                const id = snapshotIds.value[pointer.value];
                const it = items.value.find(x => x.id === id);
                if (!it) continue;
                if (it.toDispatchEpoch !== batchEpoch.value) continue;
                const s = (it.status || 'pending').toLowerCase();
                if (['running', 'dispatching', 'dispatched'].includes(s)) { nextId = id; break; }
                if (!['success','error'].includes(s)) { nextId = id; break; }
            }
        } else {
            const it = items.value.find(x => x.toDispatch && ((x.status || 'pending').toLowerCase()==='pending' || !x.status));
            if (it) nextId = it.id;
        }

        if (!nextId) {
            running.value = false;
            if (batchEpoch.value) { batchEpoch.value = null; snapshotIds.value = []; }
            return;
        }

        currentId.value = nextId;
        const item = items.value.find(x => x.id === nextId);
        if (!item) return stepDone();

        const cur = (item.status || '').toLowerCase();
        if (['dispatching','dispatched','running'].includes(cur)) {
            await waitForFinish(item);
            return stepDone();
        }

        // 进入 DISPATCHING（GUI）
        setGuiStatus(item.id, GUI_STATUS.DISPATCHING);

        // 派发前建立等待（避免完成事件先到）
        const localKey = `task:${item.id}`;
        if (!waitMap.has(localKey)) waitMap.set(localKey, createDeferred());

        updateTask(item.id, { status: 'dispatching' });
        try {
            const resp = await api.post('/tasks/run', {
                plan_name: item.plan_name, task_name: item.task_name, inputs: item.inputs || {}
            });

            // 有些实现返回 200 但 ok=false（比如引擎未启动）
            if (resp && resp.data && resp.data.ok === false) {
                const msg = String(resp.data.message || '').toLowerCase();
                if (msg.includes('scheduler is not running')) {
                    setGuiStatus(item.id, GUI_STATUS.WAITING_ENGINE, { toDispatch: true });
                } else {
                    setGuiStatus(item.id, GUI_STATUS.ENQUEUE_FAILED);
                }
                updateTask(item.id, { status: 'pending' });
                return stepDone();
            }

            // 入队成功（等待 queue.enqueued 驱动到 QUEUED）
            updateTask(item.id, { dispatchedAt: Date.now(), status: 'dispatched' });

            await waitForFinish(item);
        } catch (e) {
            // 网络/HTTP 错误
            const msg = String(e?.response?.data?.message || e?.message || '').toLowerCase();
            if (msg.includes('scheduler is not running')) {
                setGuiStatus(item.id, GUI_STATUS.WAITING_ENGINE, { toDispatch: true });
            } else {
                setGuiStatus(item.id, GUI_STATUS.ENQUEUE_FAILED);
            }
            updateTask(item.id, { status: 'pending' });
        }

        stepDone();

        function stepDone(){
            if (batchEpoch.value) pointer.value++;
            nextTick(() => processNext());
        }
    }

    function waitForFinish(item){
        const k = item.run_id ? `run:${item.run_id}` : `task:${item.id}`;
        if (earlyFinish.has(k)) { earlyFinish.delete(k); return Promise.resolve(); }
        if (!waitMap.has(k)) waitMap.set(k, createDeferred());
        return waitMap.get(k).promise;
    }

    function resolveKey(key){
        const d = waitMap.get(key);
        if (d) { clearTimeout(d.timer); try{ d.resolve(); }catch{} waitMap.delete(key); }
        else { earlyFinish.add(key); }
    }

    // ---------- 事件桥 ----------
    function onQueueEnqueued(p){
        // 仅影响 GUI（进入 QUEUED / 交付完成），无 run_id，只能按当前派发项近似匹配
        const plan = p.plan_name, task = p.task_name;
        const enqMs = toMs(p.enqueued_at ?? p.start_time ?? Date.now());

        // 候选：DISPATCHING/DISPATCHED 的项
        const candidates = items.value.filter(x =>
            (x.status === 'dispatching' || x.status === 'dispatched') &&
            (plan ? x.plan_name === plan : true) &&
            (task ? x.task_name === task : true)
        );
        if (!candidates.length) return;
        let best = candidates[0], bestDiff = 1e15;
        for (const it of candidates) {
            const d = Math.abs((it.dispatchedAt || 0) - (enqMs || Date.now()));
            if (d < bestDiff) { best = it; bestDiff = d; }
        }
        setGuiStatus(best.id, GUI_STATUS.QUEUED, { enqueuedAt: enqMs, handoff: true });
    }

    function onQueueDequeued(p){
        const plan = p.plan_name, task = p.task_name;
        const dqMs = toMs(p.start_time ?? Date.now());

        // 候选：已交付（QUEUED/派发中）但未 RUNNING 的项
        const candidates = items.value.filter(x =>
            (x.gui_status === GUI_STATUS.QUEUED || x.status === 'dispatched' || x.status === 'dispatching') &&
            (plan ? x.plan_name === plan : true) &&
            (task ? x.task_name === task : true)
        );
        if (!candidates.length) return;
        let best = candidates[0], bestDiff = 1e15;
        for (const it of candidates) {
            const d = Math.abs((it.enqueuedAt || it.dispatchedAt || 0) - (dqMs || Date.now()));
            if (d < bestDiff) { best = it; bestDiff = d; }
        }
        setGuiStatus(best.id, GUI_STATUS.DEQUEUED, { dequeuedAt: dqMs, handoff: true });
    }

    function onStarted(p){
        const plan = p.plan_name, task = p.task_name;
        const runId = p.run_id || null;
        const startMs = toMs(p.start_time ?? p.started_at ?? p.timestamp);

        let candidates = items.value.filter(x =>
            (x.status === 'dispatched' || x.status === 'dispatching') &&
            (plan ? x.plan_name === plan : true) &&
            (task ? x.task_name === task : true)
        );
        if (!candidates.length && currentId.value) {
            const cur = items.value.find(x => x.id === currentId.value);
            if (cur) candidates = [cur];
        }
        if (!candidates.length) return;

        let best = candidates[0], bestDiff = 1e15;
        for (const it of candidates) {
            const d = Math.abs((it.dispatchedAt || 0) - (startMs || Date.now()));
            if (d < bestDiff) { best = it; bestDiff = d; }
        }

        const beforeKey = `task:${best.id}`;
        const afterKey  = runId ? `run:${runId}` : beforeKey;

        updateTask(best.id, { status: 'running', run_id: runId || best.run_id || null, startedAt: startMs || Date.now() });
        setGuiStatus(best.id, GUI_STATUS.RUNNING, { handoff: true });

        if (waitMap.has(beforeKey) && runId) {
            const d = waitMap.get(beforeKey); waitMap.delete(beforeKey);
            if (earlyFinish.has(afterKey)) { clearTimeout(d.timer); try{ d.resolve(); }catch{} earlyFinish.delete(afterKey); }
            else waitMap.set(afterKey, d);
        }
    }

    function onFinished(p){
        const runId = p.run_id || null;
        if (!runId) return;
        const key = `run:${runId}`;

        const target = items.value.find(x => x.run_id === runId);
        const statusRaw = String(p.final_status ?? p.status ?? '').toLowerCase();
        const ok = ['success','succeeded','completed','ok'].includes(statusRaw);

        resolveKey(key);

        if (!target) return; // 子任务或非当前 GUI 条目

        const finishedAt = toMs(p.end_time ?? p.finished_at) || Date.now();

        if (ok) {
            setGuiStatus(target.id, GUI_STATUS.SUCCESS, { finishedAt });
            pushHistory({ ...target, status:'success', run_id: runId, finishedAt });
            removeTask(target.id);                // ✅ 成功后立刻从队列移除
        } else {
            setGuiStatus(target.id, GUI_STATUS.ERROR, {
                finishedAt, toDispatch: false, toDispatchEpoch: null
            });
            updateTask(target.id, { status: 'error' });
        }
    }

    // ---------- 启动一次 ----------
    function bootOnce(){
        if (booted) return; booted = true;
        connect?.();

        scope = effectScope();
        scope.run(() => {
            watch(lastMessage, evt => {
                if (!evt) return;
                const name = String(evt.name || '').toLowerCase();
                const p = evt.payload || {};

                // 队列事件（GUI 可见）
                if (name === 'queue.enqueued') return onQueueEnqueued(p);
                if (name === 'queue.dequeued') return onQueueDequeued(p);

                // 引擎事件（严格用 run_id）
                const isStart = (name.startsWith('task') || name.startsWith('run')) && name.endsWith('.started');
                const isFinish = (name.startsWith('task') || name.startsWith('run')) &&
                    (name.endsWith('.finished') || name.endsWith('.completed') || name.endsWith('.succeeded') || name.endsWith('.failed'));

                if (isStart) return onStarted(p);
                if (isFinish) return onFinished(p);
            });

            // Auto：始终保持“可执行项被选中”，空闲时自动推进
            watch([autoMode, items], () => {
                if (autoMode.value) {
                    batchUpdate(it => {
                        const s = (it.status || 'pending').toLowerCase();
                        if (!it.toDispatch && (s==='pending' || !it.status)) {
                            it.toDispatch = true;
                            it.status = 'pending';
                            if (it.gui_status === GUI_STATUS.IDLE) {
                                it.gui_status = GUI_STATUS.SELECTED;
                                it.selectedAt = it.selectedAt || Date.now();
                            }
                        }
                    });
                    if (!running.value) processAutoIfIdle();
                }
            }, { deep: true });
        });
    }

    bootOnce();

    return {
        running, autoMode, currentId, batchEpoch,
        startBatch, pause, setAuto, forceStop,
    };
}
