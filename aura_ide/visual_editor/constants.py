"""
为可视化编辑器定义了所有常量。

这些常量用于确保在图形编辑器、节点类和序列化/反序列化逻辑之间
使用一致的标识符和属性名称。

主要包括：
- 节点类型标识符 (NODE_TYPE_*)：用于在 NodeGraphQt 框架中注册不同类型的自定义节点。
- 自定义属性名称 (PROP_*)：用于在节点对象上存储特定于Aura的数据，如节点ID、行为ID和参数。
"""
# Node type identifiers used in NodeGraphQt registration
NODE_TYPE_ACTION = 'aura.ActionNode'
NODE_TYPE_LOGIC_GATE = 'aura.LogicGateNode'
NODE_TYPE_COMMENT = 'aura.CommentNode'

# Custom property names
PROP_NODE_ID = 'node_id'
PROP_ACTION_ID = 'action_id'
PROP_PARAMS = 'params'
PROP_LOGIC_TYPE = 'type'
PROP_TEXT = 'text'