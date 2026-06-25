from __future__ import annotations

import datetime
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from tkinter import (
    BooleanVar,
    Button,
    Canvas,
    Checkbutton,
    Frame,
    Label,
    Listbox,
    Scrollbar,
    StringVar,
    Tk,
    filedialog,
    messagebox,
    ttk,
)

from PIL import Image, ImageTk

from . import __version__
from .config import ConfigStore
from .dialogs import ImagePreviewDialog, WatermarkConfirmDialog
from .paths import data_dir, resource_path
from .theme import resolve_theme
from .ui_queue import UiQueue
from .watermark import WatermarkMatch, WatermarkRemover


IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
UI_FONT_NAME = 'Microsoft YaHei UI'
BASE_FONT = (UI_FONT_NAME, 10)
BOLD_FONT = (UI_FONT_NAME, 10, 'bold')
MENU_TITLE_FONT = (UI_FONT_NAME, 15, 'bold')
PANEL_TITLE_FONT = (UI_FONT_NAME, 17, 'bold')
THEME_LABELS = {
    '跟随系统': 'system',
    '浅色': 'light',
    '深色': 'dark',
}
THEME_NAMES = {mode: label for label, mode in THEME_LABELS.items()}


@dataclass(frozen=True)
class BatchFailure:
    filename: str
    reason: str


class WatermarkRemoverApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title('Gemini 水印去除工具')
        self.root.geometry('1000x720')
        self.root.minsize(860, 600)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self._apply_tk_scaling()

        self.config = ConfigStore()
        self.remover = WatermarkRemover()
        self.palette = resolve_theme(self.config.get('theme_mode', 'system'))
        self.current_panel = 'single'
        self.current_image: Image.Image | None = None
        self.processed_image: Image.Image | None = None
        self.current_filepath: str | None = None
        self.preview_dialog: ImagePreviewDialog | None = None
        self.batch_files: list[str] = []
        self.batch_output_dir: Path | None = None
        self.batch_failures: list[BatchFailure] = []
        self.processing = False
        self.menu_buttons: list[tuple[str, Button]] = []
        self.preview_resize_job: str | None = None
        self.preview_cache_key: tuple[int, int, int] | None = None
        self.settings_scroll_container: Frame | None = None
        self.ui_queue = UiQueue(self.root)

        self._set_icon()
        self._bind_global_mousewheel()
        self._setup_styles()
        self._setup_ui()
        self.ui_queue.start()
        self.center_window()
        self.show_panel('single')

    def _set_icon(self) -> None:
        icon_path = resource_path('app.ico')
        if icon_path.exists():
            try:
                self.root.iconbitmap(str(icon_path))
            except Exception:
                pass

    def _apply_tk_scaling(self) -> None:
        dpi = self.root.winfo_fpixels('1i')
        if dpi > 0:
            self.root.tk.call('tk', 'scaling', dpi / 72.0)

    def _bind_global_mousewheel(self) -> None:
        self.root.bind_all('<MouseWheel>', self._on_global_mousewheel, add='+')
        self.root.bind_all('<Button-4>', lambda event: self._on_global_mousewheel(event, -1), add='+')
        self.root.bind_all('<Button-5>', lambda event: self._on_global_mousewheel(event, 1), add='+')

    def _on_global_mousewheel(self, event, direction: int | None = None):
        if self.current_panel != 'settings' or self.settings_scroll_container is None:
            return None
        if not self._is_descendant(event.widget, self.settings_scroll_container):
            return None

        if direction is None:
            if event.delta == 0:
                return 'break'
            direction = -1 if event.delta > 0 else 1
        self.settings_canvas.yview_scroll(direction, 'units')
        return 'break'

    @staticmethod
    def _is_descendant(widget, parent) -> bool:
        while widget is not None:
            if widget == parent:
                return True
            widget = getattr(widget, 'master', None)
        return False

    def _post_to_ui(self, callback) -> None:
        self.ui_queue.post(callback)

    def _setup_styles(self) -> None:
        self.root.option_add('*Font', BASE_FONT)
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except Exception:
            pass

        palette = self.palette
        style.configure(
            'App.TCheckbutton',
            background=palette.surface,
            foreground=palette.text,
            font=BASE_FONT,
        )
        style.map(
            'App.TCheckbutton',
            background=[('active', palette.surface)],
            foreground=[('disabled', palette.muted_text)],
        )
        style.configure(
            'App.TEntry',
            fieldbackground=palette.input_background,
            foreground=palette.text,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            font=BASE_FONT,
        )
        style.map(
            'App.TEntry',
            fieldbackground=[('disabled', palette.background)],
            foreground=[('disabled', palette.muted_text)],
        )
        style.configure(
            'App.TCombobox',
            fieldbackground=palette.input_background,
            background=palette.input_background,
            foreground=palette.text,
            arrowcolor=palette.text,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            font=BASE_FONT,
        )
        style.map(
            'App.TCombobox',
            fieldbackground=[('readonly', palette.input_background)],
            foreground=[('readonly', palette.text)],
            selectbackground=[('readonly', palette.input_background)],
            selectforeground=[('readonly', palette.text)],
        )
        style.configure(
            'App.TLabelframe',
            background=palette.surface,
            foreground=palette.text,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            padding=14,
        )
        style.configure(
            'App.TLabelframe.Label',
            background=palette.surface,
            foreground=palette.text,
            font=BOLD_FONT,
        )
        style.configure(
            'App.Horizontal.TProgressbar',
            troughcolor=palette.surface,
            background=palette.accent,
            bordercolor=palette.border,
            lightcolor=palette.accent,
            darkcolor=palette.accent,
        )

    def center_window(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def _setup_ui(self) -> None:
        palette = self.palette
        self.root.configure(bg=palette.background)
        self.bottom_bar = Frame(self.root, height=34, bg=palette.sidebar)
        self.bottom_bar.pack(side='bottom', fill='x')
        self.bottom_bar.pack_propagate(False)
        Label(
            self.bottom_bar,
            text=f'v{__version__}',
            bg=palette.sidebar,
            fg=palette.muted_text,
        ).pack(side='left', padx=12, pady=7)

        main_container = Frame(self.root, bg=palette.background)
        main_container.pack(fill='both', expand=True)
        self.left_panel = Frame(main_container, width=200, bg=palette.sidebar, padx=12, pady=18)
        self.left_panel.pack(side='left', fill='y')
        self.left_panel.pack_propagate(False)
        Label(
            self.left_panel,
            text='菜单',
            bg=palette.sidebar,
            fg=palette.text,
            font=MENU_TITLE_FONT,
        ).pack(pady=(0, 20))

        self._menu_button('single', '单个文件处理').pack(fill='x', pady=5)
        self._menu_button('batch', '文件夹批处理').pack(fill='x', pady=5)
        self._menu_button('settings', '设置').pack(fill='x', pady=5)

        self.right_panel = Frame(main_container, bg=palette.background, padx=28, pady=22)
        self.right_panel.pack(side='right', fill='both', expand=True)

    def _menu_button(self, panel_name: str, text: str) -> Button:
        button = Button(
            self.left_panel,
            text=text,
            command=lambda: self.show_panel(panel_name),
            height=2,
            cursor='hand2',
            font=BASE_FONT,
        )
        self.menu_buttons.append((panel_name, button))
        return button

    def _refresh_menu_buttons(self) -> None:
        return

    def _button(
        self,
        parent,
        text: str,
        command,
        *,
        width: int | None = None,
        height: int = 1,
    ) -> Button:
        return Button(
            parent,
            text=text,
            command=command,
            width=width,
            height=height,
            cursor='hand2',
            font=BASE_FONT,
        )

    def _panel_title(self, title: str, subtitle: str = '') -> None:
        Label(
            self.right_panel,
            text=title,
            bg=self.palette.background,
            fg=self.palette.text,
            font=PANEL_TITLE_FONT,
        ).pack(pady=(0, 4))
        if subtitle:
            Label(
                self.right_panel,
                text=subtitle,
                bg=self.palette.background,
                fg=self.palette.muted_text,
            ).pack(pady=(0, 16))
        else:
            Frame(self.right_panel, bg=self.palette.background, height=16).pack()

    def clear_right_panel(self) -> None:
        self.settings_scroll_container = None
        self.preview_cache_key = None
        for widget in self.right_panel.winfo_children():
            widget.destroy()

    def show_panel(self, panel_name: str) -> None:
        if self.processing:
            return
        self.current_panel = panel_name
        self.clear_right_panel()
        self._refresh_menu_buttons()
        if panel_name == 'single':
            self._show_single_panel()
        elif panel_name == 'batch':
            self._show_batch_panel()
        elif panel_name == 'settings':
            self._show_settings_panel()

    def _show_single_panel(self) -> None:
        self._panel_title('单个文件处理')
        buttons = Frame(self.right_panel, bg=self.palette.background)
        buttons.pack(pady=(0, 12))
        self.select_single_button = self._button(buttons, '选择图片', self._select_single_image, width=15, height=2)
        self.select_single_button.pack(side='left', padx=5)
        self.process_single_button = self._button(
            buttons,
            '去除水印',
            self._process_single_image,
            width=15,
            height=2,
        )
        self.process_single_button.pack(side='left', padx=5)
        self.process_single_button.config(state='disabled')
        self.save_single_button = self._button(buttons, '保存图片', self._save_single_image, width=15, height=2)
        self.save_single_button.pack(side='left', padx=5)
        self.save_single_button.config(state='disabled')

        self.preview_container = Frame(
            self.right_panel,
            height=340,
            bg=self.palette.surface,
            highlightbackground=self.palette.border,
            highlightthickness=1,
        )
        self.preview_container.pack(fill='both', expand=True, padx=8, pady=10)
        self.preview_container.pack_propagate(False)
        self.preview_container.bind('<Configure>', self._queue_preview_refresh)
        self.preview_cache_key = None
        self.image_preview_label = Label(
            self.preview_container,
            text='未选择图片',
            bg=self.palette.surface,
            fg=self.palette.muted_text,
        )
        self.image_preview_label.pack(fill='both', expand=True)
        self.zoom_icon = Label(
            self.preview_container,
            text='🔍',
            bg=self.palette.surface,
            fg=self.palette.text,
            font=('Segoe UI Emoji', 15),
            cursor='hand2',
        )
        for widget in (self.preview_container, self.image_preview_label, self.zoom_icon):
            widget.bind('<Enter>', self._show_zoom_icon)
            widget.bind('<Leave>', self._hide_zoom_icon)
        self.image_preview_label.bind('<Button-1>', self._show_full_preview)
        self.zoom_icon.bind('<Button-1>', self._show_full_preview)

        self.single_status_label = Label(
            self.right_panel,
            text='',
            bg=self.palette.background,
            fg=self.palette.muted_text,
            anchor='center',
        )
        self.single_status_label.pack(fill='x', pady=(6, 0))
        if self.current_image is not None:
            self._display_preview(self.processed_image or self.current_image)
            self.process_single_button.config(state='normal')
            if self.processed_image is not None:
                self.save_single_button.config(state='normal')

    def _show_zoom_icon(self, event=None) -> None:
        if self.current_image is not None:
            self.zoom_icon.place(relx=1.0, rely=0.0, anchor='ne', x=-8, y=8)

    def _hide_zoom_icon(self, event=None) -> None:
        self.root.after(80, self._hide_zoom_icon_if_outside)

    def _hide_zoom_icon_if_outside(self) -> None:
        widget = self.root.winfo_containing(self.root.winfo_pointerx(), self.root.winfo_pointery())
        if widget not in (self.preview_container, self.image_preview_label, self.zoom_icon):
            self.zoom_icon.place_forget()

    def _show_full_preview(self, event=None) -> None:
        image = self.processed_image or self.current_image
        if image is None:
            return
        if self.preview_dialog is not None and self.preview_dialog.dialog.winfo_exists():
            self.preview_dialog.dialog.lift()
            self.preview_dialog.dialog.focus_force()
            return
        self.preview_dialog = ImagePreviewDialog(
            self.root,
            image,
            self.palette,
            on_close=self._clear_preview_dialog,
        )

    def _clear_preview_dialog(self) -> None:
        self.preview_dialog = None

    def _display_preview(self, image: Image.Image) -> None:
        available_width = max(120, self.preview_container.winfo_width() - 24)
        available_height = max(120, self.preview_container.winfo_height() - 24)
        cache_key = (id(image), available_width, available_height)
        if self.preview_cache_key == cache_key:
            self.image_preview_label.config(image=self.preview_photo, text='')
            return

        preview = image.copy()
        preview.thumbnail((available_width, available_height), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.preview_cache_key = cache_key
        self.image_preview_label.config(image=self.preview_photo, text='')

    def _queue_preview_refresh(self, event=None) -> None:
        if self.current_image is None:
            return
        if self.preview_resize_job is not None:
            self.root.after_cancel(self.preview_resize_job)
        self.preview_resize_job = self.root.after(80, self._refresh_preview_after_resize)

    def _refresh_preview_after_resize(self) -> None:
        self.preview_resize_job = None
        image = self.processed_image or self.current_image
        if image is not None and self.current_panel == 'single':
            self._display_preview(image)

    def _select_single_image(self) -> None:
        file_path = filedialog.askopenfilename(
            title='选择图片',
            filetypes=[('图片文件', '*.png *.jpg *.jpeg *.bmp *.gif'), ('所有文件', '*.*')],
        )
        if not file_path:
            return
        try:
            with Image.open(file_path) as image:
                self.current_image = image.copy()
            self.current_filepath = file_path
            self.processed_image = None
            self._display_preview(self.current_image)
            self.process_single_button.config(state='normal')
            self.save_single_button.config(state='disabled')
            self.single_status_label.config(text=f'已加载：{Path(file_path).name}')
        except Exception as error:
            messagebox.showerror('错误', f'加载图片失败：{error}')

    def _process_single_image(self) -> None:
        if self.current_image is None or self.processing:
            return
        self.processing = True
        self._set_navigation_enabled(False)
        self._set_single_controls_enabled(False)
        self.single_status_label.config(text='正在识别水印位置…')
        image = self.current_image
        thread = threading.Thread(target=self._single_detection_worker, args=(image,), daemon=True)
        thread.start()

    def _single_detection_worker(self, image: Image.Image) -> None:
        try:
            match, source = self.remover.find_known(image, self.config.watermark_positions())
            candidate = None if match is not None else self.remover.find_best(image)
            self._post_to_ui(
                lambda image=image, match=match, source=source, candidate=candidate: self._single_detection_finished(
                    image,
                    match,
                    source,
                    candidate,
                )
            )
        except Exception as error:
            self._post_to_ui(lambda reason=str(error): self._single_processing_failed(reason))

    def _single_detection_finished(
        self,
        image: Image.Image,
        match: WatermarkMatch | None,
        source: str | None,
        candidate: WatermarkMatch | None,
    ) -> None:
        if match is None:
            self.single_status_label.config(text='未匹配已记录位置，请确认候选位置')
            confirmed = WatermarkConfirmDialog(
                self.root,
                image,
                self.remover,
                candidate,
                self.palette,
            ).show()
            if confirmed is None:
                self.single_status_label.config(text='已取消处理')
                self._finish_single_processing()
                return
            self.config.save_watermark_position(confirmed, image.size)
            match = confirmed
            source = '新确认的位置'

        self.single_status_label.config(text='正在去除水印…')
        thread = threading.Thread(target=self._single_remove_worker, args=(image, match, source or '匹配位置'), daemon=True)
        thread.start()

    def _single_remove_worker(self, image: Image.Image, match: WatermarkMatch, source: str) -> None:
        try:
            processed_image = self.remover.remove(image, match)
            self._post_to_ui(
                lambda processed_image=processed_image, match=match, source=source: self._single_processing_finished(
                    processed_image,
                    match,
                    source,
                )
            )
        except Exception as error:
            self._post_to_ui(lambda reason=str(error): self._single_processing_failed(reason))

    def _single_processing_finished(self, processed_image: Image.Image, match: WatermarkMatch, source: str) -> None:
        self.processed_image = processed_image
        self._display_preview(self.processed_image)
        self.single_status_label.config(text=f'水印去除成功（{source}：{match.x}, {match.y}）')
        self._finish_single_processing()

    def _single_processing_failed(self, reason: str) -> None:
        self.single_status_label.config(text='处理失败')
        self._finish_single_processing()
        messagebox.showerror('错误', f'处理图片失败：{reason}')

    def _finish_single_processing(self) -> None:
        self.processing = False
        self._set_navigation_enabled(True)
        self._set_single_controls_enabled(True)

    def _set_single_controls_enabled(self, enabled: bool) -> None:
        if not hasattr(self, 'select_single_button'):
            return
        self.select_single_button.config(state='normal' if enabled else 'disabled')
        self.process_single_button.config(
            state='normal' if enabled and self.current_image is not None else 'disabled'
        )
        self.save_single_button.config(
            state='normal' if enabled and self.processed_image is not None else 'disabled'
        )

    def _output_filename(self, file_path: str) -> str:
        path = Path(file_path)
        if self.config.get('use_suffix', True):
            return f"{path.stem}{self.config.get('suffix', '_non')}{path.suffix}"
        return path.name

    @staticmethod
    def _ensure_output_does_not_replace_source(source_path: str | None, output_path: Path) -> None:
        if source_path is None:
            return
        if Path(source_path).resolve() == output_path.resolve():
            raise ValueError('输出路径与原图相同。请启用后缀或选择其他保存目录。')

    def _save_single_image(self) -> None:
        if self.processed_image is None:
            return
        default_dir = self.config.get('default_save_dir', '')
        if self.config.get('use_default_dir', False) and default_dir and Path(default_dir).is_dir():
            output_path = Path(default_dir) / self._output_filename(self.current_filepath or '图片.png')
        else:
            initial_dir = str(Path(self.current_filepath).parent) if self.current_filepath else str(Path.cwd())
            output_path_text = filedialog.asksaveasfilename(
                title='保存图片',
                initialdir=initial_dir,
                initialfile=self._output_filename(self.current_filepath or '图片.png'),
                defaultextension='.png',
                filetypes=[('PNG 文件', '*.png'), ('JPEG 文件', '*.jpg'), ('所有文件', '*.*')],
            )
            if not output_path_text:
                return
            output_path = Path(output_path_text)

        try:
            self._ensure_output_does_not_replace_source(self.current_filepath, output_path)
            image = self.processed_image.convert('RGB') if output_path.suffix.lower() in ('.jpg', '.jpeg') else self.processed_image
            image.save(output_path)
            self.single_status_label.config(text=f'已保存：{output_path.name}')
            messagebox.showinfo('成功', '图片保存成功')
        except Exception as error:
            messagebox.showerror('错误', f'保存图片失败：{error}')

    def _show_batch_panel(self) -> None:
        self._panel_title('文件夹批处理')
        buttons = Frame(self.right_panel, bg=self.palette.background)
        buttons.pack(pady=(0, 8))
        self.select_folder_button = self._button(buttons, '选择文件夹', self._select_batch_folder, width=15, height=2)
        self.select_folder_button.pack(side='left', padx=5)
        self.start_batch_button = self._button(
            buttons,
            '开始批处理',
            self._start_batch_process,
            width=15,
            height=2,
        )
        self.start_batch_button.pack(side='left', padx=5)
        self.start_batch_button.config(state='disabled')

        list_frame = Frame(self.right_panel, bg=self.palette.background)
        list_frame.pack(fill='both', expand=True, pady=10)
        scrollbar = Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')
        self.file_listbox = Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            font=BASE_FONT,
            bg=self.palette.input_background,
            fg=self.palette.text,
            selectbackground=self.palette.accent,
            selectforeground=self.palette.accent_text,
            highlightbackground=self.palette.border,
            highlightcolor=self.palette.accent,
            bd=1,
        )
        self.file_listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.file_listbox.yview)

        self.batch_status_label = Label(
            self.right_panel,
            text='',
            bg=self.palette.background,
            fg=self.palette.muted_text,
            anchor='center',
        )
        self.batch_status_label.pack(fill='x', pady=(0, 6))
        self.progress = ttk.Progressbar(
            self.right_panel,
            orient='horizontal',
            mode='determinate',
            style='App.Horizontal.TProgressbar',
        )
        self.progress.pack(fill='x', padx=80, pady=(0, 8))

    def _select_batch_folder(self) -> None:
        folder = filedialog.askdirectory(title='选择包含图片的文件夹')
        if not folder:
            return
        suffix = self.config.get('suffix', '_non') if self.config.get('use_suffix', True) else ''
        self.batch_files = []
        self.file_listbox.delete(0, 'end')
        skipped = 0
        for path in sorted(Path(folder).iterdir()):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if suffix and path.stem.endswith(suffix):
                skipped += 1
                continue
            self.batch_files.append(str(path))
            self.file_listbox.insert('end', path.name)

        self.progress['value'] = 0
        self.start_batch_button.config(state='normal' if self.batch_files else 'disabled')
        if self.batch_files:
            message = f'找到 {len(self.batch_files)} 张图片'
            if skipped:
                message += f'，已跳过 {skipped} 个输出文件'
            self.batch_status_label.config(text=message)
        else:
            self.batch_status_label.config(text='未找到可处理的图片文件')

    def _confirm_batch_output(self) -> bool:
        default_dir = self.config.get('default_save_dir', '')
        if self.config.get('use_default_dir', False) and default_dir and Path(default_dir).is_dir():
            self.batch_output_dir = Path(default_dir)
            return True
        output_dir = data_dir() / datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        if messagebox.askokcancel('输出目录', f'批处理结果将保存到：\n{output_dir}'):
            self.batch_output_dir = output_dir
            return True
        return False

    def _start_batch_process(self) -> None:
        if self.processing or not self.batch_files or not self._confirm_batch_output():
            return
        self.processing = True
        self.batch_failures = []
        self.start_batch_button.config(state='disabled', text='处理中…')
        self.select_folder_button.config(state='disabled')
        self._set_navigation_enabled(False)
        self.progress['maximum'] = len(self.batch_files)
        self.progress['value'] = 0
        thread = threading.Thread(target=self._batch_process_worker, daemon=True)
        thread.start()

    def _batch_process_worker(self) -> None:
        success_count = 0
        positions = self.config.watermark_positions()
        pending_success_indexes: list[int] = []
        last_ui_update = 0.0

        def flush_progress(value: int, force: bool = False) -> None:
            nonlocal pending_success_indexes, last_ui_update
            now = time.monotonic()
            if not force and len(pending_success_indexes) < 10 and now - last_ui_update < 0.12:
                return
            success_indexes = pending_success_indexes
            pending_success_indexes = []
            last_ui_update = now
            self._post_to_ui(
                lambda success_indexes=success_indexes, value=value: self._apply_batch_progress(
                    success_indexes,
                    value,
                )
            )

        assert self.batch_output_dir is not None
        try:
            self.batch_output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self._post_to_ui(lambda reason=str(error): self._batch_aborted(reason))
            return

        for index, file_path in enumerate(self.batch_files):
            path = Path(file_path)
            try:
                with Image.open(path) as image:
                    source_image = image.copy()
                match, _ = self.remover.find_known(source_image, positions)
                if match is None:
                    raise ValueError('未匹配默认位置或已记录位置')
                processed = self.remover.remove(source_image, match)
                output_path = self.batch_output_dir / self._output_filename(file_path)
                self._ensure_output_does_not_replace_source(file_path, output_path)
                if output_path.suffix.lower() in ('.jpg', '.jpeg'):
                    processed = processed.convert('RGB')
                processed.save(output_path)
                success_count += 1
                pending_success_indexes.append(index)
            except Exception as error:
                reason = str(error) or error.__class__.__name__
                self.batch_failures.append(BatchFailure(path.name, reason))
                self._post_to_ui(
                    lambda item=index, item_path=path.name, item_reason=reason: self._mark_batch_failure(
                        item,
                        item_path,
                        item_reason,
                    )
                )

            flush_progress(index + 1, force=bool(self.batch_failures and self.batch_failures[-1].filename == path.name))

        flush_progress(len(self.batch_files), force=True)
        self._post_to_ui(lambda success_count=success_count: self._batch_finished(success_count))

    def _apply_batch_progress(self, success_indexes: list[int], value: int) -> None:
        for index in success_indexes:
            self.file_listbox.itemconfig(index, {'fg': self.palette.success})
        self.progress.configure(value=value)
        self.batch_status_label.config(text=f'处理中… {value}/{len(self.batch_files)}')

    def _mark_batch_failure(self, index: int, filename: str, reason: str) -> None:
        self.file_listbox.delete(index)
        self.file_listbox.insert(index, f'{filename} — 失败：{reason}')
        self.file_listbox.itemconfig(index, {'fg': self.palette.error})

    def _batch_finished(self, success_count: int) -> None:
        self.processing = False
        self._set_navigation_enabled(True)
        self.start_batch_button.config(state='normal', text='开始批处理')
        self.select_folder_button.config(state='normal')
        failure_count = len(self.batch_failures)
        self.batch_status_label.config(text=f'批处理完成：成功 {success_count}，失败 {failure_count}')
        message = f'批处理完成\n成功：{success_count}\n失败：{failure_count}'
        if self.batch_failures:
            details = '\n'.join(f'{item.filename}：{item.reason}' for item in self.batch_failures[:10])
            if len(self.batch_failures) > 10:
                details += f'\n其余 {len(self.batch_failures) - 10} 项失败请查看列表。'
            message += f'\n\n失败原因：\n{details}'
        message += f'\n\n输出目录：{self.batch_output_dir}'
        messagebox.showinfo('完成', message)

    def _batch_aborted(self, reason: str) -> None:
        self.processing = False
        self._set_navigation_enabled(True)
        self.start_batch_button.config(state='normal', text='开始批处理')
        self.select_folder_button.config(state='normal')
        self.batch_status_label.config(text='批处理未开始')
        messagebox.showerror('批处理失败', f'无法创建输出目录：{reason}')

    def _set_navigation_enabled(self, enabled: bool) -> None:
        state = 'normal' if enabled else 'disabled'
        for _, button in self.menu_buttons:
            button.config(state=state)

    def _on_close(self) -> None:
        if self.processing:
            messagebox.showwarning('处理中', '批处理正在进行，请完成后再关闭程序。')
            return
        self.ui_queue.stop()
        self.root.destroy()

    def _settings_section(self, parent, title: str, description: str) -> ttk.LabelFrame:
        section = ttk.LabelFrame(parent, text=title, style='App.TLabelframe')
        section.pack(fill='x', pady=(0, 14))
        Label(
            section,
            text=description,
            bg=self.palette.surface,
            fg=self.palette.muted_text,
        ).pack(anchor='w', pady=(0, 10))
        return section

    def _checkbutton(self, parent, text: str, variable: BooleanVar, command) -> Checkbutton:
        return Checkbutton(
            parent,
            text=text,
            variable=variable,
            command=command,
            bg=self.palette.surface,
            fg=self.palette.text,
            activebackground=self.palette.surface,
            activeforeground=self.palette.text,
            selectcolor=self.palette.input_background,
            highlightthickness=0,
            font=BASE_FONT,
        )

    def _create_scrollable_settings(self) -> Frame:
        container = Frame(self.right_panel, bg=self.palette.background)
        self.settings_scroll_container = container
        container.pack(fill='both', expand=True)
        scrollbar = Scrollbar(container)
        scrollbar.pack(side='right', fill='y')
        self.settings_canvas = Canvas(
            container,
            bg=self.palette.background,
            highlightthickness=0,
            bd=0,
            yscrollcommand=scrollbar.set,
        )
        self.settings_canvas.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.settings_canvas.yview)

        content = Frame(self.settings_canvas, bg=self.palette.background)
        content_window = self.settings_canvas.create_window((0, 0), anchor='nw', window=content)
        content.bind(
            '<Configure>',
            lambda event: self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox('all')),
        )
        self.settings_canvas.bind(
            '<Configure>',
            lambda event: self.settings_canvas.itemconfigure(content_window, width=event.width),
        )
        return content

    def _show_settings_panel(self) -> None:
        self._panel_title('设置')
        settings = self._create_scrollable_settings()

        appearance = self._settings_section(settings, '窗口外观', '默认跟随 Windows 的深浅色设置，修改后立即生效。')
        appearance_row = Frame(appearance, bg=self.palette.surface)
        appearance_row.pack(fill='x')
        Label(appearance_row, text='显示模式：', bg=self.palette.surface, fg=self.palette.text).pack(side='left')
        current_theme_mode = self.config.get('theme_mode', 'system')
        self.theme_var = StringVar(value=THEME_NAMES.get(current_theme_mode, '跟随系统'))
        self.theme_selector = ttk.Combobox(
            appearance_row,
            textvariable=self.theme_var,
            values=tuple(THEME_LABELS),
            state='readonly',
            width=12,
            style='App.TCombobox',
        )
        self.theme_selector.pack(side='left', padx=(8, 0))
        self.theme_selector.bind('<<ComboboxSelected>>', self._change_theme_mode)
        effective_mode = '深色' if resolve_theme(current_theme_mode).background == resolve_theme('dark').background else '浅色'
        Label(
            appearance_row,
            text=f'当前生效：{effective_mode}',
            bg=self.palette.surface,
            fg=self.palette.muted_text,
        ).pack(side='left', padx=(12, 0))

        output = self._settings_section(settings, '输出设置', '控制单图和批处理的默认保存位置及输出文件名。')
        self.use_default_var = BooleanVar(value=self.config.get('use_default_dir', False))
        self._checkbutton(
            output,
            '自动保存到默认保存目录',
            self.use_default_var,
            self._toggle_auto_save,
        ).pack(anchor='w', pady=(0, 10))

        directory_row = Frame(output, bg=self.palette.surface)
        directory_row.pack(fill='x', pady=(0, 12))
        Label(directory_row, text='默认保存目录：', bg=self.palette.surface, fg=self.palette.text).pack(side='left')
        self.default_dir_var = StringVar(value=self.config.get('default_save_dir', ''))
        self.default_dir_entry = ttk.Entry(directory_row, textvariable=self.default_dir_var, style='App.TEntry')
        self.default_dir_entry.pack(side='left', fill='x', expand=True, padx=(8, 10))
        self.default_dir_entry.bind('<FocusOut>', self._save_default_dir)
        self.default_dir_browse_button = self._button(directory_row, '浏览', self._browse_default_dir, width=8)
        self.default_dir_browse_button.pack(side='right')

        self.use_suffix_var = BooleanVar(value=self.config.get('use_suffix', True))
        self._checkbutton(
            output,
            '输出文件名添加后缀',
            self.use_suffix_var,
            self._toggle_suffix,
        ).pack(anchor='w', pady=(0, 10))
        suffix_row = Frame(output, bg=self.palette.surface)
        suffix_row.pack(fill='x')
        Label(suffix_row, text='文件名后缀：', bg=self.palette.surface, fg=self.palette.text).pack(side='left')
        self.suffix_var = StringVar(value=self.config.get('suffix', '_non'))
        self.suffix_entry = ttk.Entry(suffix_row, textvariable=self.suffix_var, width=24, style='App.TEntry')
        self.suffix_entry.pack(side='left', padx=(8, 0))
        self.suffix_entry.bind('<FocusOut>', self._save_suffix)

        positions = self._settings_section(settings, '已记录的水印位置', '删除规则后，程序不会再自动使用该位置。')
        list_frame = Frame(positions, bg=self.palette.surface)
        list_frame.pack(fill='both', expand=True)
        scrollbar = Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')
        self.position_listbox = Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            height=6,
            bg=self.palette.input_background,
            fg=self.palette.text,
            selectbackground=self.palette.accent,
            selectforeground=self.palette.accent_text,
            highlightbackground=self.palette.border,
            highlightcolor=self.palette.accent,
            bd=1,
        )
        self.position_listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.position_listbox.yview)
        positions_data = self.config.watermark_positions()
        for index, position in enumerate(positions_data, start=1):
            self.position_listbox.insert(
                'end',
                (
                    f"位置 {index}：模板 {position.get('template_size', 48)}px，"
                    f"x={position['x_ratio']:.3f}，y={position['y_ratio']:.3f}，"
                    f"尺寸={position['size_ratio']:.3f}"
                ),
            )
        if not positions_data:
            self.position_listbox.insert('end', '暂无已记录的位置')
            self.position_listbox.config(state='disabled')
        self.delete_position_button = self._button(
            positions,
            '删除所选位置',
            self._delete_selected_position,
            width=14,
        )
        self.delete_position_button.pack(anchor='e', pady=(10, 0))
        if not positions_data:
            self.delete_position_button.config(state='disabled')
        self._update_settings_state()

    def _change_theme_mode(self, event=None) -> None:
        if self.processing:
            return
        selected_mode = THEME_LABELS.get(self.theme_var.get(), 'system')
        self.config.set('theme_mode', selected_mode)
        self.root.after_idle(self._rebuild_for_theme)

    def _rebuild_for_theme(self) -> None:
        if self.preview_dialog is not None and self.preview_dialog.dialog.winfo_exists():
            self.preview_dialog.close()
        self.palette = resolve_theme(self.config.get('theme_mode', 'system'))
        for widget in self.root.winfo_children():
            widget.destroy()
        self.menu_buttons = []
        self._setup_styles()
        self._setup_ui()
        self.show_panel(self.current_panel)

    def _delete_selected_position(self) -> None:
        selection = self.position_listbox.curselection()
        if not selection:
            messagebox.showwarning('提示', '请先选择要删除的位置')
            return
        self.config.remove_watermark_position(selection[0])
        self.show_panel('settings')

    def _toggle_auto_save(self) -> None:
        self.config.set('use_default_dir', self.use_default_var.get())
        self._update_settings_state()

    def _toggle_suffix(self) -> None:
        self.config.set('use_suffix', self.use_suffix_var.get())
        self._update_settings_state()

    def _update_settings_state(self) -> None:
        default_directory_enabled = self.use_default_var.get()
        suffix_enabled = self.use_suffix_var.get()
        self.default_dir_entry.config(state='normal' if default_directory_enabled else 'disabled')
        self.default_dir_browse_button.config(state='normal' if default_directory_enabled else 'disabled')
        self.suffix_entry.config(state='normal' if suffix_enabled else 'disabled')

    def _save_default_dir(self, event=None) -> None:
        self.config.set('default_save_dir', self.default_dir_var.get())

    def _save_suffix(self, event=None) -> None:
        self.config.set('suffix', self.suffix_var.get())

    def _browse_default_dir(self) -> None:
        selected = filedialog.askdirectory(title='选择默认保存目录')
        if selected:
            self.default_dir_var.set(selected)
            self._save_default_dir()


def run() -> None:
    root = Tk()
    WatermarkRemoverApp(root)
    root.mainloop()
