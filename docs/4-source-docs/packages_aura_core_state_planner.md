# 文件: `packages/aura_core/state_planner.py`

## 1. 核心目的

该文件的核心职责是提供一个**智能状态规划器（State Planner）**。对于那些复杂的、基于状态的自动化方案（Plan），`StatePlanner` 扮演着“导航员”的角色。它的主要任务有两个：

1.  **状态确定**：在执行任何任务之前，通过一系列检查（`check_task`）来准确、高效地判断系统当前处于哪个预定义的状态。
2.  **路径规划**：一旦确定了当前状态，如果它不是期望的目标状态，`StatePlanner` 能够根据预设的转移路径（`transitions`）和成本（`cost`），计算出从当前状态到达目标状态的**成本最低的执行路径**。

它将一个声明式的状态地图（`states_map.yaml`）转化为可执行的、智能的决策逻辑，是 Aura 框架实现高级自动化（例如，从任意界面返回到应用主页）的关键组件。

## 2. 关键类与函数

*   **`StateMap` (Class)**:
    *   **作用**: 一个简单的数据容器类，用于封装从 `states_map.yaml` 文件中解析出的 `states`（状态定义）和 `transitions`（转移规则）数据。它的存在使得代码结构更清晰，类型提示更友好。

*   **`StatePlanner` (Class)**:
    *   **作用**: 状态规划器的主要实现。它包含了状态图的构建、当前状态的判定、以及最优路径的搜索等所有核心功能。
    *   **`orchestrator` (Attribute)**: 一个 `Orchestrator` 实例。`StatePlanner` 自身不执行任何任务，而是**委托** `orchestrator` 来运行所有的 `check_task` 和 `transition_task`。
    *   **`graph` / `_reverse_graph` (Attributes)**: 在初始化时，`StatePlanner` 会将 `transitions` 列表预处理成一个**邻接表**表示的图（`graph`），以及一个反向图（`_reverse_graph`）。这种预处理极大地提高了后续路径规划（Dijkstra）和距离计算（BFS）的效率。

    *   **`determine_current_state(target_state)`**:
        *   **作用**: 这是该类中最智能、最核心的方法之一。它并非简单地轮询所有状态，而是通过一种高度优化的策略来确定当前状态。

    *   **`find_path(start_node, end_node)`**:
        *   **作用**: 使用经典的 **Dijkstra 算法**在预处理好的 `graph` 上寻找从起点到终点的最低成本路径。它返回的是一个由 `transition_task` 名称组成的列表。

    *   **`verify_state_with_retry(state_name, ...)`**:
        *   **作用**: 一个健壮的辅助函数，用于在执行一次状态转移后，带**重试机制**地确认系统是否真的进入了预期的下一个状态。这对于处理 UI 延迟或不稳定的情况至关重要。

## 3. 核心逻辑解析

`StatePlanner.determine_current_state` 方法的实现是该模块的精髓所在，它完美地展示了如何将图论算法应用到自动化流程中以实现效率优化。其核心逻辑可以分解为以下几个步骤：

1.  **预计算距离（智能排序的基础）**:
    *   `distances = self._calculate_distances_to_target(target_state)`: 在开始任何检查之前，它首先调用 `_calculate_distances_to_target`。这个内部方法利用**广度优先搜索（BFS）**算法在一个**反向图**（`_reverse_graph`）上，计算出图中所有状态距离目标状态（`target_state`）的**最短步数**（注意：这里不是成本，而是转移次数）。
    *   **为什么这样做?** 这步预计算为后续的检查顺序提供了关键的决策依据。直观上，一个离目标状态“更近”的状态，更有可能是我们当前所处的状态，或者我们应该优先检查它。

2.  **构建并排序检查列表**:
    *   它创建一个 `check_list`，其中包含所有定义了 `check_task` 的状态。
    *   `check_list.sort(key=lambda x: (x['distance'], x['priority']))`: 这是整个优化的核心。它对检查列表进行**多级排序**：
        *   **第一优先级**: 按刚刚计算出的 `distance` **升序**排序。离目标最近的状态会被排在最前面。
        *   **第二优先级**: 按状态定义中的 `priority` **升序**排序。距离相同时，优先级更高（数值更小）的状态会被排在前面。

3.  **分阶段执行检查**:
    *   **阶段一：并行检查 (Parallel Checks)**:
        *   规划器首先筛选出所有在 `states_map.yaml` 中被标记为 `can_async: true` 的检查任务。
        *   它使用 `asyncio.create_task` 将这些任务**同时启动**，然后通过 `asyncio.wait` 并设置 `return_when=asyncio.FIRST_COMPLETED` 来等待结果。
        *   **这意味着**：只要这些并行的检查中**有任何一个**率先成功返回 `True`，规划器就立即确认了当前状态，然后会**取消所有其他仍在运行的检查任务**，并直接返回结果。这是一个“赛马机制”，极大地缩短了在多个可能状态之间进行检查所需的时间。

    *   **阶段二：串行检查 (Sequential Checks)**:
        *   如果在并行阶段没有找到当前状态（或者没有可并行的任务），规划器会接着处理那些必须串行执行的检查（`can_async: false`）。
        *   它会严格按照之前排序好的顺序，**一个接一个地**执行这些检查任务。
        *   一旦某个检查成功，它会立即停止后续的检查并返回结果。

通过这个“预计算距离 -> 智能排序 -> 并行优先 -> 串行保底”的策略，`determine_current_state` 能够以远高于朴素轮询的效率，精准地定位系统当前的状态，为后续的路径规划和任务执行打下坚实的基础。