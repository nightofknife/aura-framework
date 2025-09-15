# src/aura_ide/panels/ide_panel/completion_provider.py [V5 - Auto Params Logic]

import inspect
import re
from typing import List, Any, Dict, Tuple, Union

from PySide6.QtCore import QObject, Slot, Signal, QPoint, Qt
from PySide6.QtGui import QStandardItemModel, QStandardItem, QTextBlock
from PySide6.QtWidgets import QCompleter

from .editor_widget import EditorWidget
from .context_parser import ContextParser, get_indentation

CompletionItem = Union[str, Tuple[str, str]]
SNIPPETS = {
    "returns": ("returns", "returns:\n  result_name: \"{{ steps.$1.result }}\""),
    "on_failure": ("on_failure",
                   "on_failure:\n  do:\n    - action: log.error\n      params:\n        message: \"任务 {{ task.name }} 失败: {{ error }}\""),
    "steps": ("steps", "steps:\n  $1:\n    name: \"$2\"\n    action: $3"),
    "for_each": ("for_each",
                 "for_each:\n  in: \"{{ $1 }}\"\n  as: \"$2\"\n  do:\n    $3:\n      action: $4\n      params:\n        data: \"{{ $2 }}\""),
    "while": ("while", "while:\n  condition: \"{{ $1 }}\"\n  limit: 10\n  do:\n    $2:\n      action: $3"),
    "try": ("try",
            "try:\n  do:\n    $1:\n      action: $2\ncatch:\n  do:\n    handle_error:\n      action: log.warning\n      params:\n        message: \"操作失败: {{ error }}\"\nfinally:\n  do:\n    cleanup:\n      action: $3"),
    "depends_on": ("depends_on", "depends_on:\n  and:\n    - $1\n    - $2"),
}
TOP_LEVEL_KEYWORDS: List[CompletionItem] = ["execution_mode", "resource_tags", "timeout", "required_initial_state",
                                            "ensured_final_state", SNIPPETS["returns"], SNIPPETS["on_failure"],
                                            SNIPPETS["steps"]]
NODE_LEVEL_KEYWORDS: List[CompletionItem] = ["name", "when", SNIPPETS["depends_on"], "action", "do",
                                             SNIPPETS["for_each"], SNIPPETS["while"], SNIPPETS["try"], "switch",
                                             "params"]


class CompletionProvider(QObject):
    actionContextFound = Signal(object)
    noContextFound = Signal()
    SnippetRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, editor_widget: EditorWidget, parent=None):
        super().__init__(parent)
        # ... (内部变量无变化) ...
        self.editor_widget = editor_widget
        self._action_definitions: List[Any] = []
        self._action_map: Dict[str, Any] = {}
        self.context_parser = ContextParser()
        self.completer = QCompleter(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setWrapAround(False)
        self.model = QStandardItemModel(self)
        self.completer.setModel(self.model)
        self.editor_widget.set_completer(self.completer)
        self.completer.activated.connect(self._on_completion_activated)

    def update_action_definitions(self, definitions: List[Any]):
        self._action_definitions = definitions
        self._action_map = {d.name: d for d in definitions}

    @Slot(str, QPoint)
    def on_cursor_moved(self, line_text_stripped: str, global_pos: QPoint):
        # ... (此方法无变化) ...
        cursor = self.editor_widget.get_text_cursor()
        line_num = cursor.blockNumber() + 1
        col_num = cursor.positionInBlock() + 1
        full_text = self.editor_widget.get_content()
        context = self.context_parser.get_context_at_cursor(full_text, line_num, col_num)
        if not context:
            self.completer.popup().hide()
            self.noContextFound.emit()
            return
        key_path, current_word = context
        completion_items = self._get_completions_for_context(key_path)
        current_line_full = cursor.block().text().strip()
        if current_line_full.startswith("action:"):
            completion_items = [d.name for d in self._action_definitions]
            action_name = current_line_full.split(":")[-1].strip()
            if action_name in self._action_map:
                self.actionContextFound.emit(self._action_map[action_name])
            else:
                self.noContextFound.emit()
        if not completion_items:
            self.completer.popup().hide()
            self.noContextFound.emit()
            return
        self._update_and_show_completer(completion_items, current_word)

    # 【新增】处理Enter键信号的槽函数
    @Slot(QTextBlock)
    def on_line_completed(self, completed_block: QTextBlock):
        line_text = completed_block.text().strip()

        # 1. 检查是否是 'action: name' 格式
        match = re.match(r'^action:\s*([\w\-/.]+)', line_text)
        if not match:
            return

        action_name = match.group(1)
        if action_name not in self._action_map:
            return

        # 2. 检查下一行是否已经有 params
        next_block = completed_block.next()
        if next_block.isValid() and next_block.text().strip().startswith("params:"):
            return

        # 3. 获取Action的参数定义
        action_def = self._action_map[action_name]
        try:
            # 假设action的执行方法是run
            params = inspect.signature(action_def.run).parameters
        except (AttributeError, ValueError):
            return  # action没有run方法或签名无法获取

        # 过滤掉 self, cls, context 等内置参数
        param_names = [p for p in params if p not in ['self', 'cls', 'context']]
        if not param_names:
            return  # 没有需要用户填写的参数

        # 4. 构建params代码片段
        snippet_lines = ["params:"]
        for i, name in enumerate(param_names):
            snippet_lines.append(f"  {name}: ${i + 1}")

        snippet = "\n".join(snippet_lines)

        # 5. 命令编辑器在当前光标位置插入代码片段
        base_indentation = " " * get_indentation(completed_block.text())
        self.editor_widget.insert_snippet_at_cursor(snippet, base_indentation)

    # ... (其余方法无变化) ...
    def _get_completions_for_context(self, key_path: List[str]) -> List[CompletionItem]:
        if not key_path: return []
        parent = key_path[-1]
        if len(key_path) <= 2 and key_path[0] != 'steps': return TOP_LEVEL_KEYWORDS
        if parent == 'steps': return []
        if 'steps' in key_path:
            try:
                steps_index = len(key_path) - 1 - key_path[::-1].index('steps')
                if len(key_path) > steps_index + 1: return NODE_LEVEL_KEYWORDS
            except ValueError:
                pass
        return []

    def _update_and_show_completer(self, items: List[CompletionItem], prefix: str):
        self.model.clear()
        for item in items:
            display_text, snippet = (item, item) if isinstance(item, str) else item
            standard_item = QStandardItem(display_text)
            standard_item.setData(snippet, self.SnippetRole)
            self.model.appendRow(standard_item)
        self.completer.setCompletionPrefix(prefix)
        if self.model.rowCount() > 0: self.completer.complete()

    @Slot(str)
    def _on_completion_activated(self, text: str):
        selected_item = self.model.findItems(text)[0] if self.model.findItems(text) else None
        if not selected_item: return
        snippet = selected_item.data(self.SnippetRole)
        prefix = self.completer.completionPrefix()
        self.editor_widget.insert_snippet(snippet, prefix)
