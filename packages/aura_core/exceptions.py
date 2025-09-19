# packages/aura_core/exceptions.py (FIXED - 完整版)

from typing import Optional, Dict, Any

# --- 基础异常 ---

class AuraException(Exception):
    """所有 Aura 核心自定义异常的基类。"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.details = details or {}

# --- 任务控制流异常 ---

class TaskControlException(Exception):
    """用于控制任务流程的基类异常，不应被视为错误。"""
    pass

class StopTaskException(TaskControlException):
    """当需要正常停止任务时抛出。"""
    def __init__(self, message: str, success: bool = True):
        self.message = message
        self.success = success
        super().__init__(self.message)

# --- 执行时错误 ---

class ExecutionError(AuraException):
    """执行期间发生的通用错误。"""
    pass

class TaskExecutionError(ExecutionError):
    """任务执行期间发生错误。"""
    def __init__(self, message: str, task_id: Optional[str] = None):
        super().__init__(message, details={'task_id': task_id})
        self.task_id = task_id

class ActionExecutionError(ExecutionError):
    """Action 执行期间发生错误。"""
    def __init__(self, message: str, action_name: Optional[str] = None):
        super().__init__(message, details={'action_name': action_name})
        self.action_name = action_name

class TaskNotFoundError(TaskExecutionError):
    """找不到指定的任务定义。"""
    def __init__(self, task_id: str):
        super().__init__(f"Task definition not found for '{task_id}'", task_id=task_id)

# --- 配置和设置错误 ---

class ConfigurationError(AuraException):
    """配置相关的错误。"""
    pass

class StatePlanningError(ConfigurationError):
    """状态规划器相关的错误。"""
    pass

class DependencyError(ConfigurationError):
    """依赖项解析或注入时发生错误。"""
    pass

# --- 资源错误 ---

class ResourceError(AuraException):
    """与资源相关的错误（如文件访问）。"""
    pass

class ResourceAcquisitionError(ResourceError):
    """获取资源（如信号量、锁）失败。"""
    def __init__(self, message: str, resource_type: str, operation: str):
        details = {'resource_type': resource_type, 'operation': operation}
        super().__init__(message, details=details)

# --- 其他错误 ---

class TimeoutError(AuraException):
    """操作超时。"""
    pass


# --- 异常工厂函数 (为了兼容旧代码) ---

def create_plugin_error(message: str, plugin_name: Optional[str] = None) -> ConfigurationError:
    """创建一个插件相关的配置错误。"""
    return ConfigurationError(message, details={'plugin_name': plugin_name})

def create_task_error(message: str, task_id: Optional[str] = None) -> TaskExecutionError:
    """创建一个任务执行错误。"""
    return TaskExecutionError(message, task_id=task_id)

def resource_unavailable(resource_type: str) -> ResourceError:
    """创建一个资源不可用的错误。"""
    return ResourceError(f"Resource of type '{resource_type}' is unavailable.")

def step_failed(step_id: str, reason: str) -> ActionExecutionError:
    """创建一个步骤失败的错误。"""
    return ActionExecutionError(f"Step '{step_id}' failed: {reason}", action_name=step_id)

def action_failed(action_name: str, reason: str) -> ActionExecutionError:
    """创建一个行为失败的错误。"""
    return ActionExecutionError(f"Action '{action_name}' failed: {reason}", action_name=action_name)
