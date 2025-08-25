# plans/aura_ui/workspace_panel.py (异步桥接版)

import io
import os
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, PhotoImage

import yaml
from PIL import Image, ImageTk

from packages.aura_core.logger import logger
from .base_panel import BasePanel
from .visual_task_editor import VisualTaskEditor


class WorkspacePanel(BasePanel):
    def _create_widgets(self):
        self.active_editor = None
        self.current_plan = tk.StringVar()
        self.photo_image_cache = {}
        self.image_extensions = ['.png', '.jpg', '.jpeg', '.bmp', '.gif']
        self.task_file_extensions = ['.yaml', '.yml']

        self._create_color_icons()

        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)
        left_frame = ttk.Frame(main_pane, padding=5)
        main_pane.add(left_frame, weight=1)
        control_frame = ttk.Frame(left_frame)
        control_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(control_frame, text="方案包:").pack(side=tk.LEFT)
        self.plan_combobox = ttk.Combobox(control_frame, textvariable=self.current_plan, state="readonly")
        self.plan_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.plan_combobox.bind("<<ComboboxSelected>>", self._populate_file_tree)
        ttk.Button(control_frame, text="刷新", command=self._force_refresh_all).pack(side=tk.LEFT)
        self.file_tree = ttk.Treeview(left_frame, show="tree headings")
        self.file_tree.column("#0", width=250, anchor='w')
        self.file_tree.pack(fill=tk.BOTH, expand=True)
        self.file_tree.bind("<Double-1>", self._on_file_double_click)
        self.editor_area = ttk.Frame(main_pane)
        main_pane.add(self.editor_area, weight=4)
        self.editor_area.grid_rowconfigure(1, weight=1)
        self.editor_area.grid_columnconfigure(0, weight=1)
        editor_toolbar = ttk.Frame(self.editor_area, padding=(10, 5, 10, 0))
        editor_toolbar.grid(row=0, column=0, sticky="ew")
        self.save_button = ttk.Button(editor_toolbar, text="保存", command=self._save_current_file, state="disabled")
        self.save_button.pack(side=tk.RIGHT)
        self.current_file_label = ttk.Label(editor_toolbar, text="双击左侧文件进行编辑")
        self.current_file_label.pack(side=tk.LEFT)
        self.editor_container = ttk.Frame(self.editor_area)
        self.editor_container.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

    def _initial_load(self):
        """初始加载时，请求一次全量数据。"""
        self.populate_plans(self.scheduler.get_all_plans())

    def destroy(self):
        if self.active_editor and hasattr(self.active_editor, 'destroy'):
            self.active_editor.destroy()
        super().destroy()

    def _create_color_icons(self):
        colors = {"folder": "#E69F00", "file": "#56B4E9", "task_file": "#009E73", "task": "#F0E442"}
        for name, color in colors.items():
            color_img = PhotoImage(width=16, height=16)
            color_img.put(color, to=(0, 0, 15, 15))
            setattr(self, f"{name}_icon", color_img)

    def _force_refresh_all(self):
        """【修改】刷新现在只触发后端重载，UI更新由推送机制完成。"""
        logger.info("用户请求手动刷新方案包列表...")
        self.scheduler.reload_plans()
        if isinstance(self.active_editor, VisualTaskEditor):
            self.active_editor.update_actions_list()
        logger.info("后端资源重载请求已发送。")

    def populate_plans(self, plans: list):
        """【修改】被动接收方案包列表。"""
        current_selection = self.current_plan.get()
        self.plan_combobox['values'] = plans
        if plans:
            if current_selection in plans:
                self.plan_combobox.set(current_selection)
            else:
                self.plan_combobox.current(0)
            self._populate_file_tree()
        else:
            self.current_plan.set('')
            self.file_tree.delete(*self.file_tree.get_children())

    def _populate_file_tree(self, event=None):
        for i in self.file_tree.get_children(): self.file_tree.delete(i)
        plan_name = self.current_plan.get()
        if not plan_name: return
        try:
            file_structure = self.scheduler.get_plan_files(plan_name)
            self._add_files_to_tree("", file_structure, "")
        except Exception as e:
            messagebox.showerror("错误", f"无法加载方案文件列表: {e}")

    # ... (其余方法 _add_files_to_tree, _on_file_double_click, _load_editor_for_item, _save_current_file 保持不变) ...
    def _add_files_to_tree(self, parent_id, structure, current_path):
        for name, item in sorted(structure.items()):
            full_path = os.path.join(current_path, name)
            is_dir = isinstance(item, dict)
            if not is_dir and full_path.startswith('tasks' + os.sep) and any(
                    name.endswith(ext) for ext in self.task_file_extensions):
                try:
                    content = self.scheduler.get_file_content(self.current_plan.get(), full_path)
                    all_tasks_data = yaml.safe_load(content) or {}
                    if isinstance(all_tasks_data, dict) and 'steps' not in all_tasks_data:
                        file_node_id = self.file_tree.insert(parent_id, "end", text=name, image=self.task_file_icon,
                                                             tags=('task_file', full_path))
                        for task_name in sorted(all_tasks_data.keys()):
                            self.file_tree.insert(file_node_id, "end", text=task_name, image=self.task_icon,
                                                  tags=('task', full_path, task_name))
                    else:
                        self.file_tree.insert(parent_id, "end", text=name, image=self.task_file_icon,
                                              tags=('file', full_path))
                except Exception as e:
                    logger.warning(f"解析任务文件 '{full_path}' 失败: {e}, 将其作为普通文件处理。")
                    self.file_tree.insert(parent_id, "end", text=name, image=self.file_icon, tags=('file', full_path))
            elif is_dir:
                node_id = self.file_tree.insert(parent_id, "end", text=name, image=self.folder_icon,
                                                tags=('directory', full_path))
                self._add_files_to_tree(node_id, item, full_path)
            else:
                self.file_tree.insert(parent_id, "end", text=name, image=self.file_icon, tags=('file', full_path))

    def _on_file_double_click(self, event):
        item_id = self.file_tree.focus()
        if not item_id: return
        tags = self.file_tree.item(item_id, "tags")
        if not tags: return
        item_type = tags[0]
        if item_type == 'directory':
            self.file_tree.item(item_id, open=not self.file_tree.item(item_id, "open"))
            return
        file_path = tags[1]
        task_name = tags[2] if item_type == 'task' else None
        self._load_editor_for_item(file_path, item_type, task_name)

    def _load_editor_for_item(self, file_path, item_type, task_name=None):
        if self.active_editor:
            self.active_editor.destroy()
            self.active_editor = None
        plan_name = self.current_plan.get()
        _, extension = os.path.splitext(file_path)
        display_name = f"{file_path} [{task_name}]" if task_name else file_path
        self.current_file_label.config(text=f"编辑: {display_name}")
        can_save = True
        editor_kwargs = {'scheduler': self.scheduler, 'ide': self.ide}

        if item_type == 'task' or (item_type == 'file' and file_path.startswith('tasks' + os.sep) and any(
                file_path.endswith(ext) for ext in self.task_file_extensions)):
            try:
                full_content = self.scheduler.get_file_content(plan_name, file_path)
                all_tasks_data = yaml.safe_load(full_content) or {}
                task_data_to_edit = all_tasks_data.get(task_name, {}) if item_type == 'task' else all_tasks_data
                self.active_editor = VisualTaskEditor(self.editor_container, plan_name=plan_name, file_path=file_path,
                                                      task_name=task_name, task_data=task_data_to_edit, **editor_kwargs)
            except Exception as e:
                messagebox.showerror("加载错误", f"无法加载可视化编辑器: {e}")
                self.active_editor = TextEditor(self.editor_container, plan_name=plan_name, file_path=file_path,
                                                **editor_kwargs)
        elif extension.lower() in self.image_extensions:
            self.active_editor = ImageViewer(self.editor_container, plan_name=plan_name, file_path=file_path,
                                             **editor_kwargs)
            can_save = False
        else:
            self.active_editor = TextEditor(self.editor_container, plan_name=plan_name, file_path=file_path,
                                            **editor_kwargs)
        self.save_button.config(state="normal" if can_save else "disabled")
        if self.active_editor:
            self.active_editor.pack(fill=tk.BOTH, expand=True)

    def _save_current_file(self):
        if self.active_editor and hasattr(self.active_editor, 'save'):
            try:
                self.active_editor.save()
            except Exception as e:
                messagebox.showerror("保存失败", f"保存文件时出错: {e}")
        else:
            messagebox.showwarning("无操作", "当前编辑器不支持保存。")


