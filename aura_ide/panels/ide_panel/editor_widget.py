# src/aura_ide/panels/ide_panel/editor_widget.py [V8.3 - Auto Params]

import re
from typing import List, Tuple

from PySide6.QtCore import Qt, QRegularExpression, Slot, Signal, QPoint
from PySide6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QFont, QColor, QAction, QKeySequence,
    QTextCursor, QTextDocument, QKeyEvent, QTextBlock
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QCompleter, QToolButton, QTextEdit
)

from .linter import LintingError


# --- YAML语法高亮器 (无变化) ---
class YamlHighlighter(QSyntaxHighlighter):
    # ... (代码无变化) ...
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules: List[Tuple[QRegularExpression, QTextCharFormat]] = []
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#c586c0"))
        keyword_format.setFontWeight(QFont.Weight.Bold)
        keywords = ["action:", "params:", "name:", "steps:", "when:", "retry:", "output_to:", "do:", "depends_on:"]
        for word in keywords:
            self.highlighting_rules.append((QRegularExpression(f"\\b{word}\\b"), keyword_format))
        key_format = QTextCharFormat()
        key_format.setForeground(QColor("#9CDCFE"))
        self.highlighting_rules.append((QRegularExpression(r"^\s*([\w\-\.]+):"), key_format))
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#ce9178"))
        self.highlighting_rules.append((QRegularExpression(r"'.*?'"), string_format))
        self.highlighting_rules.append((QRegularExpression(r'".*?"'), string_format))
        jinja_format = QTextCharFormat()
        jinja_format.setForeground(QColor("#4EC9B0"))
        self.highlighting_rules.append((QRegularExpression(r"{{.*?}}"), jinja_format))
        self.highlighting_rules.append((QRegularExpression(r"{%.*?%}"), jinja_format))
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6A9955"))
        self.highlighting_rules.append((QRegularExpression(r"#.*"), comment_format))

    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            expression = QRegularExpression(pattern)
            it = expression.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), format)


# --- 支持高级交互的编辑器子类 ---
class CodeEditor(QPlainTextEdit):
    # 【新增】定义信号
    enterPressedOnLine = Signal(QTextBlock)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._completer = None

    def setCompleter(self, completer: QCompleter):
        if self._completer: self._completer.disconnect(self)
        self._completer = completer
        if not self._completer: return
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

    def completer(self) -> QCompleter:
        return self._completer

    def keyPressEvent(self, event: QKeyEvent):
        is_enter_key = event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return)
        completer_visible = self._completer and self._completer.popup().isVisible()

        # 【修改】当按下Enter键且补全列表不可见时，发出信号
        if is_enter_key and not completer_visible:
            completed_block = self.textCursor().block()
            # 先让默认的换行行为发生
            super().keyPressEvent(event)
            # 然后发射信号，告知外界这一行已“完成”
            self.enterPressedOnLine.emit(completed_block)
            return  # 阻止后续处理

        if event.key() == Qt.Key.Key_Tab and not completer_visible:
            self.textCursor().insertText("    ")
            event.accept()
            return

        if completer_visible:
            if is_enter_key or event.key() == Qt.Key.Key_Escape:
                self._completer.popup().hide()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                popup = self._completer.popup()
                current_row = popup.currentIndex().row()
                self._completer.setCurrentRow(current_row)
                completion_text = self._completer.currentCompletion()
                if completion_text:
                    self._completer.popup().hide()
                    self._completer.activated.emit(completion_text)
                event.accept()
                return

        super().keyPressEvent(event)


