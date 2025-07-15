#### **12. 创建你自己的 Service**


# **开发者指南：创建你自己的 Service**

服务 (Service) 是 Aura 框架中封装可复用后端逻辑的核心单元，是 Action 背后的“大脑”。当您的自动化需求变得复杂，需要在多个 Action 之间共享状态、配置或复杂的逻辑时，就应该考虑创建自己的服务了。

### **何时创建服务？**

1.  **逻辑复用**: 您有一套复杂的逻辑（例如，与特定数据库的交互），希望在多个 Action 中都能调用。
2.  **状态管理**: 您需要维护一个有状态的对象（例如，一个持续的网络连接，一个加载好的大型数据模型），并在任务执行期间共享它。
3.  **能力封装**: 您希望为 Aura 集成一个全新的核心能力（例如，集成一个新的网页自动化库如 Selenium/Playwright）。

### **服务的基本结构**

创建一个服务，本质上是创建一个 Python 类，并用 `@register_service` 装饰器来标记它。

1.  **选择位置**: 与 Action 类似，您可以在插件中创建一个 `services.py` 文件。例如：`plans/MyDbPlugin/services.py`。

2.  **编写代码**: 让我们创建一个简单的服务，用于管理一个模拟的数据库连接。
    ```python
    # plans/MyDbPlugin/services.py

    from packages.aura_core.api import register_service

    @register_service(alias="db_connector", public=True)
    class MyDbService:
        def __init__(self):
            """
            服务的构造函数。在服务第一次被请求时调用。
            非常适合执行一次性的初始化操作。
            """
            self._connection = None
            self._connect()

        def _connect(self):
            print("正在连接到模拟数据库...")
            # 模拟一个耗时的连接过程
            import time; time.sleep(1)
            self._connection = "ACTIVE_CONNECTION"
            print("数据库连接成功！")

        def query(self, sql: str) -> list:
            """
            执行一个查询并返回结果。
            """
            if self._connection != "ACTIVE_CONNECTION":
                raise ConnectionError("数据库未连接。")
            print(f"执行查询: {sql}")
            # 模拟返回数据
            return [{"id": 1, "name": "Aura"}]

        def close(self):
            print("正在关闭数据库连接...")
            self._connection = None
    ```

### **剖析一个服务**

#### **1. 装饰器: `@register_service`**
*   **`alias` (必需)**: `str` - 服务的**短别名**。这个别名在整个 Aura 环境中应该是唯一的，它是在 Action 或其他服务中请求此服务时的主要标识符。
*   **`public` (可选, 默认 `False`)**: `bool` - 是否在 UI 等外部工具中可见。

#### **2. 服务的 FQID (完全限定ID)**
Aura 内部会为每个服务分配一个全局唯一的 FQID，格式为 `{插件的规范ID}/{服务别名}`。例如，上面例子的 FQID 就是 `MyDbPlugin/db_connector`。这保证了即使不同插件使用了相同的服务别名，内部也不会冲突。

#### **3. 服务的生命周期**
*   **懒加载 (Lazy Loading)**: 服务不是在 Aura 启动时就创建的，而是在**第一次被请求时**才会被实例化（即调用 `__init__` 方法）。
*   **单例 (Singleton)**: 在一次 Aura 运行期间，每个服务只会被实例化一次。所有请求该服务的地方（无论是哪个 Action 或其他服务）得到的都是**同一个实例**。这使得在服务中保存状态（如数据库连接）成为可能。

### **在 Action 中使用自定义服务**

现在，您可以创建一个 Action 来使用我们刚刚定义的 `MyDbService`。

```python
# plans/MyDbPlugin/actions.py

from packages.aura_core.api import register_action, requires_services
from .services import MyDbService # 从同一插件中导入服务类

@register_action(name="query_db")
@requires_services(db='db_connector') # 使用服务的 alias 请求依赖
def query_database(db: MyDbService, query_string: str) -> list:
    """
    使用 MyDbService 来查询数据库。
    """
    # Aura 会自动将 MyDbService 的单例对象注入到 'db' 参数中
    results = db.query(query_string)
    return results
```
当这个 Action 第一次被调用时，Aura 的服务注册中心会发现它需要一个别名为 `db_connector` 的服务。如果该服务尚未实例化，它就会创建 `MyDbService` 的一个实例（此时会打印“正在连接...”），然后将其注入到 `query_database` 函数的 `db` 参数中。后续任何其他 Action 再请求 `db_connector` 服务时，都会得到同一个已经建立好连接的实例。

通过这种方式，您可以构建出层次分明、高内聚、低耦合的强大自动化插件。

---
