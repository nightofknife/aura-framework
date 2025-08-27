# 建议放在 src/core/pathfinder.py, 然后在 main.py 中导入
# from src.core.pathfinder import Pathfinder
# 或者为了简单，直接定义在 main.py 的 Orchestrator 类上面

from collections import deque


class Pathfinder:
    def __init__(self, world_map: dict):
        """
        初始化寻路器。
        :param world_map: 从 world_map.yaml 加载的字典。
        """
        self.graph = {}
        # 将 world_map 中的 transitions 转换成邻接表，方便查找
        # self.graph 的格式: { 'state_A': ['state_B', 'state_C'], ... }
        for transition in world_map.get('transitions', []):
            from_node = transition['from']
            to_node = transition['to']
            if from_node not in self.graph:
                self.graph[from_node] = []
            self.graph[from_node].append(to_node)

    def find_path(self, start_node: str, end_node: str) -> list[str] | None:
        """
        使用广度优先搜索 (BFS) 查找从起点到终点的最短路径。
        """
        if start_node == end_node:
            return [start_node]

        if start_node not in self.graph:
            return None  # 起点不存在于任何转换中

        queue = deque([(start_node, [start_node])])  # 队列项: (当前节点, 到达此节点的路径)
        visited = {start_node}

        while queue:
            current_node, path = queue.popleft()

            for neighbor in self.graph.get(current_node, []):
                if neighbor == end_node:
                    return path + [neighbor]  # 找到路径，返回

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None  # 队列为空，说明无法到达终点
