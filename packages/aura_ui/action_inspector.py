# src/ui/action_inspector.py

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import cv2
import numpy as np

class ActionInspectorWindow(tk.Toplevel):
    def __init__(self, parent, debug_bundle):
        super().__init__(parent)
        self.title("动作检查器")
        self.geometry("1000x700")

        self.debug_bundle = debug_bundle
        self._create_widgets()
        self._display_results()

    def _create_widgets(self):
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- 左侧：图像面板 ---
        image_frame = ttk.Frame(main_pane)
        main_pane.add(image_frame, weight=3)

        source_frame = ttk.LabelFrame(image_frame, text="源图像 (截图)")
        source_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        self.source_label = ttk.Label(source_frame, background="black")
        self.source_label.pack(fill=tk.BOTH, expand=True)

        template_frame = ttk.LabelFrame(image_frame, text="模板图像")
        template_frame.pack(fill=tk.X, pady=(5, 0))
        self.template_label = ttk.Label(template_frame, background="black")
        self.template_label.pack(pady=5)

        # --- 右侧：信息面板 ---
        info_frame = ttk.Frame(main_pane, padding=(10, 0, 0, 0))
        main_pane.add(info_frame, weight=1)

        self.info_tree = ttk.Treeview(info_frame, columns=("Property", "Value"), show="headings")
        self.info_tree.heading("Property", text="属性")
        self.info_tree.heading("Value", text="值")
        self.info_tree.column("Property", width=120)
        self.info_tree.pack(fill=tk.BOTH, expand=True)

    def _numpy_to_photoimage(self, np_array, max_size=(600, 400)):
        if np_array is None: return None
        rgb_array = cv2.cvtColor(np_array, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb_array)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)

    def _display_results(self):
        result = self.debug_bundle
        params = result.debug_info.get("params", {})

        self.info_tree.insert("", "end", values=("结果", "成功" if result.found else "失败"))
        self.info_tree.insert("", "end", values=("置信度", f"{result.confidence:.4f}" if result.confidence > 0 else "N/A"))
        self.info_tree.insert("", "end", values=("匹配矩形", result.rect if result.found else "N/A"))

        if "template" in params:
            self.info_tree.insert("", "end", values=("阈值", params.get("threshold")))
            self.info_tree.insert("", "end", values=("模板路径", params.get("template")))
            template_img_np = result.debug_info.get("template_image")
            if template_img_np is not None:
                self.template_photo = self._numpy_to_photoimage(template_img_np, max_size=(200, 150))
                self.template_label.config(image=self.template_photo)
        elif "text_to_find" in params:
            self.info_tree.insert("", "end", values=("匹配模式", params.get("match_mode")))
            self.info_tree.insert("", "end", values=("目标文本", params.get("text_to_find")))
            if result.found:
                self.info_tree.insert("", "end", values=("识别文本", result.text))
            self.template_label.config(text=f'目标文本:\n"{params.get("text_to_find")}"', font=("", 12, "bold"))

        source_img_np = result.debug_info.get("source_image")
        if source_img_np is not None:
            img_to_draw_on = source_img_np.copy()
            rect_to_draw, color = (None, (0, 0, 0))
            if result.found:
                rect_to_draw, color = (result.rect, (0, 255, 0))
                self.info_tree.item(self.info_tree.get_children()[0], values=("结果", "成功 ✅"))
            elif "best_match_rect_on_fail" in result.debug_info:
                rect_to_draw, color = (result.debug_info["best_match_rect_on_fail"], (0, 0, 255))
                self.info_tree.item(self.info_tree.get_children()[0], values=("结果", "失败 ❌"))

            if rect_to_draw:
                p1 = (rect_to_draw[0], rect_to_draw[1])
                p2 = (rect_to_draw[0] + rect_to_draw[2], rect_to_draw[1] + rect_to_draw[3])
                cv2.rectangle(img_to_draw_on, p1, p2, color, 2)

            if not result.found and "all_recognized_results" in result.debug_info:
                self.info_tree.item(self.info_tree.get_children()[0], values=("结果", "失败 ❌"))
                for ocr_item in result.debug_info["all_recognized_results"]:
                    r = ocr_item.rect
                    p1, p2 = ((r[0], r[1]), (r[0] + r[2], r[1] + r[3]))
                    cv2.rectangle(img_to_draw_on, p1, p2, (128, 128, 128), 1)
                    cv2.putText(img_to_draw_on, ocr_item.text, (p1[0], p1[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

            self.source_photo = self._numpy_to_photoimage(img_to_draw_on)
            self.source_label.config(image=self.source_photo)
