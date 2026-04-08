"""
插件项目脚手架工具

帮助开发者快速创建新的插件项目
"""

from pathlib import Path
from datetime import datetime
from typing import Dict, List


class PluginScaffold:
    """插件项目脚手架"""

    TEMPLATES = {
        "basic": {
            "files": ["manifest.yaml", "README.md", "LICENSE", "src/__init__.py"],
            "description": "基础插件模板"
        },
        "service": {
            "files": ["manifest.yaml", "README.md", "LICENSE", "src/__init__.py", "src/services/my_service.py"],
            "description": "服务插件模板"
        },
        "task": {
            "files": ["manifest.yaml", "README.md", "LICENSE", "src/__init__.py", "src/tasks/my_task.py"],
            "description": "任务插件模板"
        },
        "full": {
            "files": [
                "manifest.yaml", "README.md", "LICENSE",
                "src/__init__.py",
                "src/services/my_service.py",
                "src/actions/my_action.py",
                "src/tasks/my_task.py",
                "src/hooks/on_install.py",
                "config/default.yaml",
                "config/schema.json",
                "tests/test_service.py",
                "assets/.gitkeep",
                "examples/usage.py"
            ],
            "description": "完整插件模板"
        }
    }

    def create(self, name: str, template: str = "basic") -> Path:
        """创建插件项目"""
        # 1. 解析名称
        if not name.startswith("@"):
            name = f"@default/{name}"

        org, plugin_name = name.lstrip("@").split("/")

        # 2. 创建目录
        plugin_dir = Path.cwd() / plugin_name
        if plugin_dir.exists():
            raise ValueError(f"Directory {plugin_dir} already exists")

        plugin_dir.mkdir(parents=True)

        # 3. 生成文件
        files = self.TEMPLATES[template]["files"]
        for file_path in files:
            full_path = plugin_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            if file_path == "manifest.yaml":
                content = self._generate_manifest(name, template)
            elif file_path == "README.md":
                content = self._generate_readme(name)
            elif file_path == "LICENSE":
                content = self._generate_license()
            elif file_path.endswith(".py"):
                content = self._generate_python_file(file_path, name)
            elif file_path == "config/default.yaml":
                content = self._generate_default_config()
            elif file_path == "config/schema.json":
                content = self._generate_config_schema()
            else:
                content = ""

            full_path.write_text(content, encoding="utf-8")

        return plugin_dir

    def _generate_manifest(self, name: str, template: str) -> str:
        """生成 manifest.yaml"""
        base_manifest = f'''package:
  name: "{name}"
  version: "0.1.0"
  description: "A new Aura plugin"
  license: "MIT"
  authors:
    - name: "Your Name"
      email: "your.email@example.com"
  homepage: ""
  repository: ""
  keywords: []
  categories: []

requires:
  aura: ">=3.0.0, <4.0.0"
  python: ">=3.10"
  platform: "all"

dependencies: {{}}

pypi-dependencies: {{}}

exports:
  services: []
  actions: []
  tasks: []

lifecycle: {{}}

build:
  include:
    - "src/**/*.py"
    - "README.md"
    - "LICENSE"
  exclude:
    - "tests/**"
    - "**/__pycache__"

metadata:
  changelog:
    - version: "0.1.0"
      date: "{datetime.now().strftime('%Y-%m-%d')}"
      changes:
        added:
          - "Initial release"
'''

        # 根据模板类型添加导出配置
        if template == "service":
            exports = '''
exports:
  services:
    - name: "my_service"
      source: "services.my_service:MyService"
      description: "My awesome service"
      visibility: "public"
'''
            base_manifest = base_manifest.replace("exports:\n  services: []", exports.strip())

        elif template == "task":
            exports = '''
exports:
  tasks:
    - id: "my_task"
      title: "My Task"
      description: "My awesome task"
      source: "tasks.my_task:MyTask"
      visibility: "public"
'''
            base_manifest = base_manifest.replace("exports:\n  services: []\n  actions: []\n  tasks: []", exports.strip())

        elif template == "full":
            exports = '''
exports:
  services:
    - name: "my_service"
      source: "services.my_service:MyService"
      description: "My awesome service"
      visibility: "public"
  actions:
    - name: "my_action"
      source: "actions.my_action:my_action"
      description: "My awesome action"
      visibility: "public"
  tasks:
    - id: "my_task"
      title: "My Task"
      description: "My awesome task"
      source: "tasks.my_task:MyTask"
      visibility: "public"
'''
            lifecycle = '''
lifecycle:
  on_install: "hooks.on_install:main"
'''
            base_manifest = base_manifest.replace("exports:\n  services: []\n  actions: []\n  tasks: []", exports.strip())
            base_manifest = base_manifest.replace("lifecycle: {}", lifecycle.strip())

        return base_manifest

    def _generate_readme(self, name: str) -> str:
        """生成 README.md"""
        plugin_name = name.split("/")[-1]
        return f'''# {name}

A new Aura plugin.

## Installation

```bash
aura plugin install ./path/to/{plugin_name}
```

## Usage

TODO: Add usage instructions

## Development

```bash
# Install in development mode (symlink)
aura plugin install ./path/to/{plugin_name} --link

# Make changes to the code...

# Test the plugin
aura plugin list
aura plugin info {name}
```

## License

MIT
'''

    def _generate_license(self) -> str:
        """生成 LICENSE"""
        year = datetime.now().year
        return f'''MIT License

Copyright (c) {year}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

    def _generate_python_file(self, file_path: str, name: str) -> str:
        """生成 Python 文件"""
        if "service" in file_path:
            return '''"""My Service"""


class MyService:
    """My awesome service"""

    def __init__(self):
        """Initialize the service"""
        pass

    def do_something(self):
        """Do something useful"""
        pass
'''
        elif "action" in file_path:
            return '''"""My Action"""


def my_action(param: str) -> dict:
    """
    My awesome action

    Args:
        param: A parameter

    Returns:
        Result dictionary
    """
    return {"result": "success", "param": param}
'''
        elif "task" in file_path:
            return '''"""My Task"""


class MyTask:
    """My awesome task"""

    def __init__(self):
        """Initialize the task"""
        pass

    def run(self):
        """Execute the task"""
        print("Task is running...")
'''
        elif "on_install" in file_path:
            return '''"""Installation hook"""


def main():
    """Execute on plugin installation"""
    print("Plugin is being installed...")
'''
        elif "test_" in file_path:
            return '''"""Service tests"""

import unittest


class TestMyService(unittest.TestCase):
    """Test cases for MyService"""

    def test_example(self):
        """Example test"""
        self.assertTrue(True)


if __name__ == '__main__':
    unittest.main()
'''
        elif "usage" in file_path:
            return '''"""Usage example"""


def main():
    """Example usage of the plugin"""
    print("This is an example of how to use the plugin")


if __name__ == '__main__':
    main()
'''
        else:
            return ''

    def _generate_default_config(self) -> str:
        """生成默认配置"""
        return '''# Default plugin configuration

# Example configuration values
example_setting: "default_value"
timeout: 30
enabled: true
'''

    def _generate_config_schema(self) -> str:
        """生成配置 Schema"""
        return '''{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "example_setting": {
      "type": "string",
      "description": "An example setting"
    },
    "timeout": {
      "type": "integer",
      "minimum": 0,
      "description": "Timeout in seconds"
    },
    "enabled": {
      "type": "boolean",
      "description": "Whether the plugin is enabled"
    }
  },
  "required": ["example_setting"]
}
'''
