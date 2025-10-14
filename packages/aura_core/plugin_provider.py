# -*- coding: utf-8 -*-
"""为 `resolvelib` 库提供插件信息的适配器。

此模块中的 `PluginProvider` 类实现了 `resolvelib.AbstractProvider` 接口。
它的作用是充当 Aura 的插件系统与 `resolvelib` 依赖解析算法之间的桥梁。
通过实现这个接口中的方法，我们告诉 `resolvelib` 如何从我们的
`plugin_registry` 中识别插件、查找它们的依赖关系以及如何处理版本匹配
（尽管在当前实现中，版本匹配被简化了）。
"""
from typing import Dict, Any, List

from resolvelib.providers import AbstractProvider

from packages.aura_core.plugin_definition import PluginDefinition


class PluginProvider(AbstractProvider):
    """为 `resolvelib` 库提供插件信息的适配器类。

    这个类让 `resolvelib` 能够理解 Aura 的插件生态系统，从而能够
    验证依赖关系并帮助进行拓扑排序。
    """

    def __init__(self, plugin_registry: Dict[str, PluginDefinition]):
        """初始化 PluginProvider。

        Args:
            plugin_registry: 一个包含了所有已发现插件定义的字典，
                键为插件的规范ID，值为 `PluginDefinition` 对象。
        """
        self.plugin_registry = plugin_registry

    def identify(self, requirement_or_candidate: Any) -> Any:
        """返回一个需求或候选者的唯一标识符。

        在我们的场景中，插件的规范ID（字符串）本身就是其唯一标识符。
        """
        return requirement_or_candidate

    def get_preference(
            self,
            identifier: Any,
            resolutions: Dict[str, Any],
            candidates: Dict[str, Any],
            information: Dict[str, Any],
            backtrack_causes: List[Any],
    ) -> Any:
        """在解决依赖冲突时确定偏好。

        此方法影响解析器在有多个选择时的决策顺序。在当前简化模型中，
        我们没有复杂的版本偏好，因此只返回一个基于候选者数量的简单值。
        """
        return len(candidates)

    def find_matches(self, identifier: Any, requirements: Any, incompatibilities: Any) -> List[Any]:
        """查找与给定标识符（和需求）匹配的候选者。

        在 Aura 的插件模型中，一个插件标识符只对应一个确切的插件实例，
        所以我们只需检查该标识符是否存在于我们的注册表中。
        """
        if identifier in self.plugin_registry:
            return [identifier]
        return []

    def is_satisfied_by(self, requirement: Any, candidate: Any) -> bool:
        """检查一个候选者是否满足一个需求。

        由于我们的依赖关系是基于插件的规范ID，如果需求和候选者的ID相同，
        我们就认为它得到了满足。
        """
        return requirement == candidate

    def get_dependencies(self, candidate: Any) -> List[Any]:
        """获取一个候选者（插件）的依赖列表。

        此方法会从 `plugin_registry` 中查找候选插件的定义，并返回其
        `dependencies` 字段中声明的所有依赖项的列表。
        """
        plugin_def = self.plugin_registry.get(candidate)
        if plugin_def:
            # resolvelib 需要的是依赖的标识符列表
            return list(plugin_def.dependencies.keys())
        return []
