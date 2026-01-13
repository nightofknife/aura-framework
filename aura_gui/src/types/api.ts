// API 响应类型定义
// 这个文件包含所有与后端 API 交互相关的 TypeScript 类型定义

/**
 * 系统状态响应
 */
export interface SystemStatus {
  is_running: boolean
  version?: string
  uptime?: number
}

/**
 * 任务运行记录
 */
export interface TaskRun {
  id: string
  cid: string
  plan_name: string
  task_name: string
  status: 'running' | 'success' | 'error' | 'queued'
  started_at?: number
  finished_at?: number
  error_message?: string
  result?: unknown
  inputs?: Record<string, unknown>
}

/**
 * 队列项
 */
export interface QueueItem {
  cid: string
  task_name: string
  plan_name: string
  status: 'queued' | 'running'
  enqueued_at: number
  inputs?: Record<string, unknown>
  priority?: number
}

/**
 * Plan 定义
 */
export interface Plan {
  name: string
  path: string
  tasks: string[]
  entry_point?: string
}

/**
 * Task 定义
 */
export interface TaskDefinition {
  name: string
  meta: TaskMetadata
  steps: Record<string, StepDefinition>
}

/**
 * Task 元数据
 */
export interface TaskMetadata {
  title?: string
  description?: string
  entry_point?: boolean
  inputs?: InputParameter[]
  concurrency?: ConcurrencyConfig
}

/**
 * 输入参数定义
 */
export interface InputParameter {
  name: string
  label?: string
  type?: 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object'
  default?: unknown
  required?: boolean
  min?: number
  max?: number
  allowed?: unknown[]
}

/**
 * 并发配置
 */
export type ConcurrencyConfig =
  | 'exclusive'
  | 'concurrent'
  | 'shared'
  | {
      mode?: 'exclusive' | 'concurrent' | 'shared'
      resources?: string[]
      mutex_group?: string
      max_instances?: number
    }

/**
 * Step 定义
 */
export interface StepDefinition {
  action: string
  params?: Record<string, unknown>
  outputs?: Record<string, string>
  depends_on?: string | string[]
  loop?: LoopConfig
  retry?: RetryConfig
}

/**
 * 循环配置
 */
export interface LoopConfig {
  items?: string
  variable?: string
  max_iterations?: number
}

/**
 * 重试配置
 */
export interface RetryConfig {
  max_attempts?: number
  delay?: number
  backoff?: number
  on_exception?: string | string[]
  condition?: string
}

/**
 * WebSocket 事件
 */
export interface WebSocketEvent {
  type: 'system_status' | 'task_update' | 'queue_update' | 'log' | 'error'
  data: unknown
  timestamp?: number
}

/**
 * 日志消息
 */
export interface LogMessage {
  name: string
  msg: string
  levelname: 'TRACE' | 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'
  levelno: number
  pathname: string
  filename: string
  module: string
  lineno: number
  funcName: string
  created: number
  message: string
}

/**
 * API 错误响应
 */
export interface ApiError {
  detail: string
  status?: number
  type?: string
}

/**
 * 分发任务请求
 */
export interface DispatchTaskRequest {
  plan_name: string
  task_name: string
  inputs?: Record<string, unknown>
  priority?: number
}

/**
 * 分发任务响应
 */
export interface DispatchTaskResponse {
  cid: string
  status: string
  message?: string
}