# --- 独立的编辑器组件 ---
class EditorWidget(QWidget):
    saveRequested = Signal()
    textChanged = Signal()
    cursorPositionChanged = Signal(str, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_dirty = False
        self._file_path_text = "未打开文件"
        # ... (工具栏代码无变化) ...
        self.save_action = QAction("保存", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.setEnabled(False)
        self.save_action.triggered.connect(self.saveRequested.emit)
        self.addAction(self.save_action)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        save_button = QToolButton()
        save_button.setDefaultAction(self.save_action)
        toolbar.addWidget(save_button)
        self.current_file_label = QLabel(self._file_path_text)
        self.current_file_label.setStyleSheet("color: #888;")
        toolbar.addStretch()
        toolbar.addWidget(self.current_file_label)
        layout.addLayout(toolbar)
        self.editor = CodeEditor()
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Courier New", 10)
        self.editor.setFont(font)
        self.highlighter = YamlHighlighter(self.editor.document())
        layout.addWidget(self.editor)
        self.editor.textChanged.connect(self.textChanged.emit)
        self.editor.cursorPositionChanged.connect(self._on_cursor_moved)

    def insert_snippet(self, snippet: str, prefix: str):
        cursor = self.editor.textCursor()
        is_block_snippet = '\n' in snippet
        lines = snippet.split('\n')
        first_line = lines[0]
        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, len(prefix))
        cursor.insertText(first_line)
        if is_block_snippet:
            current_block = cursor.block()
            line_text = current_block.text()
            indentation = line_text[:line_text.find(line_text.lstrip())]
            for line in lines[1:]:
                cursor.insertBlock()
                cursor.insertText(indentation + line)
        self.editor.setTextCursor(cursor)
        self._find_and_select_placeholder("$1")

    # 【新增】一个更通用的代码插入方法
    def insert_snippet_at_cursor(self, snippet: str, base_indentation: str, extra_indent: str = "  "):
        cursor = self.editor.textCursor()
        lines = snippet.split('\n')

        # 插入第一行
        first_line = lines[0]
        cursor.insertText(base_indentation + extra_indent + first_line)

        # 插入后续行
        for line in lines[1:]:
            cursor.insertBlock()
            cursor.insertText(base_indentation + extra_indent + line)

        self.editor.setTextCursor(cursor)
        self._find_and_select_placeholder("$1")

    def _find_and_select_placeholder(self, placeholder: str):
        """在整个文档中查找第一个占位符并选中它"""
        cursor = self.editor.textCursor()
        doc = self.editor.document()
        found_cursor = doc.find(placeholder, 0)
        if not found_cursor.isNull():
            self.editor.setTextCursor(found_cursor)
            self.editor.textCursor().select(QTextCursor.SelectionType.WordUnderCursor)

    # ... (其余方法无变化) ...
    def get_content(self) -> str:
        return self.editor.toPlainText()

    def set_content(self, content: str):
        self.editor.setPlainText(content)

    def set_completer(self, completer: QCompleter):
        self.editor.setCompleter(completer)

    def set_file_path(self, path_text: str):
        self._file_path_text = path_text; self._update_label()

    def set_dirty(self, is_dirty: bool):
        if self._is_dirty == is_dirty: return
        self._is_dirty = is_dirty
        self.save_action.setEnabled(is_dirty)
        self._update_label()

    def get_document(self) -> QTextDocument:
        return self.editor.document()

    def get_text_cursor(self) -> QTextCursor:
        return self.editor.textCursor()

    def go_to_line(self, line_number: int):
        cursor = QTextCursor(self.editor.document().findBlockByNumber(line_number - 1))
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def show_linting_errors(self, errors: List[LintingError]):
        selections = []
        error_format = QTextCharFormat()
        error_format.setUnderlineColor(Qt.red)
        error_format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        for error in errors:
            if error.line_number <= 0: continue
            selection = QTextEdit.ExtraSelection()
            selection.format = error_format
            block = self.editor.document().findBlockByNumber(error.line_number - 1)
            if block.isValid():
                cursor = QTextCursor(block)
                cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                selection.cursor = cursor
                selections.append(selection)
        self.editor.setExtraSelections(selections)

    def _update_label(self):
        label_text = self._file_path_text
        if self._is_dirty and not label_text.endswith(" *"):
            label_text += " *"
        elif not self._is_dirty and label_text.endswith(" *"):
            label_text = label_text[:-2]
        self.current_file_label.setText(label_text)

    @Slot()
    def _on_cursor_moved(self):
        cursor = self.editor.textCursor()
        line_text = cursor.block().text().strip()
        cursor_rect = self.editor.cursorRect()
        global_pos = self.editor.mapToGlobal(cursor_rect.bottomLeft())
        self.cursorPositionChanged.emit(line_text, global_pos)
