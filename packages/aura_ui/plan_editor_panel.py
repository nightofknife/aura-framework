# src/ui/plan_editor_panel.py
import tkinter as tk
from pathlib import Path
from tkinter import ttk, scrolledtext, messagebox, PhotoImage
import os
import yaml
import inspect
from PIL import Image, ImageTk # 【新增】导入Pillow库
import io # 【新增】导入io库

from packages.aura_shared_utils.utils.logger import logger
from packages.aura_ui.action_inspector import ActionInspectorWindow


class PlanEditorPanel(ttk.Frame):
    def __init__(self, parent, scheduler):
        super().__init__(parent)
        self.scheduler = scheduler
        self.current_editor = None
        self.current_file_path = None
        self.current_plan = tk.StringVar()
        self.photo_image_cache = None # 用于防止图片被垃圾回收
        self.image_extensions = ['.png', '.jpg', '.jpeg', '.bmp', '.gif'] # 可识别的图片后缀
        self.text_extensions = ['.yaml', '.yml', '.json', '.txt', '.py']

        self.folder_icon = PhotoImage(name='folder_icon',
                                      data='R0lGODlhEAAQAMEMAAORBf/zA/v7+/b29t3d3e/v7/n5+eDgwP///wAAAAAAAAAAAAAAAAAAAAAAAAAAACH5BAEAAAYALAAAAAAQABAAAQTeEMlJq7046827/2AojmRpnmiqrmzrvnAsz3Rt33iu73zv/8CgcEgsGo/IpHLJbDqf0Kh0Sq1ar9isdsvter/gsHhMLpvP6LR6zW673/C4fE6v2+/4vH7P7/v/gIGCg4SFhoeIiYqLjI2Oj4CBkpOUlZaXmJmam5yZAAA7')
        self.file_icon = PhotoImage(name='file_icon',
                                    data='R0lGODlhEAAQAMEMAAOpxv/81P///////9/f3/Pz8+/v79/v7wAAAAAAAAAAAAAAAAAAAAAAAAAAACH5BAEAAAYALAAAAAAQABAAAQSRCEMmqxSqzUaur1L23D2Gg5WlZ5oiq5s679wLM90bd94ru987/8CgcEgsGo/IpHLJbDqf0Kh0Sq1ar9isdsvter/gsHhMLpvP6LR6zW673/C4fE6v2+/4vH7P7/v/gIGCg4SFhoeIiYqLjI2Oj4CBkpOUlZaXmJmam5yZlAAAOw==')
        self._create_widgets()
        self._populate_plans()

    def _create_widgets(self):
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        # --- 左侧：文件浏览器 ---
        left_frame = ttk.Frame(main_pane, padding=5)
        main_pane.add(left_frame, weight=1)
        control_frame = ttk.Frame(left_frame)
        control_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(control_frame, text="方案包:").pack(side=tk.LEFT)
        self.plan_combobox = ttk.Combobox(control_frame, textvariable=self.current_plan, state="readonly")
        self.plan_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.plan_combobox.bind("<<ComboboxSelected>>", lambda e: self._populate_file_tree())
        ttk.Button(control_frame, text="刷新", command=self._force_refresh_all).pack(side=tk.LEFT)
        self.file_tree = ttk.Treeview(left_frame, show="tree headings")
        self.file_tree.column("#0", width=250, anchor='w')
        self.file_tree.pack(fill=tk.BOTH, expand=True)
        # 【修改】绑定单击事件到新的处理函数
        self.file_tree.bind("<<TreeviewSelect>>", self._on_file_select_smart)
        self.file_tree.bind("<Double-1>", self._on_file_double_click_smart)

        # --- 右侧：编辑器与预览器 ---
        right_frame = ttk.Frame(main_pane)
        main_pane.add(right_frame, weight=4)
        self.editor_notebook = ttk.Notebook(right_frame)
        self.editor_notebook.pack(fill=tk.BOTH, expand=True)

        # 编辑器标签页 (ID: 0)
        self.editor_tab = ttk.Frame(self.editor_notebook) # 【修改】给标签页变量名
        self.editor_notebook.add(self.editor_tab, text="文件编辑器")
        editor_toolbar = ttk.Frame(self.editor_tab, padding=(10, 5, 10, 0))
        editor_toolbar.pack(fill=tk.X)
        self.save_button = ttk.Button(editor_toolbar, text="保存文件", command=self._save_current_file, state="disabled")
        self.save_button.pack(side=tk.RIGHT)
        self.current_file_label = ttk.Label(editor_toolbar, text="双击左侧文件进行编辑")
        self.current_file_label.pack(side=tk.LEFT)
        self.editor_container = ttk.Frame(self.editor_tab, padding=10)
        self.editor_container.pack(fill=tk.BOTH, expand=True)

        # 资源预览器标签页 (ID: 1, 如果存在)
        self.preview_tab = ttk.Frame(self.editor_notebook, padding=10)
        # 初始不添加
    def _create_preview_widgets(self):
        """动态创建预览器UI。"""
        for widget in self.preview_tab.winfo_children(): widget.destroy()
        if not self.preview_tab.winfo_exists() or self.preview_tab not in self.editor_notebook.tabs():
             self.editor_notebook.add(self.preview_tab, text="资源预览")

        preview_toolbar = ttk.Frame(self.preview_tab)
        preview_toolbar.pack(fill=tk.X, pady=(0, 10))
        self.copy_path_button = ttk.Button(preview_toolbar, text="复制相对路径", command=self._copy_resource_path)
        self.copy_path_button.pack(side=tk.RIGHT)
        self.preview_file_label = ttk.Label(preview_toolbar, text="")
        self.preview_file_label.pack(side=tk.LEFT)
        self.image_preview_label = ttk.Label(self.preview_tab, background="gray")
        self.image_preview_label.pack(fill=tk.BOTH, expand=True)

    def _get_selected_file_path(self):
        """辅助方法，获取当前在文件树中选中的文件相对路径。"""
        item_id = self.file_tree.focus()
        if not item_id or 'directory' in self.file_tree.item(item_id, "tags"): return None
        path_parts = [self.file_tree.item(item_id, "text")]
        parent = self.file_tree.parent(item_id)
        while parent: path_parts.insert(0, self.file_tree.item(parent, "text")); parent = self.file_tree.parent(parent)
        return os.path.join(*path_parts)


    def _on_file_select_smart(self, event):
        """
        【全新逻辑】处理文件单击事件：
        - 如果是图片，显示预览并切换到预览标签页。
        - 如果不是图片，确保切换回编辑器标签页，并隐藏预览标签页。
        """
        file_path = self._get_selected_file_path()
        if not file_path:
            # 没有选中文件，确保显示编辑器标签页，隐藏预览
            self.editor_notebook.select(self.editor_tab)
            if self.preview_tab.winfo_exists() and self.preview_tab in self.editor_notebook.tabs():
                self.editor_notebook.hide(self.preview_tab)
            return

        _, extension = os.path.splitext(file_path)
        if extension.lower() in self.image_extensions:
            self._show_image_preview(file_path) # 这个方法内部会切换到预览页
        else:
            # 选中了非图片文件，切换回编辑器页，隐藏预览页
            self.editor_notebook.select(self.editor_tab)
            if self.preview_tab.winfo_exists() and self.preview_tab in self.editor_notebook.tabs():
                self.editor_notebook.hide(self.preview_tab)
            # 可以选择清除编辑器内容或显示提示
            if self.current_editor: self.current_editor.destroy(); self.current_editor = None
            self.current_file_label.config(text="双击左侧文件进行编辑")
            self.save_button.config(state="disabled")

    def _show_image_preview(self, file_path):
        """加载并显示图片预览，并切换到预览标签页。"""
        self._create_preview_widgets()  # 确保预览UI存在
        self.preview_file_label.config(text=f"预览: {file_path}")

        try:
            plan_name = self.current_plan.get()
            image_bytes = self.scheduler.get_file_content_bytes(plan_name, file_path)
            image = Image.open(io.BytesIO(image_bytes))
            image.thumbnail((self.preview_tab.winfo_width() - 20, self.preview_tab.winfo_height() - 50),
                            Image.Resampling.LANCZOS)  # 动态调整大小
            self.photo_image_cache = ImageTk.PhotoImage(image)
            self.image_preview_label.config(image=self.photo_image_cache)

            # 【关键】切换到预览标签页
            self.editor_notebook.select(self.preview_tab)

        except Exception as e:
            self.image_preview_label.config(image=None, text=f"无法预览图片:\n{e}")
            logger.error(f"预览图片 '{file_path}' 失败: {e}", exc_info=True)
            # 即使预览失败，也要切换到预览标签页显示错误信息
            self.editor_notebook.select(self.preview_tab)

    def _copy_resource_path(self):
        """复制当前预览的资源的相对路径。"""
        # 【修改】直接使用 self.current_previewing_path，因为单击时已经设置了
        file_path = self._get_selected_file_path() # 重新获取确保是当前选中的
        if file_path:
            posix_path = Path(file_path).as_posix()
            self.clipboard_clear()
            self.clipboard_append(posix_path)
            logger.info(f"路径已复制到剪贴板: {posix_path}")
            original_text = self.copy_path_button.cget("text")
            self.copy_path_button.config(text="已复制!")
            self.after(1000, lambda: self.copy_path_button.config(text=original_text) if self.copy_path_button.winfo_exists() else None)

    def _force_refresh_all(self):
        logger.info("用户请求手动刷新方案包列表...")
        selected_plan = self.current_plan.get()
        self.scheduler.reload_plans()
        self._populate_plans()
        if selected_plan in self.plan_combobox['values']:
            self.plan_combobox.set(selected_plan)
        self._populate_file_tree()
        logger.info("方案包列表刷新完毕。")

    def _populate_plans(self):
        plans = self.scheduler.get_all_plans()
        self.plan_combobox['values'] = plans
        if plans:
            if self.current_plan.get() not in plans:
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
            self._add_files_to_tree("", file_structure)
        except Exception as e:
            messagebox.showerror("错误", f"无法加载方案文件列表: {e}")

    def _add_files_to_tree(self, parent_id, structure):
        for name, item in sorted(structure.items()):
            is_dir = isinstance(item, dict)
            icon = self.folder_icon if is_dir else self.file_icon
            node_id = self.file_tree.insert(parent_id, "end", text=name, image=icon,
                                            tags=('directory' if is_dir else 'file',))
            if is_dir: self._add_files_to_tree(node_id, item)

    def _on_file_double_click_smart(self, event):
        """
                【全新逻辑】处理文件双击事件：
                - 如果是文件夹，展开/折叠。
                - 如果是图片，什么也不做（因为单击已经处理了预览）。
                - 如果是文本文件，加载编辑器并切换到编辑器标签页。
                """
        item_id = self.file_tree.focus()
        if not item_id: return

        # 处理文件夹
        if 'directory' in self.file_tree.item(item_id, "tags"):
            self.file_tree.item(item_id, open=not self.file_tree.item(item_id, "open"))
            return

        file_path = self._get_selected_file_path()
        if not file_path: return

        # 检查是否为图片文件
        _, extension = os.path.splitext(file_path)
        if extension.lower() in self.image_extensions:
            # 双击图片时，确保预览标签页是可见且选中的
            if self.preview_tab.winfo_exists() and self.preview_tab in self.editor_notebook.tabs():
                self.editor_notebook.select(self.preview_tab)
            return  # 不执行任何编辑操作

        # 【修改】只对文本文件或未知文件执行加载编辑器
        if extension.lower() in self.text_extensions or extension == '':  # 允许编辑无后缀文件
            self.current_file_path = file_path
            self._load_editor()  # 这个方法内部会切换到编辑器页
        else:
            # 对于其他非文本、非图片的文件类型，可以选择显示提示或什么都不做
            messagebox.showinfo("不支持的类型", f"暂不支持直接编辑 '{extension}' 类型的文件。", parent=self)

    def _load_editor(self):
        """加载合适的编辑器，并切换到编辑器标签页。"""
        if self.current_editor: self.current_editor.destroy()

        plan_name = self.current_plan.get()
        file_path = self.current_file_path

        self.current_file_label.config(text=f"正在编辑: {file_path}")
        self.save_button.config(state="normal")

        # 根据文件类型创建不同的编辑器
        if file_path == 'world_map.yaml':
            self.current_editor = StateMachineEditor(self.editor_container, self.scheduler, plan_name, file_path)
        elif file_path.startswith('tasks' + os.sep):
            self.current_editor = TaskEditor(self.editor_container, self.scheduler, plan_name, file_path)
        else:  # 默认使用通用文本编辑器
            self.current_editor = GenericTextEditor(self.editor_container, self.scheduler, plan_name, file_path)

        self.current_editor.pack(fill=tk.BOTH, expand=True)

        # 【关键】切换到编辑器标签页
        self.editor_notebook.select(self.editor_tab)
        # 确保预览标签页被隐藏
        if self.preview_tab.winfo_exists() and self.preview_tab in self.editor_notebook.tabs():
            self.editor_notebook.hide(self.preview_tab)

    def _save_current_file(self):
        if self.current_editor and hasattr(self.current_editor, 'save'):
            try:
                self.current_editor.save()
                messagebox.showinfo("成功", f"文件 '{self.current_file_path}' 已保存。")
            except Exception as e:
                messagebox.showerror("保存失败", f"保存文件时出错: {e}")
        else:
            messagebox.showwarning("无操作", "没有活动的编辑器或保存方法。")


