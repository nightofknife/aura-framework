"""
定义了 Aura 框架中所有自定义的异常类。

这个模块建立了一个结构化的异常体系，旨在提供清晰、可追溯的错误信息。
所有自定义异常都继承自 `AuraException`，它增强了标准的 `Exception`，
支持附加详细信息、严重级别以及保留原始的异常原因（cause），从而实现了
完整的异常链追踪。

异常被分为几大类：
- **任务控制流异常**: 用于控制任务执行流程，不代表真正的错误（如 `JumpSignal`, `StopTaskException`）。
- **执行时错误**: 在任务或行为执行期间发生的错误（如 `TaskExecutionError`）。
- **配置和设置错误**: 与框架、插件或任务配置相关的错误（如 `ConfigurationError`）。
- **资源错误**: 与外部资源（文件、网络、锁等）交互时发生的错误。

此外，模块还提供了一系列工厂函数（如 `create_task_error`），用于方便地创建特定类型的异常实例。
"""
from typing import Optional, Dict, Any
import traceback


# --- 基础异常 ---

class AuraException(Exception):
    """
    所有 Aura 核心自定义异常的基类。

    这个基类扩展了标准的 `Exception`，增加了对附加细节、严重级别和
    异常链的支持。

    Attributes:
        details (Dict[str, Any]): 一个包含关于异常的附加结构化信息的字典。
        cause (Optional[Exception]): 导致此异常被抛出的原始异常对象。
        severity (str): 异常的严重级别，例如 'error', 'warning', 'critical', 'signal'。
    """
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, cause: Optional[Exception] = None, severity: str = 'error'):
        """
        初始化 AuraException。

        Args:
            message (str): 人类可读的异常信息。
            details (Optional[Dict[str, Any]]): 附加的结构化数据。
            cause (Optional[Exception]): 包装的原始异常。
            severity (str): 异常的严重级别。
        """
        super().__init__(message)
        self.details = details or {}
        self.cause = cause
        self.severity = severity
        if cause:
            self.__cause__ = cause  # 建立 Python 的原生异常链

    def get_full_traceback(self) -> str:
        """
        获取完整的堆栈跟踪信息，包括其 cause 的堆栈跟踪。

        Returns:
            str: 格式化后的完整堆栈跟踪字符串。
        """
        if self.__cause__:
            return ''.join(traceback.format_exception(type(self.__cause__), self.__cause__, self.__cause__.__traceback__))
        else:
            return ''.join(traceback.format_exception(type(self), self, self.__traceback__))


# --- 任务控制流异常 ---

class TaskControlException(AuraException):
    """
    用于控制任务流程的基类异常，通常不应被视为错误。

    这类异常用于实现如跳出循环、提前终止任务等非线性的执行逻辑。
    它们的默认严重级别是 'signal'。
    """
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, cause: Optional[Exception] = None, severity: str = 'signal'):
        super().__init__(message, details, cause, severity)


class JumpSignal(TaskControlException):
    """
    一个控制流跳转信号，用于实现类似 `break`, `continue`, `goto` 的逻辑。

    当 `ExecutionEngine` 捕获到此信号时，会中断当前执行路径，并根据
    `type` 和 `target` 调整执行流程。

    Attributes:
        type (str): 跳转类型，例如 'break'。
        target (str): 跳转目标，例如目标循环节点的ID。
    """
    def __init__(self, type: str, target: str, cause: Optional[Exception] = None):
        message = f"Jump signal: {type} to {target}"
        super().__init__(message, {'type': type, 'target': target}, cause, severity='signal')
        self.type = type
        self.target = target


class StopTaskException(TaskControlException):
    """
    当需要正常（或非正常）停止整个任务时抛出。

    Attributes:
        success (bool): 指示任务是成功停止还是失败停止。
    """
    def __init__(self, message: str, success: bool = True, details: Optional[Dict[str, Any]] = None, cause: Optional[Exception] = None, severity: Optional[str] = None):
        self.success = success
        # 根据 success 状态自动决定严重级别
        final_severity = severity or ('success' if success else 'critical')
        super().__init__(message, details or {'success': success}, cause, final_severity)


