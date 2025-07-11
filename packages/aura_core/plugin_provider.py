# packages/aura_core/plugin_provider.py (全新文件)

from typing import Dict, Any, List

from resolvelib.providers import AbstractProvider

from packages.aura_shared_utils.models.plugin_definition import PluginDefinition


class PluginProvider(AbstractProvider):
    """
    为 resolvelib 库提供插件信息的适配器类。
    它告诉 resolvelib 如何识别插件、查找它们的依赖关系等。
    """

    def __init__(self, plugin_registry: Dict[str, PluginDefinition]):
        self.plugin_registry = plugin_registry

    def identify(self, requirement_or_candidate):
        """返回一个对象的唯一标识符。"""
        return requirement_or_candidate

    def get_preference(
            self,
            identifier: Any,
            resolutions: Dict[str, Any],
            candidates: Dict[str, Any],
            information: Dict[str, Any],
            backtrack_causes: List[Any],
    ) -> Any:
        """确定解决冲突时的偏好。我们简单地返回候选者的数量。"""
        return len(candidates)

    def find_matches(self, identifier, requirements, incompatibilities):
        """查找与给定标识符匹配的候选者。"""
        if identifier in self.plugin_registry:
            return [identifier]
        return []

    def is_satisfied_by(self, requirement, candidate):
        """检查一个候选者是否满足一个需求。在我们的场景中，它们是相同的。"""
        return requirement == candidate

    def get_dependencies(self, candidate):
        """获取一个候选者的依赖列表。"""
        plugin_def = self.plugin_registry.get(candidate)
        if plugin_def:
            return list(plugin_def.dependencies.keys())
        return []