# --- Editor Classes ---

class GenericTextEditor(ttk.Frame):
    def __init__(self, parent, scheduler, plan_name, file_path):
        super().__init__(parent)
        self.scheduler, self.plan_name, self.file_path = scheduler, plan_name, file_path
        self.text_area = scrolledtext.ScrolledText(self, wrap=tk.WORD, font=("Courier New", 10))
        self.text_area.pack(fill=tk.BOTH, expand=True)
        self.load()

    def load(self):
        # 【健壮性】尝试以文本模式读取，如果失败，显示错误而不是崩溃
        try:
            content = self.scheduler.get_file_content(self.plan_name, self.file_path)
            self.text_area.delete('1.0', tk.END)
            self.text_area.insert('1.0', content)
        except Exception as e:
            error_msg = f"无法以文本模式加载文件:\n{e}"
            self.text_area.delete('1.0', tk.END)
            self.text_area.insert('1.0', error_msg)
            logger.error(f"加载文件 '{self.file_path}' 到文本编辑器失败: {e}")

    def save(self):
        content = self.text_area.get('1.0', tk.END).strip() # strip() 移除末尾换行符
        self.scheduler.save_file_content(self.plan_name, self.file_path, content)


class TaskEditor(ttk.Frame):
    INSPECTABLE_ACTIONS = ["find_image", "find_text"]

    def __init__(self, parent, scheduler, plan_name, file_path):
        super().__init__(parent)
        self.scheduler, self.plan_name, self.file_path = scheduler, plan_name, file_path
        self.task_data = {}
        self.actions = self.scheduler.get_available_actions()
        self.name_var, self.requires_state_var = tk.StringVar(), tk.StringVar()
        self._create_widgets()
        self.load()

    def _create_widgets(self):
        # Task Attributes
        header_frame = ttk.LabelFrame(self, text="任务属性", padding=10)
        header_frame.pack(fill=tk.X, padx=5, pady=5)
        header_frame.columnconfigure(1, weight=1)
        ttk.Label(header_frame, text="任务名称:").grid(row=0, column=0, sticky='w', padx=5, pady=2)
        ttk.Entry(header_frame, textvariable=self.name_var).grid(row=0, column=1, sticky='ew', padx=5, pady=2)
        ttk.Label(header_frame, text="前置状态:").grid(row=1, column=0, sticky='w', padx=5, pady=2)
        ttk.Entry(header_frame, textvariable=self.requires_state_var).grid(row=1, column=1, sticky='ew', padx=5, pady=2)
        ttk.Label(header_frame, text="任务描述:").grid(row=2, column=0, sticky='nw', padx=5, pady=2)
        self.description_text = tk.Text(header_frame, height=3, wrap=tk.WORD, font=("", 9))
        self.description_text.grid(row=2, column=1, sticky='ew', padx=5, pady=2)

        # Interrupts
        interrupt_frame = ttk.LabelFrame(self, text="激活的中断", padding=10)
        interrupt_frame.pack(fill=tk.X, padx=5, pady=5)
        interrupt_frame.columnconfigure(0, weight=1)
        interrupt_frame.columnconfigure(2, weight=1)
        ttk.Label(interrupt_frame, text="可用:").grid(row=0, column=0, sticky='w')
        self.available_interrupts_list = tk.Listbox(interrupt_frame, height=5, exportselection=False)
        self.available_interrupts_list.grid(row=1, column=0, sticky='nsew', padx=(0, 5))
        btn_frame_interrupts = ttk.Frame(interrupt_frame)
        btn_frame_interrupts.grid(row=1, column=1, padx=5)
        ttk.Button(btn_frame_interrupts, text=">>", command=self._add_interrupt).pack(pady=2)
        ttk.Button(btn_frame_interrupts, text="<<", command=self._remove_interrupt).pack(pady=2)
        ttk.Label(interrupt_frame, text="已激活:").grid(row=0, column=2, sticky='w')
        self.activated_interrupts_list = tk.Listbox(interrupt_frame, height=5, exportselection=False)
        self.activated_interrupts_list.grid(row=1, column=2, sticky='nsew', padx=(5, 0))

        # Steps
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))
        left_frame = ttk.LabelFrame(pane, text="任务步骤", padding=5)
        pane.add(left_frame, weight=1)
        self.step_tree = ttk.Treeview(left_frame, columns=("#", "Name", "Action"), show="headings")
        self.step_tree.heading("#", text="#", anchor='w')
        self.step_tree.heading("Name", text="名称")
        self.step_tree.heading("Action", text="行为")
        self.step_tree.column("#", width=40, stretch=False)
        self.step_tree.pack(fill=tk.BOTH, expand=True)
        self.step_tree.bind("<<TreeviewSelect>>", self._on_step_select)
        btn_frame_steps = ttk.Frame(left_frame)
        btn_frame_steps.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame_steps, text="添加", command=self._add_step).pack(side=tk.LEFT)
        ttk.Button(btn_frame_steps, text="删除", command=self._remove_step).pack(side=tk.LEFT)
        ttk.Button(btn_frame_steps, text="上移", command=lambda: self._move_step(-1)).pack(side=tk.LEFT)
        ttk.Button(btn_frame_steps, text="下移", command=lambda: self._move_step(1)).pack(side=tk.LEFT)
        self.inspect_button = ttk.Button(btn_frame_steps, text="检查此步骤", command=self._inspect_selected_step,
                                         state="disabled")
        self.inspect_button.pack(side=tk.RIGHT, padx=5)
        self.details_frame = ttk.LabelFrame(pane, text="步骤详情", padding=10)
        pane.add(self.details_frame, weight=2)

    def load(self):
        self.task_data = yaml.safe_load(self.scheduler.get_file_content(self.plan_name, self.file_path)) or {}
        self.name_var.set(self.task_data.get('name', ''))
        self.requires_state_var.set(self.task_data.get('requires_state', ''))
        self.description_text.delete('1.0', tk.END)
        self.description_text.insert('1.0', self.task_data.get('description', ''))
        self._refresh_step_list()
        self._populate_interrupt_lists()

    def _populate_interrupt_lists(self):
        self.available_interrupts_list.delete(0, tk.END)
        self.activated_interrupts_list.delete(0, tk.END)
        activated_set = set(self.task_data.get('activates_interrupts', []))
        for rule in self.scheduler.get_all_interrupts_status():
            if rule.get('scope') == 'task' and rule.get('plan_name') == self.plan_name:
                (self.activated_interrupts_list if rule[
                                                       'name'] in activated_set else self.available_interrupts_list).insert(
                    tk.END, rule['name'])

    def _add_interrupt(self):
        for i in reversed(self.available_interrupts_list.curselection()):
            self.activated_interrupts_list.insert(tk.END, self.available_interrupts_list.get(i))
            self.available_interrupts_list.delete(i)

    def _remove_interrupt(self):
        for i in reversed(self.activated_interrupts_list.curselection()):
            self.available_interrupts_list.insert(tk.END, self.activated_interrupts_list.get(i))
            self.activated_interrupts_list.delete(i)

    def _refresh_step_list(self):
        self.step_tree.delete(*self.step_tree.get_children())
        for i, step in enumerate(self.task_data.get('steps', [])):
            self.step_tree.insert("", "end", iid=i, values=(i + 1, step.get('name', ''), step.get('action', '')))

    def _on_step_select(self, event):
        selected_items = self.step_tree.selection()
        if not selected_items: return
        step_index = int(selected_items[0])
        step_data = self.task_data.get('steps', [])[step_index]

        # 清理旧的详情控件
        for widget in self.details_frame.winfo_children(): widget.destroy()

        # --- 渲染基本信息 (name, action) ---
        # (这部分代码保持不变)
        ttk.Label(self.details_frame, text="名称:").grid(row=0, column=0, sticky='w', pady=2)
        name_var = tk.StringVar(value=step_data.get('name', ''))
        ttk.Entry(self.details_frame, textvariable=name_var, width=40).grid(row=0, column=1, columnspan=2, sticky='ew')
        name_var.trace_add("write", lambda *a: self._update_step_data(step_index, 'name', name_var.get()))

        ttk.Label(self.details_frame, text="行为:").grid(row=1, column=0, sticky='w', pady=2)
        action_var = tk.StringVar(value=step_data.get('action', ''))
        action_combo = ttk.Combobox(self.details_frame, textvariable=action_var, values=list(self.actions.keys()),
                                    state="readonly")
        action_combo.grid(row=1, column=1, columnspan=2, sticky='ew')
        action_combo.bind("<<ComboboxSelected>>",
                          lambda e: self._update_step_data(step_index, 'action', action_var.get(), True))

        # --- 【新增】显示Action的文档说明 ---
        action_name = step_data.get('action')
        if action_name in self.actions:
            action_def = self.actions[action_name]
            doc_label = ttk.Label(self.details_frame, text=action_def.docstring, wraplength=400, justify=tk.LEFT,
                                  style="TLabel")
            doc_label.grid(row=2, column=0, columnspan=3, sticky='w', pady=(5, 10), padx=5)

        # --- 渲染参数 ---
        params_frame = ttk.LabelFrame(self.details_frame, text="参数", padding=5)
        params_frame.grid(row=3, column=0, columnspan=3, sticky='ew', pady=5)
        params_frame.columnconfigure(1, weight=1)  # 让输入框可以伸缩

        self.inspect_button.config(state="normal" if action_name in self.INSPECTABLE_ACTIONS else "disabled")

        if action_name in self.actions:
            action_def = self.actions[action_name]  # 再次获取 action_def
            params = step_data.get('params', {})
            row = 0
            for param_name, spec in action_def.signature.parameters.items():
                if param_name in ['context', 'engine', 'persistent_context']: continue

                # 参数名标签
                ttk.Label(params_frame, text=f"{param_name}:").grid(row=row, column=0, sticky='w', pady=2, padx=5)

                # 参数输入框
                param_var = tk.StringVar(
                    value=params.get(param_name, spec.default if spec.default != inspect.Parameter.empty else ''))
                ttk.Entry(params_frame, textvariable=param_var).grid(row=row, column=1, sticky='ew', pady=2, padx=5)
                param_var.trace_add("write",
                                    lambda *a, pn=param_name, pv=param_var: self._update_step_param(step_index, pn,
                                                                                                    pv.get()))

                # 【新增】参数类型/默认值提示
                param_doc_text = ""
                if spec.annotation != inspect.Parameter.empty:
                    param_doc_text += f"类型: {spec.annotation.__name__}"
                if spec.default != inspect.Parameter.empty:
                    param_doc_text += f" (默认: {spec.default})"

                if param_doc_text:
                    doc_label = ttk.Label(params_frame, text=param_doc_text, foreground="gray", font=("", 8))
                    doc_label.grid(row=row, column=2, sticky='w', padx=5)

                row += 1
    def _inspect_selected_step(self):
        selected = self.step_tree.selection()
        if not selected: return
        step_index = int(selected[0])
        logger.info(f"UI请求检查步骤 {step_index}...")
        self.config(cursor="watch")
        try:
            result = self.scheduler.inspect_step(self.plan_name, self.file_path, step_index)
            if hasattr(result, 'debug_info') and result.debug_info:
                ActionInspectorWindow(self, result)
            else:
                messagebox.showinfo("检查结果", f"步骤执行完毕，返回值为:\n\n{result}")
        except Exception as e:
            logger.error(f"检查步骤失败: {e}", exc_info=True)
            messagebox.showerror("检查失败", f"执行步骤时发生错误:\n\n{e}")
        finally:
            self.config(cursor="")

    def _update_step_data(self, index, key, value, action_changed=False):
        self.task_data['steps'][index][key] = value
        if action_changed: self.task_data['steps'][index]['params'] = {}
        self._refresh_step_list()
        self.step_tree.selection_set(str(index))

    def _update_step_param(self, index, param_name, value):
        self.task_data.setdefault('steps', [])[index].setdefault('params', {})[param_name] = value

    def _add_step(self):
        self.task_data.setdefault('steps', []).append({'name': '新步骤', 'action': '', 'params': {}})
        self._refresh_step_list()

    def _remove_step(self):
        selected = self.step_tree.selection()
        if selected: self.task_data['steps'].pop(int(selected[0])); self._refresh_step_list()

    def _move_step(self, direction):
        selected = self.step_tree.selection()
        if not selected: return
        index = int(selected[0])
        new_index = index + direction
        steps = self.task_data.get('steps', [])
        if 0 <= new_index < len(steps):
            steps.insert(new_index, steps.pop(index))
            self._refresh_step_list()
            self.step_tree.selection_set(str(new_index))

    def save(self):
        self.task_data['name'] = self.name_var.get()
        self.task_data['description'] = self.description_text.get('1.0', tk.END).strip()
        if self.requires_state_var.get():
            self.task_data['requires_state'] = self.requires_state_var.get()
        elif 'requires_state' in self.task_data:
            del self.task_data['requires_state']

        activated_list = list(self.activated_interrupts_list.get(0, tk.END))
        if activated_list:
            self.task_data['activates_interrupts'] = activated_list
        elif 'activates_interrupts' in self.task_data:
            del self.task_data['activates_interrupts']

        if 'steps' in self.task_data and not self.task_data['steps']: del self.task_data['steps']
        new_content = yaml.dump(self.task_data, allow_unicode=True, sort_keys=False, default_flow_style=False)
        self.scheduler.save_file_content(self.plan_name, self.file_path, new_content)