# --- 执行时错误 ---

class ExecutionError(AuraException):
    """在任务或行为执行期间发生的通用错误。"""
    pass


class TaskExecutionError(ExecutionError):
    """在特定任务执行期间发生的错误。"""
    def __init__(self, message: str, task_id: Optional[str] = None, cause: Optional[Exception] = None):
        super().__init__(message, {'task_id': task_id}, cause)
        self.task_id = task_id


class ActionExecutionError(ExecutionError):
    """在特定行为（Action）执行期间发生的错误。"""
    def __init__(self, message: str, action_name: Optional[str] = None, cause: Optional[Exception] = None):
        super().__init__(message, {'action_name': action_name}, cause)
        self.action_name = action_name


class TaskNotFoundError(TaskExecutionError):
    """当尝试加载一个不存在的任务定义时抛出。"""
    def __init__(self, task_id: str, cause: Optional[Exception] = None):
        super().__init__(f"Task definition not found for '{task_id}'", task_id=task_id, cause=cause)


# --- 配置和设置错误 ---

class ConfigurationError(AuraException):
    """与框架、插件或任务的配置相关的错误。"""
    pass


class StatePlanningError(ConfigurationError):
    """在状态规划（从当前状态到目标状态的路径计算）期间发生的错误。"""
    pass


class DependencyError(ConfigurationError):
    """在解析或注入服务依赖项时发生的错误。"""
    pass


# --- 资源错误 ---

class ResourceError(AuraException):
    """与外部资源（如文件访问、网络连接）相关的通用错误。"""
    pass


class ResourceAcquisitionError(ResourceError):
    """获取资源（如信号量、锁）失败时抛出。"""
    def __init__(self, message: str, resource_type: str, operation: str, cause: Optional[Exception] = None):
        details = {'resource_type': resource_type, 'operation': operation}
        super().__init__(message, details, cause)


# --- 其他错误 ---

class TimeoutError(AuraException):
    """当某个操作因超时而失败时抛出。"""
    pass


# --- 异常工厂函数 (为了兼容旧代码) ---

def create_plugin_error(message: str, plugin_name: Optional[str] = None, cause: Optional[Exception] = None) -> ConfigurationError:
    """创建一个插件相关的配置错误。"""
    return ConfigurationError(message, {'plugin_name': plugin_name}, cause)


def create_task_error(message: str, task_id: Optional[str] = None, cause: Optional[Exception] = None) -> TaskExecutionError:
    """创建一个任务执行错误。"""
    return TaskExecutionError(message, task_id=task_id, cause=cause)


def resource_unavailable(resource_type: str, cause: Optional[Exception] = None) -> ResourceError:
    """创建一个资源不可用的错误。"""
    return ResourceError(f"Resource of type '{resource_type}' is unavailable.", cause=cause)


def step_failed(step_id: str, reason: str, cause: Optional[Exception] = None) -> ActionExecutionError:
    """创建一个步骤（节点）失败的错误。"""
    return ActionExecutionError(f"Step '{step_id}' failed: {reason}", action_name=step_id, cause=cause)


def action_failed(action_name: str, reason: str, cause: Optional[Exception] = None) -> ActionExecutionError:
    """创建一个行为（Action）失败的错误。"""
    return ActionExecutionError(f"Action '{action_name}' failed: {reason}", action_name=action_name, cause=cause)


def create_jump_signal(type: str, target: str, cause: Optional[Exception] = None) -> JumpSignal:
    """创建一个跳转信号异常。"""
    return JumpSignal(type, target, cause)


def create_stop_task(message: str, success: bool = True, cause: Optional[Exception] = None) -> StopTaskException:
    """创建一个停止任务的异常信号。"""
    return StopTaskException(message, success=success, cause=cause)