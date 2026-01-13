/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

// GUI 配置接口
interface GuiConfig {
  api?: {
    base_url?: string
    timeout_ms?: number
    dispatch_timeout_ms?: number
    status_poll_ms?: number
    queue_list_limit?: number
  }
  ws?: {
    base_url?: string
    heartbeat_ms?: number
    reconnect?: {
      base_ms?: number
      multiplier?: number
      max_ms?: number
      jitter?: number
    }
    logs_enabled?: boolean
    logs_path?: string
  }
  staging?: {
    poll_interval_ms?: number
    dispatch_delay_ms?: number
    repeat_max?: number
    remove_after_ms?: number
    history_max?: number
    storage_keys?: {
      queue?: string
      history?: string
      auto?: string
    }
  }
  theme?: {
    default?: string
    storage_key?: string
  }
}

// 扩展 Window 接口
interface Window {
  guiConfig?: GuiConfig
}
