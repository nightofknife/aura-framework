<template>
  <div class="settings-view">
    <div class="header-bar">
      <div>
        <strong class="view-title">系统配置</strong>
        <div class="view-subtitle">参数会写入 config.yaml，部分配置需要重启后端才能完全生效</div>
      </div>
      <div class="toolbar">
        <button class="btn btn-ghost" @click="loadConfig" :disabled="loading">重新加载</button>
        <button class="btn btn-ghost" @click="resetDefaults" :disabled="loading || saving">恢复默认</button>
        <button class="btn btn-primary" @click="saveConfig" :disabled="saving">保存配置</button>
      </div>
    </div>

    <div class="panel glass glass-thick">
      <div class="panel-header">
        <strong>配置文件</strong>
        <span class="path">{{ configPath || '未找到 config.yaml' }}</span>
      </div>
      <div class="panel-body">
        <div v-if="errorMsg" class="error">{{ errorMsg }}</div>
        <div class="hint">所有参数都会保存到 config.yaml，建议保存后重启后端。</div>
      </div>
    </div>

    <div v-for="section in sections" :key="section.key" class="panel glass glass-thick">
      <div class="panel-header">
        <strong>{{ section.title }}</strong>
        <span v-if="section.desc" class="section-desc">{{ section.desc }}</span>
      </div>
      <div class="panel-body form-grid">
        <div v-for="field in section.fields" :key="field.path" class="field">
          <div class="label">{{ field.label }}</div>
          <select
            v-if="field.type === 'select'"
            class="select"
            :value="getFieldValue(field)"
            @change="setFieldValue(field, $event.target.value)"
          >
            <option v-for="opt in field.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
          <label v-else-if="field.type === 'boolean'" class="chk">
            <input
              type="checkbox"
              :checked="getFieldValue(field)"
              @change="setFieldValue(field, $event.target.checked)"
            >
            <span>{{ field.checkboxLabel || '启用' }}</span>
          </label>
          <input
            v-else-if="field.type === 'number'"
            class="input"
            type="number"
            :min="field.min"
            :max="field.max"
            :step="field.step || 1"
            :value="getFieldValue(field)"
            @input="setFieldValue(field, $event.target.value)"
            :placeholder="field.placeholder"
          />
          <input
            v-else-if="field.type === 'array_csv'"
            class="input"
            :value="getFieldValue(field)"
            @input="setFieldValue(field, $event.target.value)"
            :placeholder="field.placeholder || '多个值用逗号分隔'"
          />
          <input
            v-else
            class="input"
            :value="getFieldValue(field)"
            @input="setFieldValue(field, $event.target.value)"
            :placeholder="field.placeholder"
          />
          <div v-if="field.help" class="help">{{ field.help }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import axios from 'axios';
import { getGuiConfig } from '../config.js';
import { useToasts } from '../composables/useToasts.js';

const { push: toast } = useToasts();
const guiConfig = getGuiConfig();
const api = axios.create({
  baseURL: guiConfig?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: guiConfig?.api?.timeout_ms || 5000,
});

const DEFAULT_CONFIG = {
  backend: {
    app: { title: 'Aura Automation Framework API', version: '1.0.0' },
    api: { prefix: '/api/v1' },
    cors: {
      allow_origins: ['*'],
      allow_credentials: true,
      allow_methods: ['*'],
      allow_headers: ['*'],
    },
    websocket: { events_path: '/ws/v1/events' },
    scheduler_startup_timeout_sec: 10,
    server: {
      host: '0.0.0.0',
      port: 18098,
      reload: true,
      log_level: 'info',
      workers: 1,
      access_log: false,
    },
  },
  dependencies: {
    requirements_file: 'requirements.txt',
    auto_install: true,
    on_missing: 'skip_plan',
    pip: { timeout_sec: 120, args: [] },
  },
  logging: {
    log_dir: 'logs',
    task_name: { default: 'aura_session' },
  },
  scheduler: {
    num_event_workers: 1,
    queue: { main_maxsize: 1000, event_maxsize: 2000, interrupt_maxsize: 100 },
    loop_sleep_sec: { queue_full: 0.2, consumer_error: 0.5 },
  },
  execution: {
    max_concurrent_tasks: 1,
    io_workers: 16,
    cpu_workers: 4,
    state_planning: { max_replans: 10, replanning_sleep_sec: 1 },
  },
  task_loader: { cache_maxsize: 1024, cache_ttl_sec: 300 },
  scheduling_service: { tick_sec: 60 },
  interrupt_service: { poll_sec: 1 },
  id_generator: { instance_id: 1, epoch_ms: 1609459200000 },
  state_store: { type: 'file', path: './project_state.json' },
  gui: {
    api: {
      base_url: 'http://127.0.0.1:18098/api/v1',
      timeout_ms: 5000,
      dispatch_timeout_ms: 10000,
      status_poll_ms: 2000,
      queue_list_limit: 200,
    },
    ws: {
      base_url: 'ws://127.0.0.1:18098',
      heartbeat_ms: 25000,
      reconnect: { base_ms: 5000, multiplier: 2, max_ms: 30000, jitter: 0.2 },
    },
    staging: {
      poll_interval_ms: 1000,
      dispatch_delay_ms: 50,
      repeat_max: 500,
      remove_after_ms: 2000,
      history_max: 300,
      storage_keys: {
        queue: 'aura_staging_queue_v1',
        history: 'aura_staging_history_v1',
        auto: 'aura_runner_auto',
      },
    },
    theme: { default: 'system', storage_key: 'aura_theme' },
    navigation: {
      default_route: 'execute',
      items: [
        { key: 'dashboard', label: '仪表盘', icon: 'dashboard' },
        { key: 'execute', label: '执行台', icon: 'execute' },
        { key: 'runs', label: '运行中', icon: 'runs' },
        { key: 'plans', label: '方案/任务', icon: 'plans' },
        { key: 'task_editor', label: '任务编辑', icon: 'task_editor' },
        { key: 'settings', label: '设置', icon: 'settings' },
      ],
    },
    task_editor: { viewport: { default_zoom: 1, min_zoom: 0.2 } },
    background: { dynamic_enabled: true, max_dpr: 2, density: 2.0, speed: 0.4, strength: 0.8, mouse_push: 30, dust: 50 },
  },
};

const configState = ref(clone(DEFAULT_CONFIG));
const configPath = ref('');
const loading = ref(false);
const saving = ref(false);
const errorMsg = ref('');

const sections = [
  {
    key: 'backend',
    title: '后端服务',
    fields: [
      { path: 'backend.server.host', label: '监听地址', type: 'text' },
      { path: 'backend.server.port', label: '监听端口', type: 'number', min: 1, max: 65535 },
      { path: 'backend.server.reload', label: '自动重载', type: 'boolean' },
      {
        path: 'backend.server.log_level',
        label: '日志等级',
        type: 'select',
        options: [
          { value: 'debug', label: '调试' },
          { value: 'info', label: '信息' },
          { value: 'warning', label: '警告' },
          { value: 'error', label: '错误' },
          { value: 'critical', label: '致命' },
        ],
      },
      { path: 'backend.server.workers', label: '工作进程数', type: 'number', min: 1 },
      { path: 'backend.server.access_log', label: '访问日志', type: 'boolean' },
      { path: 'backend.api.prefix', label: 'API 前缀', type: 'text' },
      { path: 'backend.websocket.events_path', label: '事件 WS 路径', type: 'text' },
      { path: 'backend.scheduler_startup_timeout_sec', label: '启动超时(秒)', type: 'number', min: 1 },
      { path: 'backend.cors.allow_origins', label: 'CORS 允许来源', type: 'array_csv', help: '使用逗号分隔多个来源' },
      { path: 'backend.cors.allow_methods', label: 'CORS 允许方法', type: 'array_csv' },
      { path: 'backend.cors.allow_headers', label: 'CORS 允许请求头', type: 'array_csv' },
      { path: 'backend.cors.allow_credentials', label: 'CORS 允许凭证', type: 'boolean' },
    ],
  },
  {
    key: 'dependencies',
    title: '依赖管理',
    fields: [
      { path: 'dependencies.requirements_file', label: '依赖文件名', type: 'text' },
      { path: 'dependencies.auto_install', label: '自动安装依赖', type: 'boolean' },
      {
        path: 'dependencies.on_missing',
        label: '缺库处理',
        type: 'select',
        options: [
          { value: 'skip_plan', label: '跳过当前计划' },
          { value: 'continue', label: '继续加载计划' },
        ],
      },
      { path: 'dependencies.pip.timeout_sec', label: '安装超时(秒)', type: 'number', min: 10 },
      { path: 'dependencies.pip.args', label: 'pip 参数', type: 'array_csv', help: '例如：--index-url https://pypi.tuna.tsinghua.edu.cn/simple' },
    ],
  },
  {
    key: 'logging',
    title: '日志配置',
    fields: [
      { path: 'logging.log_dir', label: '日志目录', type: 'text' },
      { path: 'logging.task_name.default', label: '默认任务名', type: 'text' },
    ],
  },
  {
    key: 'scheduler',
    title: '调度器',
    fields: [
      { path: 'scheduler.num_event_workers', label: '事件工作线程', type: 'number', min: 1 },
      { path: 'scheduler.queue.main_maxsize', label: '主队列容量', type: 'number', min: 1 },
      { path: 'scheduler.queue.event_maxsize', label: '事件队列容量', type: 'number', min: 1 },
      { path: 'scheduler.queue.interrupt_maxsize', label: '中断队列容量', type: 'number', min: 1 },
      { path: 'scheduler.loop_sleep_sec.queue_full', label: '队列满等待(秒)', type: 'number', step: 0.1, min: 0 },
      { path: 'scheduler.loop_sleep_sec.consumer_error', label: '消费错误等待(秒)', type: 'number', step: 0.1, min: 0 },
    ],
  },
  {
    key: 'execution',
    title: '执行引擎',
    fields: [
      { path: 'execution.max_concurrent_tasks', label: '最大并发任务', type: 'number', min: 1 },
      { path: 'execution.io_workers', label: 'IO 线程数', type: 'number', min: 1 },
      { path: 'execution.cpu_workers', label: 'CPU 线程数', type: 'number', min: 1 },
      { path: 'execution.state_planning.max_replans', label: '最大重规划次数', type: 'number', min: 0 },
      { path: 'execution.state_planning.replanning_sleep_sec', label: '重规划等待(秒)', type: 'number', step: 0.1, min: 0 },
    ],
  },
  {
    key: 'task_loader',
    title: '任务加载',
    fields: [
      { path: 'task_loader.cache_maxsize', label: '缓存容量', type: 'number', min: 1 },
      { path: 'task_loader.cache_ttl_sec', label: '缓存 TTL(秒)', type: 'number', min: 1 },
    ],
  },
  {
    key: 'tickers',
    title: '周期与中断',
    fields: [
      { path: 'scheduling_service.tick_sec', label: '调度周期(秒)', type: 'number', min: 1 },
      { path: 'interrupt_service.poll_sec', label: '中断轮询(秒)', type: 'number', step: 0.1, min: 0 },
    ],
  },
  {
    key: 'id_generator',
    title: 'ID 生成',
    fields: [
      { path: 'id_generator.instance_id', label: '实例 ID', type: 'number', min: 1 },
      { path: 'id_generator.epoch_ms', label: '起始时间戳(毫秒)', type: 'number', min: 0 },
    ],
  },
  {
    key: 'state_store',
    title: '状态存储',
    fields: [
      {
        path: 'state_store.type',
        label: '存储类型',
        type: 'select',
        options: [
          { value: 'file', label: '文件' },
          { value: 'redis', label: 'Redis' },
        ],
      },
      { path: 'state_store.path', label: '存储路径', type: 'text' },
    ],
  },
  {
    key: 'gui',
    title: '前端界面',
    fields: [
      { path: 'gui.api.base_url', label: 'API 地址', type: 'text' },
      { path: 'gui.api.timeout_ms', label: 'API 超时(ms)', type: 'number', min: 100 },
      { path: 'gui.api.dispatch_timeout_ms', label: '派发超时(ms)', type: 'number', min: 100 },
      { path: 'gui.api.status_poll_ms', label: '状态轮询(ms)', type: 'number', min: 200 },
      { path: 'gui.api.queue_list_limit', label: '队列拉取条数', type: 'number', min: 10 },
      { path: 'gui.ws.base_url', label: 'WS 地址', type: 'text' },
      { path: 'gui.ws.heartbeat_ms', label: 'WS 心跳间隔(ms)', type: 'number', min: 1000 },
      { path: 'gui.ws.reconnect.base_ms', label: 'WS 重连基础(ms)', type: 'number', min: 500 },
      { path: 'gui.ws.reconnect.multiplier', label: 'WS 重连倍率', type: 'number', step: 0.1, min: 1 },
      { path: 'gui.ws.reconnect.max_ms', label: 'WS 重连上限(ms)', type: 'number', min: 1000 },
      { path: 'gui.ws.reconnect.jitter', label: 'WS 抖动比例', type: 'number', step: 0.1, min: 0, max: 1 },
      { path: 'gui.staging.poll_interval_ms', label: '前端队列轮询(ms)', type: 'number', min: 200 },
      { path: 'gui.staging.dispatch_delay_ms', label: '派发间隔(ms)', type: 'number', min: 0 },
      { path: 'gui.staging.repeat_max', label: '最大重复次数', type: 'number', min: 1 },
      { path: 'gui.staging.remove_after_ms', label: '移除延迟(ms)', type: 'number', min: 0 },
      { path: 'gui.staging.history_max', label: '历史记录上限', type: 'number', min: 50 },
      { path: 'gui.staging.storage_keys.queue', label: '队列存储键', type: 'text' },
      { path: 'gui.staging.storage_keys.history', label: '历史存储键', type: 'text' },
      { path: 'gui.staging.storage_keys.auto', label: '自动模式键', type: 'text' },
      {
        path: 'gui.theme.default',
        label: '主题模式',
        type: 'select',
        options: [
          { value: 'system', label: '跟随系统' },
          { value: 'light', label: '浅色' },
          { value: 'dark', label: '深色' },
        ],
      },
      { path: 'gui.theme.storage_key', label: '主题存储键', type: 'text' },
      {
        path: 'gui.navigation.default_route',
        label: '默认入口',
        type: 'select',
        options: [
          { value: 'execute', label: '执行台' },
          { value: 'dashboard', label: '仪表盘' },
          { value: 'runs', label: '运行中' },
          { value: 'plans', label: '方案/任务' },
          { value: 'task_editor', label: '任务编辑' },
          { value: 'settings', label: '设置' },
        ],
      },
      { path: 'gui.task_editor.viewport.default_zoom', label: '编辑器默认缩放', type: 'number', step: 0.1, min: 0.1 },
      { path: 'gui.task_editor.viewport.min_zoom', label: '编辑器最小缩放', type: 'number', step: 0.1, min: 0.05 },
      { path: 'gui.background.dynamic_enabled', label: '动态背景', type: 'boolean' },
      { path: 'gui.background.max_dpr', label: '背景最大 DPR', type: 'number', step: 0.1, min: 1 },
      { path: 'gui.background.density', label: '动态线条密度', type: 'number', step: 0.1, min: 0.5, max: 4 },
      { path: 'gui.background.speed', label: '动态线条速度', type: 'number', step: 0.05, min: 0, max: 3 },
      { path: 'gui.background.strength', label: '动态线条振幅', type: 'number', step: 0.05, min: 0, max: 2 },
      { path: 'gui.background.mouse_push', label: '鼠标扰动强度', type: 'number', step: 1, min: 0, max: 80 },
      { path: 'gui.background.dust', label: '星尘数量', type: 'number', step: 1, min: 0, max: 200 },
    ],
  },
];

function getFieldValue(field) {
  const value = getPath(configState.value, field.path);
  if (field.type === 'array_csv') {
    if (Array.isArray(value)) return value.join(', ');
    return value == null ? '' : String(value);
  }
  if (field.type === 'boolean') {
    return !!value;
  }
  return value ?? '';
}

function setFieldValue(field, raw) {
  let next = raw;
  if (field.type === 'number') {
    const num = Number(raw);
    next = Number.isFinite(num) ? num : 0;
  } else if (field.type === 'boolean') {
    next = !!raw;
  } else if (field.type === 'array_csv') {
    next = parseCsv(raw);
  }
  setPath(configState.value, field.path, next);
}

function parseCsv(value) {
  if (Array.isArray(value)) return value;
  return String(value || '')
    .split(',')
    .map(item => item.trim())
    .filter(Boolean);
}

function clone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function deepMerge(target, source) {
  if (!source || typeof source !== 'object') return target;
  const out = Array.isArray(target) ? [...target] : { ...target };
  for (const [key, value] of Object.entries(source)) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      out[key] = deepMerge(out[key] || {}, value);
    } else {
      out[key] = value;
    }
  }
  return out;
}

