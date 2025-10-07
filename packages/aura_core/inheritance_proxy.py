# packages/aura_core/inheritance_proxy.py
"""
定义了 `InheritanceProxy` 类，用于实现服务（Service）的继承和扩展。

该模块提供了一个代理模式的实现，允许一个“子服务”无缝地覆盖或扩展一个“父服务”的功能。
当一个服务被声明为另一个服务的扩展时，`ServiceRegistry` 会创建这个代理对象，
将父服务和子服务的实例包装起来。所有对该服务的调用都会通过这个代理进行，
从而实现了优先调用子服务实现、若子服务未实现则回退到父服务实现的效果。
"""
from typing import Any

class InheritanceProxy:
    """
    一个动态代理类，用于无缝地结合父服务和子服务，实现继承效果。

    它通过重写 `__getattr__` 方法，实现了一个属性查找链：
    1. 优先在子服务中查找属性（方法或成员变量）。
    2. 如果在子服务中找不到，则在父服务中查找。
    3. 如果都找不到，则抛出 `AttributeError`。

    这使得子服务可以只实现它需要覆盖或新增的方法，而所有未被覆盖的方法
    都会被自动委托给父服务，从而模拟了类的继承行为。
    """

    def __init__(self, parent_service: object, child_service: object):
        """
        初始化继承代理。

        Args:
            parent_service (object): 父服务的实例。
            child_service (object): 子服务的实例，它扩展了父服务。
        """
        self._parent_service = parent_service
        self._child_service = child_service

    def __getattr__(self, name: str) -> Any:
        """
        动态获取属性。

        这是代理模式的核心。当访问代理对象的属性时，此方法会被调用。

        Args:
            name (str): 被访问的属性的名称。

        Returns:
            Any: 从子服务或父服务中找到的属性值。

        Raises:
            AttributeError: 如果在子服务和父服务中都找不到该属性。
        """
        # 优先从子服务获取属性或方法
        if hasattr(self._child_service, name):
            return getattr(self._child_service, name)

        # 如果子服务没有，则从父服务获取
        if hasattr(self._parent_service, name):
            return getattr(self._parent_service, name)

        # 如果都找不到，则抛出标准的 AttributeError
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
