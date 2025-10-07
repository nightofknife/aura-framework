"""
为 `resolvelib` 库提供一个适配器（Provider）。

这个模块定义了 `PluginProvider` 类，它实现了 `resolvelib` 的 `AbstractProvider`
接口。这使得 `resolvelib` 能够理解 Aura 的插件生态系统，并能够基于
`plugin.yaml` 文件中定义的依赖关系来解析和验证插件的依赖图。
这个适配器是 `PluginManager` 能够进行健壮的依赖解析和拓扑排序的关键。
"""
from typing import Dict, Any, List

from resolvelib.providers import AbstractProvider

from packages.aura_core.plugin_definition import PluginDefinition


class PluginProvider(AbstractProvider):
    """
    为 `resolvelib` 库提供插件信息的适配器类。

    它实现了 `AbstractProvider` 接口，将 Aura 插件的概念映射到 `resolvelib`
    可以理解的需求（Requirement）和候选者（Candidate）模型上。
    """

    def __init__(self, plugin_registry: Dict[str, PluginDefinition]):
        """
        初始化插件提供者。

        Args:
            plugin_registry (Dict[str, PluginDefinition]): 一个从插件ID映射到
                其 `PluginDefinition` 对象的字典。这是所有插件信息的来源。
        """
        self.plugin_registry = plugin_registry

    def identify(self, requirement_or_candidate: Any) -> str:
        """
        返回一个需求或候选者的唯一标识符。

        在 Aura 的场景中，我们直接使用插件的规范ID (`author/name`) 作为标识符。

        Args:
            requirement_or_candidate (Any): 在这里通常是插件的规范ID字符串。

        Returns:
            str: 对象的唯一标识符。
        """
        return requirement_or_candidate

    def get_preference(
            self,
            identifier: Any,
            resolutions: Dict[str, Any],
            candidates: Dict[str, Any],
            information: Dict[str, Any],
            backtrack_causes: List[Any],
    ) -> int:
        """
        确定在解决依赖冲突时的偏好。

        由于 Aura 的插件版本管理相对简单（不处理复杂的版本范围），我们
        在这里使用一个简单的策略：返回候选者的数量。这在我们的用例中已足够。

        Returns:
            int: 偏好值。
        """
        return len(candidates)

    def find_matches(
            self,
            identifier: Any,
            requirements: Dict[str, Any],
            incompatibilities: Dict[str, Any]
    ) -> List[Any]:
        """
        根据给定的标识符查找匹配的候选者。

        在 Aura 中，一个插件ID只对应一个版本（即在代码库中的那个版本），
        所以如果插件存在于注册表中，我们就返回它自己作为唯一的候选者。

        Args:
            identifier (Any): 要查找的插件的ID。
            requirements (Dict[str, Any]): 对此标识符的要求。
            incompatibilities (Dict[str, Any]): 与此标识符不兼容的项。

        Returns:
            List[Any]: 匹配的候选者列表。如果找到，则列表包含插件ID；否则为空列表。
        """
        if identifier in self.plugin_registry:
            return [identifier]
        return []

    def is_satisfied_by(self, requirement: Any, candidate: Any) -> bool:
        """
        检查一个候选者是否满足一个需求。

        在我们的场景中，需求和候选者都是插件ID，因此当它们相同时即为满足。

        Args:
            requirement (Any): 需求（插件ID）。
            candidate (Any): 候选者（插件ID）。

        Returns:
            bool: 如果候选者满足需求，则为 True。
        """
        return requirement == candidate

    def get_dependencies(self, candidate: Any) -> List[str]:
        """
        获取一个候选者（插件）的依赖列表。

        此方法会从 `plugin_registry` 中查找插件的定义，并返回其
        `dependencies` 字段中声明的所有其他插件的ID列表。

        Args:
            candidate (Any): 候选者（插件ID）。

        Returns:
            List[str]: 该插件所依赖的其他插件的ID列表。
        """
        plugin_def = self.plugin_registry.get(candidate)
        if plugin_def:
            # 返回依赖字典的键，即所有依赖的插件ID
            return list(plugin_def.dependencies.keys())
        return []