function getPath(obj, path) {
  const parts = path.split('.');
  let curr = obj;
  for (const part of parts) {
    if (!curr || typeof curr !== 'object') return undefined;
    curr = curr[part];
  }
  return curr;
}

function setPath(obj, path, value) {
  const parts = path.split('.');
  let curr = obj;
  for (let i = 0; i < parts.length - 1; i += 1) {
    const key = parts[i];
    if (!curr[key] || typeof curr[key] !== 'object') {
      curr[key] = {};
    }
    curr = curr[key];
  }
  curr[parts[parts.length - 1]] = value;
}

async function loadConfig() {
  loading.value = true;
  errorMsg.value = '';
  try {
    const { data } = await api.get('/system/config');
    configPath.value = data?.path || '';
    if (!data?.exists) {
      errorMsg.value = '未找到 config.yaml，已使用默认配置。';
    }
    configState.value = deepMerge(clone(DEFAULT_CONFIG), data?.data || {});
  } catch (e) {
    const msg = e?.response?.data?.detail || e.message;
    errorMsg.value = msg;
    toast({ type: 'error', title: '加载失败', message: msg });
  } finally {
    loading.value = false;
  }
}

async function saveConfig() {
  saving.value = true;
  errorMsg.value = '';
  try {
    await api.put('/system/config', { data: configState.value });
    toast({ type: 'success', title: '保存成功', message: '已写入 config.yaml（部分配置需重启生效）' });
  } catch (e) {
    const msg = e?.response?.data?.detail || e.message;
    errorMsg.value = msg;
    toast({ type: 'error', title: '保存失败', message: msg });
  } finally {
    saving.value = false;
  }
}

function resetDefaults() {
  configState.value = clone(DEFAULT_CONFIG);
  toast({ type: 'info', title: '已恢复默认', message: '请保存以写入 config.yaml' });
}

loadConfig();
</script>

<style scoped>
.settings-view { display:flex; flex-direction:column; gap:16px; }
.header-bar { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.view-title { font-size:22px; }
.view-subtitle { color:var(--text-3); font-size:12px; }
.toolbar { display:flex; gap:8px; flex-wrap:wrap; }
.panel-header { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.path { color:var(--text-3); font-size:12px; }
.section-desc { color:var(--text-3); font-size:12px; }
.form-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:12px; }
.field .label { font-size:12px; color:var(--text-3); margin-bottom:6px; }
.help { color:var(--text-3); font-size:12px; margin-top:6px; }
.error { color:#c00; font-size:12px; }
.hint { color:var(--text-3); font-size:12px; }
</style>
