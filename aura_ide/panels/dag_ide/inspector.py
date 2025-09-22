# inspector.py (基于您的inspector_panel.py扩展)
from PySide6.QtWidgets import QGroupBox, QFormLayout, QLineEdit, QTextEdit, QComboBox, QTabWidget, QPushButton

class DagInspector(QWidget):
    node_changed = Signal(str, Dict[str, Any])  # node_id, updated_props

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_node: Optional[AuraNodeItem] = None
        self.tabs = QTabWidget()
        self.basic_tab = self._create_basic_tab()
        self.logic_tab = self._create_logic_tab()
        self.params_tab = self._create_params_tab()
        self.when_tab = self._create_when_tab()
        self.tabs.addTab(self.basic_tab, "基本")
        self.tabs.addTab(self.params_tab, "参数")
        self.tabs.addTab(self.logic_tab, "依赖逻辑")
        self.tabs.addTab(self.when_tab, "条件")
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)

    def _create_basic_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.id_label = QLabel("")  # 只读
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_change)
        self.desc_edit = QTextEdit()
        self.desc_edit.textChanged.connect(self._on_change)
        form.addRow("ID:", self.id_label)
        form.addRow("名称:", self.name_edit)
        form.addRow("描述:", self.desc_edit)
        return widget

    def _create_params_tab(self) -> QWidget:
        widget = QWidget()
        self.params_form = QFormLayout(widget)
        self.validate_btn = QPushButton("验证参数")
        self.validate_btn.clicked.connect(self._validate_params)
        layout = QVBoxLayout(widget)
        layout.addLayout(self.params_form)
        layout.addWidget(self.validate_btn)
        return widget

    def _create_logic_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.expr_edit = QLineEdit()  # 表达式模式
        self.expr_edit.textChanged.connect(self._on_change)
        self.add_gate_btn = QPushButton("添加AND/OR Gate")
        self.add_gate_btn.clicked.connect(self._add_logic_node)
        logic_tree = QTreeWidget()  # 树状查看当前逻辑
        logic_tree.setHeaderLabels(["逻辑树"])
        layout.addWidget(QLabel("表达式编辑 (e.g., A and (B or not C)):"))
        layout.addWidget(self.expr_edit)
        layout.addWidget(self.add_gate_btn)
        layout.addWidget(logic_tree)
        return widget

    def _create_when_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.when_edit = QLineEdit()  # Jinja when
        self.when_edit.textChanged.connect(self._on_change)
        self.test_btn = QPushButton("测试条件")
        self.test_btn.clicked.connect(self._test_when)
        form.addRow("When表达式:", self.when_edit)
        form.addRow(self.test_btn)
        return widget

    def load_node(self, node: AuraNodeItem):
        self.current_node = node
        self.id_label.setText(node.node_id)
        self.name_edit.setText(node.name or "")
        self.desc_edit.setText(node.desc or "")
        self.params = node.params.copy()
        self._update_params_form()
        self.expr_edit.setText(node.depends_expr or "")  # 复杂逻辑表达式
        self.when_edit.setText(node.when_expr or "")

    def _on_change(self):
        if self.current_node:
            self.current_node.name = self.name_edit.text()
            self.current_node.desc = self.desc_edit.toPlainText()
            self.current_node.params = self.params
            self.current_node.depends_expr = self.expr_edit.text()
            self.current_node.when_expr = self.when_edit.text()
            self.node_changed.emit(self.current_node.node_id, {'name': self.current_node.name, ...})  # 更新

    def _update_params_form(self):
        # 清空 + 动态基于action_def
        while self.params_form.count():
            self.params_form.takeAt(0)
        if self.current_node.action_def:
            for param_name, param in self.current_node.action_def.signature.parameters.items():
                if param_name in ['self', 'context']: continue
                edit = QLineEdit(str(self.params.get(param_name, '')))
                edit.textChanged.connect(lambda t, n=param_name: self.params.update({n: t}))
                self.params_form.addRow(param_name, edit)

    def _validate_params(self):
        # bridge.perform_condition_check
        result = self.bridge.perform_condition_check({'action': self.current_node.action_def.name, 'params': self.params})
        if result:
            QMessageBox.information(self, "验证通过", "参数有效")
        else:
            QMessageBox.warning(self, "验证失败", "参数无效")

    def _add_logic_node(self):
        # 弹出选择AND/OR, 然后在graph添加LogicNode, 连到current_node
        logic_type, ok = QInputDialog.getItem(self, "添加逻辑门", "类型:", ["AND", "OR", "NOT"], 0, False)
        if ok:
            # graph.create_logic_node(logic_type, pos=near current_node)
            # 自动连线: new_gate.output -> current_node.input
            pass

    def _test_when(self):
        # bridge.perform_condition_check({'action': 'eval', 'params': {'expr': self.when_edit.text()}})
        pass