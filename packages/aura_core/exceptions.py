from typing import Optional, Dict, Any
import traceback  # 【新增】for get_full_traceback


# --- 基础异常 ---

class AuraException(Exception):
    """所有 Aura 核心自定义异常的基类。【增强】支持 cause 和 traceback 保留。"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, cause: Optional[Exception] = None, severity: str = 'error'):
        super().__init__(message)
        self.details = details or {}
        self.cause = cause  # 【新增】原始异常
        self.severity = severity  # 【新增】严重级（error/warning/critical/signal）
        if cause:
            self.__cause__ = cause  # 【新增】Python 异常链，保留栈

    def get_full_traceback(self) -> str:
        """【新增】获取完整 traceback（包括 cause）。用于日志/result。"""
        if self.__cause__:
            return ''.join(traceback.format_exception(type(self.__cause__), self.__cause__, self.__cause__.__traceback__))
        else:
            return ''.join(traceback.format_exception(type(self), self, self.__traceback__))


# --- 任务控制流异常 ---

class TaskControlException(AuraException):
    """用于控制任务流程的基类异常，不应被视为错误。【增强】继承 AuraException 支持 cause。"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, cause: Optional[Exception] = None, severity: str = 'signal'):
        super().__init__(message, details, cause, severity)


class JumpSignal(TaskControlException):
    """【新增】控制流跳转信号（e.g., break/continue/switch）。支持 cause 和 traceback。"""
    def __init__(self, type: str, target: str, cause: Optional[Exception] = None):
        message = f"Jump signal: {type} to {target}"
        super().__init__(message, {'type': type, 'target': target}, cause, severity='signal')
        self.type = type
        self.target = target


class StopTaskException(TaskControlException):
    """当需要正常停止任务时抛出。【增强】兼容原有 success，添加 cause 和 severity（success=True 时 severity='success'）。"""
    def __init__(self, message: str, success: bool = True, details: Optional[Dict[str, Any]] = None, cause: Optional[Exception] = None,severity = None):
        # 【兼容】原有参数
        self.success = success
        # 【新增】自动设置 severity：success=True -> 'success'，否则 'critical' 或指定
        severity = 'success' if success else 'critical'
        super().__init__(message, details or {'success': success}, cause, severity)
        self.severity = severity


# --- 执行时错误 ---

class ExecutionError(AuraException):
    """执行期间发生的通用错误。【兼容】继承增强基类。"""
    pass


class TaskExecutionError(ExecutionError):
    """任务执行期间发生错误。【兼容】"""
    def __init__(self, message: str, task_id: Optional[str] = None, cause: Optional[Exception] = None):
        super().__init__(message, {'task_id': task_id}, cause)
        self.task_id = task_id


class ActionExecutionError(ExecutionError):
    """Action 执行期间发生错误。【兼容】"""
    def __init__(self, message: str, action_name: Optional[str] = None, cause: Optional[Exception] = None):
        super().__init__(message, {'action_name': action_name}, cause)
        self.action_name = action_name


class TaskNotFoundError(TaskExecutionError):
    """找不到指定的任务定义。【兼容】"""
    def __init__(self, task_id: str, cause: Optional[Exception] = None):
        super().__init__(f"Task definition not found for '{task_id}'", task_id=task_id, cause=cause)


# --- 配置和设置错误 ---

class ConfigurationError(AuraException):
    """配置相关的错误。【兼容】"""
    pass


class StatePlanningError(ConfigurationError):
    """状态规划器相关的错误。【兼容】"""
    pass


class DependencyError(ConfigurationError):
    """依赖项解析或注入时发生错误。【兼容】"""
    pass


# --- 资源错误 ---

class ResourceError(AuraException):
    """与资源相关的错误（如文件访问）。【兼容】"""
    pass


class ResourceAcquisitionError(ResourceError):
    """获取资源（如信号量、锁）失败。【兼容】"""
    def __init__(self, message: str, resource_type: str, operation: str, cause: Optional[Exception] = None):
        details = {'resource_type': resource_type, 'operation': operation}
        super().__init__(message, details, cause)


# --- 其他错误 ---

class TimeoutError(AuraException):
    """操作超时。【兼容】"""
    pass


# --- 异常工厂函数 (为了兼容旧代码) 【增强】支持 cause ---

def create_plugin_error(message: str, plugin_name: Optional[str] = None, cause: Optional[Exception] = None) -> ConfigurationError:
    """创建一个插件相关的配置错误。【增强】可选 cause。"""
    return ConfigurationError(message, {'plugin_name': plugin_name}, cause)


def create_task_error(message: str, task_id: Optional[str] = None, cause: Optional[Exception] = None) -> TaskExecutionError:
    """创建一个任务执行错误。【增强】可选 cause。"""
    return TaskExecutionError(message, task_id=task_id, cause=cause)


def resource_unavailable(resource_type: str, cause: Optional[Exception] = None) -> ResourceError:
    """创建一个资源不可用的错误。【增强】可选 cause。"""
    return ResourceError(f"Resource of type '{resource_type}' is unavailable.", cause=cause)


def step_failed(step_id: str, reason: str, cause: Optional[Exception] = None) -> ActionExecutionError:
    """创建一个步骤失败的错误。【增强】可选 cause。"""
    return ActionExecutionError(f"Step '{step_id}' failed: {reason}", action_name=step_id, cause=cause)


def action_failed(action_name: str, reason: str, cause: Optional[Exception] = None) -> ActionExecutionError:
    """创建一个行为失败的错误。【增强】可选 cause。"""
    return ActionExecutionError(f"Action '{action_name}' failed: {reason}", action_name=action_name, cause=cause)

# 【新增】工厂 for JumpSignal（便于使用）
def create_jump_signal(type: str, target: str, cause: Optional[Exception] = None) -> JumpSignal:
    """【新增】创建跳转信号异常。"""
    return JumpSignal(type, target, cause)

# 【新增】工厂 for StopTaskException（兼容原有）
def create_stop_task(message: str, success: bool = True, cause: Optional[Exception] = None) -> StopTaskException:
    """【新增】创建停止任务异常，兼容原有 success。"""
    return StopTaskException(message, success=success, cause=cause)