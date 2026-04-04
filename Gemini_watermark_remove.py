#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini 水印去除工具
支持单个文件和文件夹批处理
"""

import os
import sys
import threading
import json
import datetime
from tkinter import (
    Tk, Frame, Label, Button, filedialog, messagebox,
    Listbox, Scrollbar, ttk, BooleanVar, StringVar
)


def get_script_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def get_config_dir():
    if getattr(sys, 'frozen', False):
        config_dir = os.path.join(get_script_dir(), 'config')
    else:
        if sys.platform == 'win32':
            config_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'GeminiWatermarkRemover')
        elif sys.platform == 'darwin':
            config_dir = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'GeminiWatermarkRemover')
        else:
            config_dir = os.path.join(os.path.expanduser('~'), '.config', 'GeminiWatermarkRemover')

    if not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)
    return config_dir


SCRIPT_DIR = get_script_dir()
CONFIG_FILE = os.path.join(get_config_dir(), 'config.json')

from PIL import Image, ImageTk
import numpy as np


class Config:
    def __init__(self):
        self.config = {
            'default_save_dir': '',
            'use_default_dir': False,
            'use_suffix': True,
            'suffix': '_non'
        }
        self.load()
        if not os.path.exists(CONFIG_FILE):
            self.save()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self.config.update(json.load(f))
            except:
                pass

    def save(self):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save()


class WatermarkRemover:
    def __init__(self):
        self.alpha_maps = {}
        self.watermark_images = {}
        self._load_watermarks()

    def _load_watermarks(self):
        watermark_96_path = get_resource_path('bg_96.png')
        watermark_48_path = get_resource_path('bg_48.png')
        self.watermark_images[96] = Image.open(watermark_96_path).convert('RGBA')
        self.watermark_images[48] = Image.open(watermark_48_path).convert('RGBA')

    def _get_alpha_map(self, size):
        if size in self.alpha_maps:
            return self.alpha_maps[size]

        watermark = self.watermark_images[size]
        width, height = watermark.size
        watermark_array = np.array(watermark)

        alpha_map = np.zeros((height, width), dtype=np.float32)
        for y in range(height):
            for x in range(width):
                r = watermark_array[y, x, 0]
                g = watermark_array[y, x, 1]
                b = watermark_array[y, x, 2]
                max_val = max(r, g, b)
                alpha_map[y, x] = max_val / 255.0

        self.alpha_maps[size] = alpha_map
        return alpha_map

    def _get_watermark_info(self, img_width, img_height):
        if img_width > 1024 and img_height > 1024:
            return {
                'logo_size': 96,
                'margin_right': 64,
                'margin_bottom': 64
            }
        else:
            return {
                'logo_size': 48,
                'margin_right': 32,
                'margin_bottom': 32
            }

    def _calculate_position(self, img_width, img_height, config):
        return {
            'x': img_width - config['margin_right'] - config['logo_size'],
            'y': img_height - config['margin_bottom'] - config['logo_size'],
            'width': config['logo_size'],
            'height': config['logo_size']
        }

    def remove_watermark(self, image):
        img_array = np.array(image.convert('RGBA'))
        height, width = img_array.shape[:2]

        watermark_info = self._get_watermark_info(width, height)
        position = self._calculate_position(width, height, watermark_info)
        alpha_map = self._get_alpha_map(watermark_info['logo_size'])

        x_start = position['x']
        y_start = position['y']

        ALPHA_NOISE_FLOOR = 3.0 / 255.0
        ALPHA_THRESHOLD = 0.002
        MAX_ALPHA = 0.99
        LOGO_VALUE = 255

        for y in range(position['height']):
            for x in range(position['width']):
                img_y = y_start + y
                img_x = x_start + x

                if img_y >= height or img_x >= width:
                    continue

                raw_alpha = alpha_map[y, x]

                signal_alpha = max(0, raw_alpha - ALPHA_NOISE_FLOOR)

                if signal_alpha < ALPHA_THRESHOLD:
                    continue

                alpha = min(raw_alpha, MAX_ALPHA)
                m = 1.0 - alpha

                for c in range(3):
                    val = img_array[img_y, img_x, c]
                    new_val = (val - alpha * LOGO_VALUE) / m
                    new_val = max(0, min(255, round(new_val)))
                    img_array[img_y, img_x, c] = new_val

        return Image.fromarray(img_array, 'RGBA')


class WatermarkRemoverApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Gemini 水印去除工具")
        self.root.geometry("900x600")
        self.root.minsize(800, 500)

        self._set_window_icon()

        self.config = Config()
        self.remover = WatermarkRemover()
        self.current_image = None
        self.processed_image = None
        self.current_filepath = None
        self.batch_files = []
        self.processing = False
        self.current_panel = 'single'
        self.batch_output_dir = None

        self.center_window()
        self._setup_ui()

    def _set_window_icon(self):
        icon_path = get_resource_path('app.ico')
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except:
                pass

    def center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def _setup_ui(self):
        main_container = Frame(self.root)
        main_container.pack(fill='both', expand=True)

        left_panel = Frame(main_container, width=200, bg='#e8e8e8', padx=10, pady=10)
        left_panel.pack(side='left', fill='y')
        left_panel.pack_propagate(False)

        title_label = Label(left_panel, text="菜单", bg='#e8e8e8', font=('Microsoft YaHei', 12, 'bold'))
        title_label.pack(pady=(0, 15))

        self.single_file_btn = Button(
            left_panel,
            text="单个文件处理",
            command=lambda: self.show_panel('single'),
            width=20,
            height=2,
            cursor='hand2'
        )
        self.single_file_btn.pack(pady=5)

        self.batch_btn = Button(
            left_panel,
            text="文件夹批处理",
            command=lambda: self.show_panel('batch'),
            width=20,
            height=2,
            cursor='hand2'
        )
        self.batch_btn.pack(pady=5)

        self.settings_btn = Button(
            left_panel,
            text="设置",
            command=lambda: self.show_panel('settings'),
            width=20,
            height=2,
            cursor='hand2'
        )
        self.settings_btn.pack(pady=5)

        self.right_panel = Frame(main_container, padx=20, pady=20)
        self.right_panel.pack(side='right', fill='both', expand=True)

        bottom_bar = Frame(self.root, height=30, bg='#f0f0f0')
        bottom_bar.pack(side='bottom', fill='x')
        bottom_bar.pack_propagate(False)

        version_label = Label(bottom_bar, text="v1.0", bg='#f0f0f0', fg='#666666', font=('Microsoft YaHei', 9))
        version_label.pack(side='left', padx=10)

        self.show_panel('single')

    def clear_right_panel(self):
        for widget in self.right_panel.winfo_children():
            widget.destroy()

    def show_panel(self, panel_name):
        self.current_panel = panel_name
        self.clear_right_panel()

        if panel_name == 'single':
            self.show_single_file_panel()
        elif panel_name == 'batch':
            self.show_batch_panel()
        elif panel_name == 'settings':
            self.show_settings_panel()

    def show_single_file_panel(self):
        title_label = Label(self.right_panel, text="单个文件处理", font=('Microsoft YaHei', 14, 'bold'))
        title_label.pack(pady=(0, 20))

        btn_frame = Frame(self.right_panel)
        btn_frame.pack(pady=10)

        self.select_btn = Button(
            btn_frame,
            text="选择图片",
            command=self._select_single_image,
            width=15,
            height=2
        )
        self.select_btn.pack(side='left', padx=5)

        self.process_single_btn = Button(
            btn_frame,
            text="去除水印",
            command=self._process_single_image,
            width=15,
            height=2,
            state='disabled'
        )
        self.process_single_btn.pack(side='left', padx=5)

        self.save_single_btn = Button(
            btn_frame,
            text="保存图片",
            command=self._save_single_image,
            width=15,
            height=2,
            state='disabled'
        )
        self.save_single_btn.pack(side='left', padx=5)

        self.image_preview_label = Label(self.right_panel, text="未选择图片", font=('Microsoft YaHei', 10))
        self.image_preview_label.pack(pady=20)

        self.single_status_label = Label(self.right_panel, text="", font=('Microsoft YaHei', 10))
        self.single_status_label.pack(pady=10)

    def show_batch_panel(self):
        title_label = Label(self.right_panel, text="文件夹批处理", font=('Microsoft YaHei', 14, 'bold'))
        title_label.pack(pady=(0, 20))

        btn_frame = Frame(self.right_panel)
        btn_frame.pack(pady=10)

        self.select_folder_btn = Button(
            btn_frame,
            text="选择文件夹",
            command=self._select_folder,
            width=15,
            height=2
        )
        self.select_folder_btn.pack(side='left', padx=5)

        self.start_batch_btn = Button(
            btn_frame,
            text="开始批处理",
            command=self._start_batch_process,
            width=15,
            height=2,
            state='disabled'
        )
        self.start_batch_btn.pack(side='left', padx=5)

        list_frame = Frame(self.right_panel)
        list_frame.pack(fill='both', expand=True, pady=10)

        scrollbar = Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')

        self.file_listbox = Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            font=('Microsoft YaHei', 9),
            height=15
        )
        self.file_listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.file_listbox.yview)

        self.batch_status_label = Label(self.right_panel, text="", font=('Microsoft YaHei', 10))
        self.batch_status_label.pack(pady=10)

        self.progress = ttk.Progressbar(
            self.right_panel,
            orient='horizontal',
            length=400,
            mode='determinate'
        )
        self.progress.pack(pady=5)

    def show_settings_panel(self):
        title_label = Label(self.right_panel, text="设置", font=('Microsoft YaHei', 14, 'bold'))
        title_label.pack(pady=(0, 20))

        settings_frame = Frame(self.right_panel)
        settings_frame.pack(fill='x', pady=10)

        self.use_default_var = BooleanVar(value=self.config.get('use_default_dir', False))

        use_default_check = ttk.Checkbutton(
            settings_frame,
            text="自动保存到默认保存目录",
            variable=self.use_default_var,
            command=self._on_auto_save_toggle
        )
        use_default_check.pack(anchor='w', pady=5)

        dir_frame = Frame(settings_frame)
        dir_frame.pack(fill='x', pady=10)

        Label(dir_frame, text="默认保存目录:", font=('Microsoft YaHei', 10)).pack(side='left', padx=(0, 10))

        self.default_dir_var = StringVar(value=self.config.get('default_save_dir', ''))
        self.default_dir_entry = ttk.Entry(dir_frame, textvariable=self.default_dir_var, width=40)
        self.default_dir_entry.pack(side='left', padx=(0, 10))
        self.default_dir_entry.bind('<KeyRelease>', self._on_dir_change)

        browse_dir_btn = Button(
            dir_frame,
            text="浏览",
            command=self._browse_default_dir,
            width=10
        )
        browse_dir_btn.pack(side='left')

        suffix_frame = Frame(settings_frame)
        suffix_frame.pack(fill='x', pady=10)

        self.use_suffix_var = BooleanVar(value=self.config.get('use_suffix', True))
        use_suffix_check = ttk.Checkbutton(
            suffix_frame,
            text="输出文件名添加后缀",
            variable=self.use_suffix_var,
            command=self._on_use_suffix_toggle
        )
        use_suffix_check.pack(anchor='w', pady=5)

        suffix_input_frame = Frame(suffix_frame)
        suffix_input_frame.pack(fill='x', pady=5)

        Label(suffix_input_frame, text="后缀:", font=('Microsoft YaHei', 10)).pack(side='left', padx=(0, 10))

        self.suffix_var = StringVar(value=self.config.get('suffix', '_non'))
        self.suffix_entry = ttk.Entry(suffix_input_frame, textvariable=self.suffix_var, width=20)
        self.suffix_entry.pack(side='left', padx=(0, 10))
        self.suffix_entry.bind('<KeyRelease>', self._on_suffix_change)

        self._toggle_default_dir()
        self._toggle_suffix_entry()

    def _on_auto_save_toggle(self):
        self.config.set('use_default_dir', self.use_default_var.get())
        self._toggle_default_dir()

    def _on_use_suffix_toggle(self):
        self.config.set('use_suffix', self.use_suffix_var.get())
        self._toggle_suffix_entry()

    def _toggle_suffix_entry(self):
        if hasattr(self, 'suffix_entry'):
            state = 'normal' if self.use_suffix_var.get() else 'disabled'
            self.suffix_entry.config(state=state)

    def _on_dir_change(self, event=None):
        self.config.set('default_save_dir', self.default_dir_var.get())

    def _on_suffix_change(self, event=None):
        self.config.set('suffix', self.suffix_var.get())

    def _toggle_default_dir(self):
        if hasattr(self, 'default_dir_entry'):
            state = 'normal' if self.use_default_var.get() else 'disabled'
            self.default_dir_entry.config(state=state)

    def _browse_default_dir(self):
        folder_path = filedialog.askdirectory(title="选择默认保存目录")
        if folder_path:
            self.default_dir_var.set(folder_path)
            self.config.set('default_save_dir', folder_path)

    def _select_single_image(self):
        file_path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.bmp *.gif"),
                ("所有文件", "*.*")
            ]
        )

        if file_path:
            try:
                self.current_filepath = file_path
                self.current_image = Image.open(file_path)

                self._display_preview(self.current_image)
                self.process_single_btn.config(state='normal')
                self.save_single_btn.config(state='disabled')
                self.single_status_label.config(text=f"已加载: {os.path.basename(file_path)}")
                self.processed_image = None
            except Exception as e:
                messagebox.showerror("错误", f"加载图片失败: {str(e)}")

    def _display_preview(self, img):
        display_img = img.copy()
        display_img.thumbnail((500, 350))
        photo = ImageTk.PhotoImage(display_img)
        self.image_preview_label.config(image=photo, text="")
        self.image_preview_label.image = photo

    def _process_single_image(self):
        if not self.current_image:
            return

        try:
            self.single_status_label.config(text="处理中...")
            self.root.update()

            self.processed_image = self.remover.remove_watermark(self.current_image)

            self._display_preview(self.processed_image)
            self.save_single_btn.config(state='normal')
            self.single_status_label.config(text="水印去除成功！")
        except Exception as e:
            messagebox.showerror("错误", f"处理图片失败: {str(e)}")
            self.single_status_label.config(text="处理失败")

    def _get_output_filename(self, filepath):
        filename = os.path.basename(filepath)
        base, ext = os.path.splitext(filename)
        if self.config.get('use_suffix', True):
            suffix = self.config.get('suffix', '_non')
            return f"{base}{suffix}{ext}"
        return filename

    def _save_single_image(self):
        if not self.processed_image:
            return

        use_default = self.config.get('use_default_dir', False)
        default_dir = self.config.get('default_save_dir', '')

        if use_default and default_dir and os.path.exists(default_dir):
            if self.current_filepath:
                output_filename = self._get_output_filename(self.current_filepath)
                output_path = os.path.join(default_dir, output_filename)
            else:
                output_path = os.path.join(default_dir, "图片_无水印.png")

            try:
                if output_path.lower().endswith(('.jpg', '.jpeg')):
                    save_img = self.processed_image.convert('RGB')
                else:
                    save_img = self.processed_image
                save_img.save(output_path)
                self.single_status_label.config(text=f"已保存到: {os.path.basename(output_path)}")
                messagebox.showinfo("成功", "图片保存成功！")
            except Exception as e:
                messagebox.showerror("错误", f"保存图片失败: {str(e)}")
        else:
            if self.current_filepath:
                output_filename = self._get_output_filename(self.current_filepath)
                default_dir = os.path.dirname(self.current_filepath)
                default_path = os.path.join(default_dir, output_filename)
            else:
                default_path = "图片_无水印.png"

            file_path = filedialog.asksaveasfilename(
                title="保存图片",
                defaultextension=".png",
                initialfile=os.path.basename(default_path),
                initialdir=os.path.dirname(default_path) if self.current_filepath else None,
                filetypes=[
                    ("PNG 文件", "*.png"),
                    ("JPEG 文件", "*.jpg"),
                    ("所有文件", "*.*")
                ]
            )

            if file_path:
                try:
                    if file_path.lower().endswith(('.jpg', '.jpeg')):
                        save_img = self.processed_image.convert('RGB')
                    else:
                        save_img = self.processed_image
                    save_img.save(file_path)
                    self.single_status_label.config(text=f"已保存到: {os.path.basename(file_path)}")
                    messagebox.showinfo("成功", "图片保存成功！")
                except Exception as e:
                    messagebox.showerror("错误", f"保存图片失败: {str(e)}")

    def _select_folder(self):
        # 重置状态
        self.batch_files = []
        self.file_listbox.delete(0, 'end')
        self.batch_status_label.config(text="")
        self.progress['value'] = 0
        self.start_batch_btn.config(state='disabled')
        
        folder_path = filedialog.askdirectory(title="选择包含图片的文件夹")

        if folder_path:
            image_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
            for filename in os.listdir(folder_path):
                if filename.lower().endswith(image_extensions):
                    self.batch_files.append(os.path.join(folder_path, filename))
                    self.file_listbox.insert('end', filename)

            if self.batch_files:
                self.batch_status_label.config(text=f"找到 {len(self.batch_files)} 张图片")
                self.start_batch_btn.config(state='normal')
            else:
                self.batch_status_label.config(text="未找到图片文件")
                messagebox.showwarning("警告", "所选文件夹中没有找到图片文件")

    def _confirm_batch_output(self):
        use_default = self.config.get('use_default_dir', False)
        default_dir = self.config.get('default_save_dir', '')

        if use_default and default_dir and os.path.exists(default_dir):
            result = messagebox.askyesnocancel(
                "确认输出目录",
                f"已设置默认保存目录：\n{default_dir}\n\n- 点击'是'：使用默认目录\n- 点击'否'：使用默认输出目录（程序同级 data 文件夹）\n- 点击'取消'：取消批处理"
            )
            if result is None:  # 用户点击了取消
                return False
            elif result:
                self.batch_output_dir = default_dir
                return True
            else:
                self.batch_output_dir = self._get_default_batch_output_dir()
                return True
        else:
            self.batch_output_dir = self._get_default_batch_output_dir()
            result = messagebox.askokcancel(
                "输出目录",
                f"未设置默认保存目录，将输出到：\n{self.batch_output_dir}\n\n按时间创建子文件夹\n\n点击'确定'继续，点击'取消'取消批处理"
            )
            return result

    def _get_default_batch_output_dir(self):
        base_dir = os.path.join(get_script_dir(), 'data')
        if not os.path.exists(base_dir):
            os.makedirs(base_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        return os.path.join(base_dir, timestamp)

    def _start_batch_process(self):
        if not self.batch_files or self.processing:
            return

        if not self._confirm_batch_output():
            return

        self.processing = True
        self.start_batch_btn.config(state='disabled', text="处理中...")
        self.select_folder_btn.config(state='disabled')
        self.progress['maximum'] = len(self.batch_files)
        self.progress['value'] = 0

        thread = threading.Thread(target=self._batch_process_worker)
        thread.daemon = True
        thread.start()

    def _batch_process_worker(self):
        success_count = 0
        fail_count = 0

        output_dir = self.batch_output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        for i, file_path in enumerate(self.batch_files):
            try:
                img = Image.open(file_path)
                processed_img = self.remover.remove_watermark(img)

                output_filename = self._get_output_filename(file_path)
                output_path = os.path.join(output_dir, output_filename)

                if output_path.lower().endswith(('.jpg', '.jpeg')):
                    processed_img = processed_img.convert('RGB')

                processed_img.save(output_path)
                success_count += 1

                self.root.after(0, lambda idx=i: self.file_listbox.itemconfig(idx, {'fg': 'green'}))
            except Exception as e:
                fail_count += 1
                self.root.after(0, lambda idx=i: self.file_listbox.itemconfig(idx, {'fg': 'red'}))

            self.root.after(0, lambda val=i+1: self.progress.configure(value=val))
            self.root.after(0, lambda: self.batch_status_label.config(
                text=f"处理中... {i+1}/{len(self.batch_files)}"
            ))

        self.processing = False
        self.root.after(0, lambda: self._batch_finished(success_count, fail_count, output_dir))

    def _batch_finished(self, success_count, fail_count, output_dir):
        self.start_batch_btn.config(state='normal', text="开始批处理")
        self.select_folder_btn.config(state='normal')
        self.batch_status_label.config(
            text=f"批处理完成！成功: {success_count}, 失败: {fail_count}"
        )
        messagebox.showinfo("完成", f"批处理完成！\n成功: {success_count}\n失败: {fail_count}\n\n输出目录: {output_dir}")


def main():
    root = Tk()
    app = WatermarkRemoverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
