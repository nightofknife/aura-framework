# src/aura_ide/panels/ide_panel/context_parser.py [V3 - Indentation-Based Parsing]

import re
from typing import List, Optional, Tuple


def get_indentation(s: str) -> int:
    """计算字符串的行首空格缩进量"""
    return len(s) - len(s.lstrip(' '))


class ContextParser:
    """
    一个更健壮的、主要基于缩进的上下文解析器。
    """

    def get_context_at_cursor(self, text: str, line_num: int, col_num: int) -> Optional[Tuple[List[str], str]]:
        """
        获取光标位置的上下文路径和当前正在输入的词。
        """
        lines = text.splitlines()
        if line_num > len(lines):
            return [], ""

        current_line_text = lines[line_num - 1]

        # 1. 获取光标前的单词
        current_word = self._get_word_before_cursor(current_line_text, col_num)

        # 2. 基于缩进向上追溯，构建上下文路径
        path = self._build_path_by_indentation(lines, line_num)

        return path, current_word

    def _get_word_before_cursor(self, line_text: str, column: int) -> str:
        pos = min(column - 1, len(line_text))
        start = pos
        # 允许的字符：字母、数字、下划线、点、斜杠
        while start > 0 and (line_text[start - 1].isalnum() or line_text[start - 1] in '_./-'):
            start -= 1
        return line_text[start:pos]

    def _build_path_by_indentation(self, lines: List[str], start_line_num: int) -> List[str]:
        """
        核心算法：通过向上查找缩进更小的父行来构建路径。
        """
        path = []

        # 确定当前行的有效内容和缩进
        current_line_text = lines[start_line_num - 1]
        # 如果当前行是空的，我们认为它的缩进是有效的，但它的内容不构成路径的一部分
        # 如果当前行有内容，我们把它自己也考虑为路径的一部分
        current_indent = get_indentation(current_line_text)

        # 如果当前行是一个键值对，我们可能是在编辑值，所以路径应该包含这个键
        key_match = re.match(r'^\s*([\w\-]+):', current_line_text)
        if key_match and not current_line_text.strip().endswith(':'):
            # We are likely on the value side of a key, so path includes the key
            pass  # The loop below will find it as a parent
        elif key_match:
            # We are on a line that defines a new block, e.g. `steps:`, `aabb:`
            path.append(key_match.group(1))

        # 向上追溯
        for i in range(start_line_num - 2, -1, -1):
            parent_line_text = lines[i]
            if not parent_line_text.strip():
                continue  # 跳过空行

            parent_indent = get_indentation(parent_line_text)

            if parent_indent < current_indent:
                parent_key_match = re.match(r'^\s*([\w\-]+):', parent_line_text)
                if parent_key_match:
                    path.insert(0, parent_key_match.group(1))
                    current_indent = parent_indent  # 更新当前缩进，继续向上查找父级

        return path
