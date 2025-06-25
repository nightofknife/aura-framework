# packages/aura_core/context.py (已修正并增加子上下文标志)

from typing import Dict, Any, Optional

from packages.aura_core.event_bus import Event

class Context:
    def __init__(
        self,
        initial_data: Dict[str, Any] = None,
        is_sub_context: bool = False,
        # 【新】 增加一个参数来接收触发事件
        triggering_event: Optional[Event] = None
    ):
        """
        初始化上下文。
        :param initial_data: (可选) 初始数据字典。
        :param is_sub_context: (内部使用) 标记这是否是一个子上下文。
        """
        self._data: Dict[str, Any] = {}
        if initial_data:
            self._data.update({k.lower(): v for k, v in initial_data.items()})

        # 【新功能】增加内部标志
        self._is_sub_context = is_sub_context
        self._triggering_event = triggering_event


    def set(self, key: str, value: Any):
        self._data[key.lower()] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key.lower(), default)

    def delete(self, key: str):
        self._data.pop(key.lower(), None)

    # 【新功能】提供一个公共方法来检查状态
    def is_sub_context(self) -> bool:
        """检查这是否是一个子上下文。"""
        return self._is_sub_context

    def get_triggering_event(self) -> Optional[Event]:
        """获取触发此上下文创建的事件。"""
        return self._triggering_event

    # 【修改】fork 方法现在会正确地创建子上下文
    def fork(self) -> 'Context':
        """
        创建一个新的、变量隔离的子上下文。
        它不会继承父上下文的任何变量，并被自动标记为子上下文。
        """
        return Context(is_sub_context=True, triggering_event=self._triggering_event)


    def __str__(self):
        trigger_id = self._triggering_event.id if self._triggering_event else None
        return f"Context(keys={list(self._data.keys())}, sub={self._is_sub_context}, trigger={trigger_id})"