# src/ui/plan_editor_panel.py

# ... (文件顶部的所有 import 保持不变) ...
# 【新增】导入 networkx, math, 和 simpledialog


# ... (PlanEditorPanel 和其他编辑器类保持不变) ...
# ... (GenericTextEditor 和 TaskEditor 的代码保持不变) ...


# src/ui/plan_editor_panel.py

# ... (文件顶部的所有 import 保持不变) ...
# 【新增】导入 networkx, math, 和 simpledialog
import networkx as nx
import math
from tkinter import simpledialog


# ... (PlanEditorPanel 和其他编辑器类保持不变) ...
# ... (GenericTextEditor 和 TaskEditor 的代码保持不变) ...


class StateMachineEditor(ttk.Frame):
    """
    【最终完美版 v3】一个具备可视化交互设计、右键菜单重命名和曲线箭头功能的专业状态机编辑器。
    此版本使用self.after彻底修正了重命名对话框的TclError。
    """

    def __init__(self, parent, scheduler, plan_name, file_path):
        super().__init__(parent)
        self.scheduler, self.plan_name, self.file_path = scheduler, plan_name, file_path

        self.map_data = {}
        self.canvas_items = {}
        self.line_items = {}
        self.scaled_pos = {}
        self.selected_item = None
        self.node_width, self.node_height = 140, 50
        self._resize_timer = None
        self.plan_tasks = []
        self._drag_data = {'start_node': None, 'line': None}

        self._create_widgets()
        self.load()

    def _create_widgets(self):
        # ... (此函数及之后的所有方法都与上一版相同，无需修改) ...
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)
        canvas_frame = ttk.Frame(main_pane)
        main_pane.add(canvas_frame, weight=3)
        canvas_toolbar = ttk.Frame(canvas_frame)
        canvas_toolbar.pack(side=tk.TOP, fill=tk.X, pady=5, padx=5)
        ttk.Button(canvas_toolbar, text="重排布局", command=self.load).pack(side=tk.LEFT)
        self.canvas = tk.Canvas(canvas_frame, bg='white', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<Button-3>", self._on_canvas_right_click)
        self.canvas.bind("<B1-Motion>", self._do_drag)
        self.canvas.bind("<ButtonRelease-1>", self._end_drag)
        self.properties_frame = ttk.LabelFrame(main_pane, text="属性编辑器", padding=10)
        main_pane.add(self.properties_frame, weight=1)

    def load(self):
        try:
            content = self.scheduler.get_file_content(self.plan_name, self.file_path)
            self.map_data = yaml.safe_load(content) or {}
            if 'states' not in self.map_data: self.map_data['states'] = {}
            if 'transitions' not in self.map_data: self.map_data['transitions'] = []
            self.plan_tasks = self.scheduler.get_tasks_for_plan(self.plan_name)
            self.after(50, self._recalculate_and_draw)
        except Exception as e:
            messagebox.showerror("加载失败", f"加载 world_map.yaml 失败: {e}")
            logger.error(f"加载 world_map.yaml 失败: {e}", exc_info=True)

    def _on_canvas_resize(self, event):
        if self._resize_timer: self.after_cancel(self._resize_timer)
        self._resize_timer = self.after(100, self._recalculate_and_draw)

    def _recalculate_and_draw(self):
        self._calculate_layout()
        self._draw_canvas()

    def _calculate_layout(self):
        states = self.map_data.get('states', {})
        if not states:
            self.scaled_pos = {}
            return
        G = nx.DiGraph()
        for state_name in states: G.add_node(state_name)
        for transition in self.map_data.get('transitions', []):
            source, target = transition.get('from'), transition.get('to')
            if source in G and target in G: G.add_edge(source, target)
        try:
            pos = nx.spring_layout(G, seed=42, k=1.2, iterations=100)
        except nx.NetworkXError:
            pos = {list(G.nodes())[0]: (0, 0)} if G.nodes() else {}
        canvas_width, canvas_height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1: return
        padding = 80
        min_x, max_x = min((p[0] for p in pos.values()), default=0), max((p[0] for p in pos.values()), default=0)
        min_y, max_y = min((p[1] for p in pos.values()), default=0), max((p[1] for p in pos.values()), default=0)

        def scale_pos(p):
            x, y = p
            scale_x = (canvas_width - 2 * padding) / (max_x - min_x) if max_x > min_x else 1
            scale_y = (canvas_height - 2 * padding) / (max_y - min_y) if max_y > min_y else 1
            new_x, new_y = padding + (x - min_x) * scale_x, padding + (y - min_y) * scale_y
            return new_x, new_y

        self.scaled_pos = {name: scale_pos(p) for name, p in pos.items()}

    def _draw_canvas(self):
        self.canvas.delete("all")
        self.canvas_items.clear()
        self.line_items.clear()
        self._update_properties_panel(self.selected_item)
        if not self.scaled_pos: return
        transition_pairs = {(t['from'], t['to']) for t in self.map_data.get('transitions', [])}
        for i, transition in enumerate(self.map_data.get('transitions', [])):
            source, target = transition.get('from'), transition.get('to')
            if not (source in self.scaled_pos and target in self.scaled_pos): continue
            x1_center, y1_center = self.scaled_pos[source]
            x2_center, y2_center = self.scaled_pos[target]
            is_bidirectional = (target, source) in transition_pairs
            if is_bidirectional:
                u, v = min(source, target), max(source, target)
                x_u, y_u = self.scaled_pos[u]
                x_v, y_v = self.scaled_pos[v]
                is_canonical_direction = (source == u)
                control_point = self._get_arc_control_point(x_u, y_u, x_v, y_v, is_canonical_direction)
                start_x, start_y = self._get_line_box_intersection(control_point[0], control_point[1], x1_center,
                                                                   y1_center)
                end_x, end_y = self._get_line_box_intersection(control_point[0], control_point[1], x2_center, y2_center)
                line_id = self.canvas.create_line(start_x, start_y, *control_point, end_x, end_y, smooth=True,
                                                  arrow=tk.LAST, arrowshape=(10, 12, 5), width=3.0, activewidth=5.0,
                                                  fill='gray40', activefill='red')
                mid_x, mid_y = control_point
            else:
                start_x, start_y = self._get_line_box_intersection(x2_center, y2_center, x1_center, y1_center)
                end_x, end_y = self._get_line_box_intersection(x1_center, y1_center, x2_center, y2_center)
                line_id = self.canvas.create_line(start_x, start_y, end_x, end_y, arrow=tk.LAST, arrowshape=(10, 12, 5),
                                                  width=3.0, activewidth=5.0, fill='gray40', activefill='red')
                mid_x, mid_y = (start_x + end_x) / 2, (start_y + end_y) / 2
            self.canvas.tag_bind(line_id, "<Button-1>", lambda e, idx=i: self._on_item_click(f"transition:{idx}"))
            self.line_items[i] = line_id
            task_name = transition.get('task', 'N/A')
            text_id = self.canvas.create_text(mid_x, mid_y, text=task_name, fill='blue', font=("", 8, "italic"))
            bbox = self.canvas.bbox(text_id)
            bg_id = self.canvas.create_rectangle(bbox, fill="white", outline="")
            self.canvas.tag_lower(bg_id, text_id)
        start_state = self.map_data.get('start_state')
        for name, p in self.scaled_pos.items():
            x, y = p
            x1, y1, x2, y2 = x - self.node_width / 2, y - self.node_height / 2, x + self.node_width / 2, y + self.node_height / 2
            fill_color = 'lightgreen' if name == start_state else 'lightblue'
            node_id = self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill_color, outline='blue', width=1.5,
                                                   activeoutline='red', activewidth=2.5, tags=f"node_{name}")
            text_id = self.canvas.create_text(x, y, text=name, font=("", 9, "bold"), tags=f"node_{name}_text")
            self.canvas.tag_bind(f"node_{name}", "<Button-1>", lambda e, n=name: self._on_item_click(f"state:{n}"))
            self.canvas.tag_bind(f"node_{name}", "<Button-3>", lambda e, n=name: self._on_node_right_click(e, n))
            self.canvas.tag_bind(f"node_{name}", "<Control-Button-1>", lambda e, n=name: self._start_drag(e, n))
            self.canvas_items[name] = {'node_id': node_id, 'text_id': text_id}
        if self.selected_item: self._highlight_item(self.selected_item, 'red', 5.0)

    def _on_node_right_click(self, event, state_name):
        menu = tk.Menu(self, tearoff=0)
        # 【TclError FIX】使用 self.after 延迟对话框的调用，避免与菜单销毁冲突
        menu.add_command(label=f"重命名状态 '{state_name}'...",
                         command=lambda: self.after(1, lambda: self._prompt_for_rename(state_name)))
        menu.add_separator()
        menu.add_command(label=f"将 '{state_name}' 设为起始状态", command=lambda: self._set_as_start_state(state_name))
        menu.add_separator()
        menu.add_command(label=f"删除状态 '{state_name}'", command=lambda: self._delete_state(state_name))
        menu.post(event.x_root, event.y_root)

    def _prompt_for_rename(self, old_name):
        new_name = simpledialog.askstring(
            "重命名状态",
            f"为状态 '{old_name}' 输入新名称:",
            initialvalue=old_name,
            parent=self.winfo_toplevel()
        )
        if new_name:
            self._rename_state(old_name, new_name.strip())

    def _rename_state(self, old_name, new_name):
        if not new_name or old_name == new_name: return
        if new_name in self.map_data['states']:
            messagebox.showerror("重命名失败", f"状态名 '{new_name}' 已存在。", parent=self.winfo_toplevel())
            return
        self.map_data['states'][new_name] = self.map_data['states'].pop(old_name)
        for t in self.map_data.get('transitions', []):
            if t.get('from') == old_name: t['from'] = new_name
            if t.get('to') == old_name: t['to'] = new_name
        if self.map_data.get('start_state') == old_name:
            self.map_data['start_state'] = new_name
        if self.selected_item == f"state:{old_name}":
            self.selected_item = f"state:{new_name}"
        self.save()
        self._recalculate_and_draw()

    # --- 其他函数保持不变 ---

    def _get_arc_control_point(self, x1, y1, x2, y2, is_first_curve=True):
        dx, dy = x2 - x1, y2 - y1
        mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
        perp_dx, perp_dy = -dy, dx
        dist = math.sqrt(perp_dx ** 2 + perp_dy ** 2)
        if dist == 0: return mid_x, mid_y
        norm_perp_dx, norm_perp_dy = perp_dx / dist, perp_dy / dist
        curvature = 30
        if not is_first_curve: curvature = -curvature
        return mid_x + curvature * norm_perp_dx, mid_y + curvature * norm_perp_dy

    def _get_line_box_intersection(self, from_x, from_y, to_x, to_y):
        dx, dy = to_x - from_x, to_y - from_y
        if dx == 0 and dy == 0: return to_x, to_y
        half_w, half_h = self.node_width / 2, self.node_height / 2
        if dx == 0: return to_x, to_y - half_h if dy > 0 else to_y + half_h
        if dy == 0: return to_x - half_w if dx > 0 else to_x + half_w, to_y
        line_slope = dy / dx;
        box_slope = half_h / half_w
        if abs(line_slope) < box_slope:
            if dx > 0:
                return to_x - half_w, from_y + line_slope * (to_x - half_w - from_x)
            else:
                return to_x + half_w, from_y + line_slope * (to_x + half_w - from_x)
        else:
            if dy > 0:
                return from_x + (to_y - half_h - from_y) / line_slope, to_y - half_h
            else:
                return from_x + (to_y + half_h - from_y) / line_slope, to_y + half_h

    def _on_canvas_right_click(self, event):
        # 查找鼠标下的元素，以确定是点击了空白处还是节点
        overlapping = self.canvas.find_overlapping(event.x, event.y, event.x, event.y)
        node_clicked = False
        for item in overlapping:
            tags = self.canvas.gettags(item)
            if any(tag.startswith("node_") for tag in tags):
                node_clicked = True
                break

        if not node_clicked:
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(label="在此处创建新状态", command=lambda: self._create_new_state(event.x, event.y))
            menu.post(event.x_root, event.y_root)

    def _create_new_state(self, canvas_x, canvas_y):
        base_name = "new_state"
        new_name = base_name
        count = 1
        while new_name in self.map_data['states']:
            new_name = f"{base_name}_{count}"
            count += 1
        self.map_data['states'][new_name] = {'check': {'task': ''}}
        self.save()
        self._recalculate_and_draw()
        self._on_item_click(f"state:{new_name}")

    def _delete_state(self, state_name):
        if not messagebox.askyesno("确认删除", f"确定要删除状态 '{state_name}' 吗？\n所有与它相关的转换也将被一并删除。"):
            return
        if state_name in self.map_data['states']:
            del self.map_data['states'][state_name]
        self.map_data['transitions'] = [t for t in self.map_data.get('transitions', []) if
                                        t.get('from') != state_name and t.get('to') != state_name]
        if self.map_data.get('start_state') == state_name:
            del self.map_data['start_state']
        self.selected_item = None
        self.save()
        self._recalculate_and_draw()

    def _set_as_start_state(self, state_name):
        self.map_data['start_state'] = state_name
        self.save()
        self._draw_canvas()

    def _start_drag(self, event, state_name):
        self._drag_data['start_node'] = state_name
        x, y = self.scaled_pos[state_name]
        self._drag_data['line'] = self.canvas.create_line(x, y, event.x, event.y, fill='blue', dash=(4, 4))

    def _do_drag(self, event):
        if not self._drag_data.get('line'): return
        x, y = self.scaled_pos[self._drag_data['start_node']]
        self.canvas.coords(self._drag_data['line'], x, y, event.x, event.y)

    def _end_drag(self, event):
        if not self._drag_data.get('line'): return
        self.canvas.delete(self._drag_data['line'])
        overlapping = self.canvas.find_overlapping(event.x, event.y, event.x, event.y)
        target_node = None
        for item in overlapping:
            tags = self.canvas.gettags(item)
            for tag in tags:
                if tag.startswith("node_") and not tag.endswith("_text"):
                    target_node = tag.split("node_")[1]
                    break
            if target_node: break
        start_node = self._drag_data['start_node']
        if target_node and target_node != start_node:
            exists = any(
                t.get('from') == start_node and t.get('to') == target_node for t in self.map_data['transitions'])
            if not exists:
                new_transition = {'from': start_node, 'to': target_node, 'task': ''}
                self.map_data['transitions'].append(new_transition)
                self.save()
                self._recalculate_and_draw()
        self._drag_data = {'start_node': None, 'line': None}

    def _on_canvas_click(self, event):
        overlapping = self.canvas.find_overlapping(event.x, event.y, event.x, event.y)
        if not overlapping: self._on_item_click(None)

    def _on_item_click(self, item_identifier):
        if self.selected_item: self._highlight_item(self.selected_item, 'blue', 1.5)
        self.selected_item = item_identifier
        if self.selected_item: self._highlight_item(self.selected_item, 'red', 5.0)
        self._update_properties_panel(item_identifier)

    def _highlight_item(self, item_identifier, color, width):
        if not item_identifier: return
        item_type, name = item_identifier.split(':', 1)
        start_state = self.map_data.get('start_state')
        if item_type == 'state' and name in self.canvas_items:
            outline_color = 'green' if name == start_state and color == 'blue' else color
            self.canvas.itemconfig(self.canvas_items[name]['node_id'], outline=outline_color, width=width)
        elif item_type == 'transition':
            idx = int(name)
            if idx in self.line_items:
                self.canvas.itemconfig(self.line_items[idx], fill=color)

    def _update_properties_panel(self, item_identifier):
        for widget in self.properties_frame.winfo_children(): widget.destroy()
        if not item_identifier:
            ttk.Label(self.properties_frame, text="在左侧画布上选择一个元素进行编辑。").pack(pady=20, padx=5)
            return
        item_type, name = item_identifier.split(':', 1)
        if item_type == 'state':
            self._create_state_editor(name)
        elif item_type == 'transition':
            self._create_transition_editor(int(name))

    def _create_state_editor(self, state_name):
        state_data = self.map_data.get('states', {}).get(state_name, {})
        ttk.Label(self.properties_frame, text=f"状态: {state_name}", font=("", 11, "bold")).pack(fill=tk.X,
                                                                                                 pady=(0, 10))
        editor_frame = ttk.Frame(self.properties_frame)
        editor_frame.pack(fill=tk.X)
        ttk.Label(editor_frame, text="检查任务:").grid(row=0, column=0, sticky='w', padx=(0, 5))
        task_var = tk.StringVar(value=state_data.get('check', {}).get('task', ''))
        task_combo = ttk.Combobox(editor_frame, textvariable=task_var, values=self.plan_tasks, state="readonly")
        task_combo.grid(row=0, column=1, sticky='ew')
        editor_frame.columnconfigure(1, weight=1)
        task_combo.bind("<<ComboboxSelected>>", lambda e: self._on_state_check_task_change(state_name, task_var.get()))

    def _create_transition_editor(self, transition_index):
        transition_data = self.map_data['transitions'][transition_index]
        source, target = transition_data.get('from'), transition_data.get('to')
        ttk.Label(self.properties_frame, text=f"转换: {source} -> {target}", font=("", 11, "bold")).pack(fill=tk.X,
                                                                                                         pady=(0, 10))
        editor_frame = ttk.Frame(self.properties_frame)
        editor_frame.pack(fill=tk.X)
        ttk.Label(editor_frame, text="执行任务:").grid(row=0, column=0, sticky='w', padx=(0, 5))
        task_var = tk.StringVar(value=transition_data.get('task', ''))
        task_combo = ttk.Combobox(editor_frame, textvariable=task_var, values=self.plan_tasks, state="readonly")
        task_combo.grid(row=0, column=1, sticky='ew')
        editor_frame.columnconfigure(1, weight=1)
        task_combo.bind("<<ComboboxSelected>>",
                        lambda e: self._on_transition_task_change(transition_index, task_var.get()))

    def _on_state_check_task_change(self, state_name, new_task):
        self.map_data['states'][state_name]['check'] = {'task': new_task}
        self.save()

    def _on_transition_task_change(self, index, new_task):
        self.map_data['transitions'][index]['task'] = new_task
        self.save()
        self._draw_canvas()

    def save(self):
        try:
            new_content = yaml.dump(self.map_data, allow_unicode=True, sort_keys=False, default_flow_style=False)
            self.scheduler.save_file_content(self.plan_name, self.file_path, new_content)
        except Exception as e:
            logger.error(f"保存 world_map.yaml 失败: {e}", exc_info=True)
            raise

