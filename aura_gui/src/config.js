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
      { key: 'execute', label: '执行台', icon: 'play' },
      { key: 'tasks', label: '任务库', icon: 'library' },
      { key: 'runs', label: '运行记录', icon: 'history' },
      { key: 'capabilities', label: '能力中心', icon: 'cpu' },
      { key: 'settings', label: '设置', icon: 'settings' },
    ],
  },
  logs: {
    display_level: 'warning',
  },
  features: {
    local_admin: false,
  },
  background: {
    dynamic_enabled: false,
    max_dpr: 2,
    density: 2.0,
    speed: 0.4,
    strength: 0.8,
    mouse_push: 30,
    dust: 50,
  },
};

export const RUNTIME_CONNECTION_STORAGE_KEY = 'aura_runtime_connection'
export const RUNTIME_CONNECTION_EVENT = 'aura-runtime-connection-changed'

let cachedConfig = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
let envOverridesApplied = false;
let storageOverridesApplied = false;

function safeStorage() {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function applyEnvOverrides() {
  if (envOverridesApplied) return;
  const env = import.meta.env || {};
  const apiBase = env.VITE_API_BASE_URL;
  const wsBase = env.VITE_WS_URL;
  const timeoutMs = env.VITE_API_TIMEOUT_MS;
  if (apiBase) cachedConfig.api.base_url = apiBase;
  if (wsBase) cachedConfig.ws.base_url = wsBase;
  if (timeoutMs) cachedConfig.api.timeout_ms = Number(timeoutMs);
  envOverridesApplied = true;
}

function applyRuntimeConnection(connection) {
  if (!connection || typeof connection !== 'object') return;
  if (connection.apiBase) cachedConfig.api.base_url = String(connection.apiBase);
  if (connection.wsBase) cachedConfig.ws.base_url = String(connection.wsBase);
}

function applyStoredRuntimeConnection() {
  if (storageOverridesApplied) return;
  storageOverridesApplied = true;
  const raw = safeStorage()?.getItem(RUNTIME_CONNECTION_STORAGE_KEY);
  if (!raw) return;
  try {
    applyRuntimeConnection(JSON.parse(raw));
  } catch {
    safeStorage()?.removeItem(RUNTIME_CONNECTION_STORAGE_KEY);
  }
}

export async function loadGuiConfig() {
  applyEnvOverrides();
  applyStoredRuntimeConnection();
  return cachedConfig;
}

export function getGuiConfig() {
  applyEnvOverrides();
  applyStoredRuntimeConnection();
  return cachedConfig;
}

export function setRuntimeConnection(connection) {
  const next = {
    id: connection?.id || 'manual',
    apiBase: String(connection?.apiBase || '').trim(),
    wsBase: String(connection?.wsBase || '').trim(),
  };
  if (!next.apiBase) throw new Error('Runtime API base is required.');
  applyRuntimeConnection(next);
  safeStorage()?.setItem(RUNTIME_CONNECTION_STORAGE_KEY, JSON.stringify(next));
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(RUNTIME_CONNECTION_EVENT, { detail: next }));
  }
  return next;
}

export function clearRuntimeConnection() {
  safeStorage()?.removeItem(RUNTIME_CONNECTION_STORAGE_KEY);
  cachedConfig = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
  envOverridesApplied = false;
  storageOverridesApplied = false;
  applyEnvOverrides();
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(RUNTIME_CONNECTION_EVENT, { detail: null }));
  }
}
