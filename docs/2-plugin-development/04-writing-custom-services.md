# 4. 编写自定义 Services

当你的 Action 需要管理状态、处理复杂的生命周期或与外部系统进行持续交互时，就需要引入 Service 的概念。Service 是可复用的、通常有状态的组件，通过依赖注入提供给 Action 使用。

## 1. 为什么需要 Service？

*   **状态管理**: Actions 被设计为无状态的。如果你需要跨多个 Action 调用来维持一个状态（例如，一个数据库连接池、一个 websocket 连接），Service 是理想的实现方式。
*   **封装复杂逻辑**: Service 可以封装与第三方库或外部 API 交互的复杂逻辑，让 Action 的代码保持简洁，专注于业务流程。
*   **生命周期管理**: Aura 可以管理 Service 的生命周期，例如在框架启动时初始化 Service，在关闭时优雅地释放资源。
*   **可复用性**: 一个 Service 可以被同一个 Plan 下的多个 Action 共享，也可以被其他 Plan 使用。

## 2. 创建一个 Service

一个 Service 本质上是一个普通的 Python 类。按照惯例，你应该将 Service 类放在你的 Plan 的 `services/` 目录下。

**示例：创建一个数据库 Service**

假设我们正在创建一个 `database` Plan，需要一个 `DatabaseService` 来管理数据库连接。

**文件路径:** `plans/database/services/db_service.py`
```python
import logging

logger = logging.getLogger(__name__)

class DatabaseService:
    def __init__(self):
        self._connection = None
        logger.info("DatabaseService is being initialized.")
        # 在实际应用中，这里可能不会立即连接，而是在第一次使用时
        # self.connect()

    def connect(self, db_url: str):
        """连接到数据库"""
        logger.info(f"Connecting to database at {db_url}...")
        # 实际的数据库连接逻辑
        self._connection = "DUMMY_CONNECTION_OBJECT"
        logger.info("Database connection established.")

    def disconnect(self):
        """断开数据库连接"""
        logger.info("Disconnecting from database...")
        self._connection = None
        logger.info("Database connection closed.")

    def query(self, sql: str) -> list:
        """执行一个只读查询"""
        if not self._connection:
            raise ConnectionError("Database is not connected.")
        logger.info(f"Executing query: {sql}")
        return [{"id": 1, "name": "Aura"}] # 返回模拟数据
```

## 3. 注册 Service

创建了 Service 类之后，你需要告诉 Aura 它的存在。这是通过在 Plan 的根目录下的 `__init__.py` 文件中，使用 `service_registry` 来完成的。

**文件路径:** `plans/database/__init__.py`
```python
from aura_core.service_registry import service_registry
from .services.db_service import DatabaseService

# 注册 DatabaseService
# 第一个参数是 Service 的唯一名称，其他 Plan 可以通过这个名称来引用它
# 第二个参数是 Service 类本身
service_registry.register("db_service", DatabaseService)
```
当 Aura 加载 `database` Plan 时，它会执行这个 `__init__.py` 文件，从而将 `DatabaseService` 的实例注册到全局的服务注册表中。

## 4. 在 Action 中使用 Service (依赖注入)

一旦 Service被注册，你就可以在任何 Action 中通过依赖注入来使用它。你只需要在 Action 函数的参数中，使用与注册时相同的名称 (`db_service`) 和正确的类作为类型提示，Aura 会自动将 Service 实例传入。

**文件路径:** `plans/database/actions/db_actions.py`
```python
from .services.db_service import DatabaseService # 导入 Service 类用于类型提示
from aura_core.actions import action

@action
def get_user_from_db(user_id: int, db_service: DatabaseService) -> dict:
    """
    从数据库中查询用户信息。

    :param user_id: 要查询的用户 ID。
    :param db_service: 由框架自动注入的 DatabaseService 实例。
    :return: 用户信息的字典。
    """
    # 在实际应用中，连接可能在服务启动时就已建立
    db_service.connect("postgresql://user:pass@host:port/db")

    user_data = db_service.query(f"SELECT * FROM users WHERE id = {user_id}")

    db_service.disconnect()

    if user_data:
        return user_data[0]
    return None
```
### 工作原理：

当 `database.get_user_from_db` Action 被调用时，Aura 的执行引擎会检查它的参数列表。当它看到一个名为 `db_service` 且类型为 `DatabaseService` 的参数时，它会自动从 `service_registry` 中查找名为 `db_service` 的服务实例，并将其作为参数传递给该函数。

这种依赖注入的模式，极大地简化了 Action 的编写，并促进了代码的解耦和可测试性。
