


### **第五部分：开发者指南 (Developer Guide) **

---

#### **11. 创建你自己的 Action**


# **开发者指南：创建你自己的 Action**

Aura 强大的核心在于其开放的 Action 系统。如果您发现内置的 Action 无法满足您的特定需求（例如，您需要与一个特殊的内部 API 对话，或者操作一个非标准的桌面软件），您可以轻松地使用 Python 编写自己的 Action。

创建一个新的 Action 本质上就是编写一个 Python 函数，并用一个特殊的装饰器 `@register_action` 来“告诉”Aura 它的存在。

### **Action 的基本结构**

让我们来创建一个简单的 Action，它的功能是计算两个数的和。

1.  **选择位置**: 在您的方案包（现在可以称之为“插件”）中，可以创建一个名为 `actions.py` 的文件来存放自定义 Action。例如：`plans/MyMathPlugin/actions.py`。Aura 会自动发现并加载这些文件。

2.  **编写代码**:
    ```python
    # plans/MyMathPlugin/actions.py

    from packages.aura_core.api import register_action

    @register_action(name="add", public=True)
    def add_numbers(num1: float, num2: float) -> float:
        """
        这个 Action 计算两个数字的和。
        它会在日志中打印计算过程，并返回结果。
        """
        print(f"正在计算 {num1} + {num2}")
        result = num1 + num2
        return result
    ```

### **剖析一个 Action**

#### **1. 装饰器: `@register_action`**
这是将一个普通 Python 函数转变为 Aura Action 的魔法。它接受几个参数：
*   **`name` (必需)**: `str` - Action 在**其所属插件内**的唯一名称。这个名称应该是简洁的、描述其功能的动词或动名词短语（例如 `add`, `get_user_data`）。
*   **`public` (可选, 默认 `False`)**: `bool` - 如果设置为 `True`，这个 Action 可能会在 UI 或其他外部工具中展示给用户。
*   **`read_only` (可选, 默认 `False`)**: `bool` - 一个提示性标志。如果您的 Action 不会改变系统或外部应用的状态（例如，只是读取数据或进行计算），可以将其设置为 `True`。

#### **2. Action 的命名与调用**

在 Aura 3.0 的插件体系中，Action 的调用变得更加规范。虽然你在注册时只提供了一个简单的 `name` (如 `add`)，但在 YAML 中，为了避免不同插件间的命名冲突，推荐使用**带有命名空间的 Action 名称**。

**命名空间规则**:
Aura 的核心 Action（如 `log`, `find_image`）属于 `core` 命名空间，可以直接使用。对于您在插件中自定义的 Action，其命名空间就是您的**插件名（方案文件夹名）**，但使用**点(`.`)**而不是斜杠(`/`)。

*   **插件名**: `MyMathPlugin`
*   **Action 注册名**: `add`
*   **在 YAML 中的调用名**: `mymathplugin.add`

```yaml
# plans/MyMathPlugin/tasks/main.yaml
steps:
  - name: "执行自定义加法"
    action: mymathplugin.add # 使用 <插件名>.<action名>
    params:
      num1: 10
      num2: 32
    output_to: "sum_result"
```
这种设计既保持了 Action 定义的简洁性，又保证了在大型项目中 Action 调用的清晰和无冲突。

#### **3. 函数签名与文档字符串**
*   **函数签名**: Action 函数的参数直接对应于 YAML 中 `params` 块里的键。强烈建议使用类型提示和默认值。
*   **文档字符串 (Docstring)**: 为您的 Action 编写清晰的文档字符串。Aura 框架可以提取这些信息，未来可能用于自动生成文档或在 UI 中提供帮助。

### **高级：注入服务和上下文**

您的 Action 通常需要与 Aura 的核心功能交互。Aura 通过**依赖注入**机制来实现这一点。您只需在函数签名中声明它们，Aura 就会在执行时自动将它们“注入”进来。

#### **注入 `Context`**
如果您需要直接读写当前任务的上下文，只需在参数中添加 `context: Context`。

#### **注入服务: `@requires_services`**
更常见的情况是，您需要使用 Aura 提供的核心服务。为此，您需要使用另一个装饰器 `@requires_services` 来声明您的依赖。

```python
# plans/MyMathPlugin/actions.py

from packages.aura_core.api import register_action, requires_services
# 导入您需要的服务类
from aura_official_packages.aura_base.services.app_provider_service import AppProviderService

@register_action(name="get_window_title")
@requires_services(app='Aura-Project/base/app') # 声明依赖
def get_window_title(app: AppProviderService) -> str:
    """
    获取当前活动窗口的标题。
    """
    # 'app' 参数会被自动注入 AppProviderService 的实例
    title = app.get_window_title()
    return title
```
**`@requires_services` 的用法**:
*   **`my_param_name='service_id'`**: 这种 `key=value` 的形式是最清晰的。`key` (`my_param_name`) 是你函数中接收服务实例的参数名，`value` (`service_id`) 是服务的**短别名** (如 `config`) 或**完全限定ID (FQID)** (如 `Aura-Project/base/app`)。
*   **`'service_id'`**: 这种直接写服务ID的形式是一种简写。框架会自动使用服务ID的最后一部分作为函数参数名。例如 `@requires_services('config')` 等同于 `@requires_services(config='config')`。

---


