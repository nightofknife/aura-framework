import unittest
from pathlib import Path
import shutil
import yaml

from packages.aura_core.builder import build_package_from_source, set_project_base_path, clear_build_cache
from packages.aura_core.plugin_definition import PluginDefinition
from packages.aura_core.api import ACTION_REGISTRY, service_registry

class TestBuilder(unittest.TestCase):
    def setUp(self):
        self.project_root = Path(__file__).resolve().parent.parent
        set_project_base_path(self.project_root)
        self.test_plan_path = self.project_root / "plans" / "test_plan"
        if self.test_plan_path.exists():
            shutil.rmtree(self.test_plan_path)
        self.test_plan_path.mkdir(parents=True, exist_ok=True)
        ACTION_REGISTRY.clear()
        service_registry.clear()
        clear_build_cache()

    def tearDown(self):
        if self.test_plan_path.exists():
            shutil.rmtree(self.test_plan_path)
        api_file = self.test_plan_path / "api.yaml"
        if api_file.exists():
            api_file.unlink()
        ACTION_REGISTRY.clear()
        service_registry.clear()
        clear_build_cache()


    def test_duplicate_task_ids_from_different_files(self):
        # 1. Create the test plugin structure
        plugin_yaml_content = """
identity:
  author: test_author
  name: test_plan
  version: "1.0"
plugin_type: plan
description: "A test plan"
homepage: ""
"""
        (self.test_plan_path / "plugin.yaml").write_text(plugin_yaml_content)

        tasks_dir = self.test_plan_path / "tasks"
        group1_dir = tasks_dir / "group1"
        group2_dir = tasks_dir / "group2"
        group1_dir.mkdir(parents=True, exist_ok=True)
        group2_dir.mkdir(parents=True, exist_ok=True)

        task_content = """
my_task:
  meta:
    entry_point: true
    title: "My Task"
"""
        (group1_dir / "common.yaml").write_text(task_content)
        (group2_dir / "common.yaml").write_text(task_content)

        # 2. Run the builder
        plugin_def = PluginDefinition(
            author="test_author",
            name="test_plan",
            version="1.0",
            description="A test plan",
            homepage="",
            path=self.test_plan_path,
            plugin_type="plan"
        )

        build_package_from_source(plugin_def)

        api_file_path = self.test_plan_path / "api.yaml"
        self.assertTrue(api_file_path.exists(), "api.yaml was not created")

        with open(api_file_path, 'r') as f:
            api_data = yaml.safe_load(f)

        tasks = api_data.get("entry_points", {}).get("tasks", [])
        task_ids = [task['task_id'] for task in tasks]

        # 3. Assert the correct behavior (the test should pass after the fix)
        self.assertEqual(len(task_ids), 2, "Should find two tasks")
        self.assertEqual(len(set(task_ids)), 2, "Task IDs should be unique")
        self.assertIn("group1/common/my_task", task_ids)
        self.assertIn("group2/common/my_task", task_ids)

if __name__ == '__main__':
    unittest.main()