class TextEditor(BasePanel):
    def __init__(self, parent, plan_name, file_path, **kwargs):
        self.plan_name = plan_name
        self.file_path = file_path
        super().__init__(parent, **kwargs)

    def _create_widgets(self):
        self.text_area = scrolledtext.ScrolledText(self, wrap=tk.WORD, font=("Courier New", 10))
        self.text_area.pack(fill=tk.BOTH, expand=True)

    def _initial_load(self):
        try:
            content = self.scheduler.get_file_content(self.plan_name, self.file_path)
            self.text_area.delete('1.0', tk.END)
            self.text_area.insert('1.0', content)
        except Exception as e:
            self.text_area.delete('1.0', tk.END)
            self.text_area.insert('1.0', f"无法以文本模式加载文件:\n{e}")

    def save(self):
        content = self.text_area.get('1.0', tk.END).strip()
        self.scheduler.save_file_content(self.plan_name, self.file_path, content)


class ImageViewer(BasePanel):
    def __init__(self, parent, plan_name, file_path, **kwargs):
        self.plan_name = plan_name
        self.file_path = file_path
        super().__init__(parent, **kwargs)

    def _create_widgets(self):
        self.image_label = ttk.Label(self, background="gray")
        self.image_label.pack(fill=tk.BOTH, expand=True)

    def _initial_load(self):
        try:
            image_bytes = self.scheduler.get_file_content_bytes(self.plan_name, self.file_path)
            image = Image.open(io.BytesIO(image_bytes))
            self.photo_image = ImageTk.PhotoImage(image)
            self.image_label.config(image=self.photo_image)
        except Exception as e:
            self.image_label.config(image=None, text=f"无法预览图片:\n{e}")
