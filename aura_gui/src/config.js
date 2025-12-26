const DEFAULT_CONFIG = {
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
    events_path: '/ws/v1/events',
    logs_path: '/ws/logs',
    logs_enabled: true,
    reconnect: {
      base_ms: 5000,
      multiplier: 2,
      max_ms: 30000,
      jitter: 0.2,
    },
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
  theme: {
    default: 'system',
    storage_key: 'aura_theme',
  },
  navigation: {
    default_route: 'execute',
    items: [
      { key: 'dashboard', label: '仪表盘', icon: 'dashboard' },
      { key: 'execute', label: '执行台', icon: 'execute' },
      { key: 'runs', label: '运行中', icon: 'runs' },
      { key: 'plans', label: '方案/任务', icon: 'plans' },
      { key: 'automation', label: '自动化', icon: 'automation' },
      { key: 'task_editor', label: '任务编辑', icon: 'task_editor' },
      { key: 'settings', label: '设置', icon: 'settings' },
    ],
  },
  task_editor: {
    viewport: {
      default_zoom: 1,
      min_zoom: 0.2,
    },
  },
  logs: {
    display_level: 'warning',
  },
  background: {
    dynamic_enabled: true,
    max_dpr: 2,
    density: 2.0,
    speed: 0.4,
    strength: 0.8,
    mouse_push: 30,
    dust: 50,
  },
};

let cachedConfig = JSON.parse(JSON.stringify(DEFAULT_CONFIG));

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

function applyEnvOverrides() {
  const apiBase = import.meta?.env?.VITE_API_BASE_URL;
  const wsBase = import.meta?.env?.VITE_WS_URL;
  const timeoutMs = import.meta?.env?.VITE_API_TIMEOUT_MS;
  if (apiBase) cachedConfig.api.base_url = apiBase;
  if (wsBase) cachedConfig.ws.base_url = wsBase;
  if (timeoutMs) cachedConfig.api.timeout_ms = Number(timeoutMs);
}

export async function loadGuiConfig() {
  applyEnvOverrides();
  try {
    const resp = await fetch(`${cachedConfig.api.base_url}/system/config/gui`, { cache: 'no-store' });
    if (resp.ok) {
      const data = await resp.json();
      cachedConfig = deepMerge(cachedConfig, data);
    }
  } catch {
  }
  return cachedConfig;
}

export function getGuiConfig() {
  return cachedConfig;
}

