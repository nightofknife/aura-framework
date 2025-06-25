# packages/aura_core/inheritance_proxy.py

class InheritanceProxy:
    """
    一个动态代理类，用于无缝地结合父服务和子服务。
    它优先调用子服务的方法，如果子服务没有该方法，则转发给父服务。
    """

    def __init__(self, parent_service: object, child_service: object):
        self._parent_service = parent_service
        self._child_service = child_service

    def __getattr__(self, name: str):
        # 优先从子服务获取属性或方法
        if hasattr(self._child_service, name):
            return getattr(self._child_service, name)

        # 如果子服务没有，则从父服务获取
        if hasattr(self._parent_service, name):
            return getattr(self._parent_service, name)

        # 如果都找不到，则抛出标准的 AttributeError
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

