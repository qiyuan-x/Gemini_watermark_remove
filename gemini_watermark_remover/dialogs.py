from __future__ import annotations

import ctypes
import math
import sys
from tkinter import Button, Canvas, Frame, Label, StringVar, Toplevel, ttk

from PIL import Image, ImageTk

from .paths import resource_path
from .theme import ThemePalette
from .watermark import WatermarkMatch, WatermarkRemover


UI_FONT_NAME = 'Microsoft YaHei UI'
BASE_FONT = (UI_FONT_NAME, 10)
DIALOG_TITLE_FONT = (UI_FONT_NAME, 12, 'bold')


def _work_area(window) -> tuple[int, int, int, int]:
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    if sys.platform != 'win32':
        return 0, 0, screen_width, screen_height

    class Rect(ctypes.Structure):
        _fields_ = [
            ('left', ctypes.c_long),
            ('top', ctypes.c_long),
            ('right', ctypes.c_long),
            ('bottom', ctypes.c_long),
        ]

    rect = Rect()
    try:
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    except (AttributeError, OSError):
        pass
    return 0, 0, screen_width, screen_height


def _clamp_position(window, width: int, height: int, x: int, y: int, margin: int = 32) -> tuple[int, int]:
    work_left, work_top, work_right, work_bottom = _work_area(window)
    min_x = work_left + margin
    min_y = work_top + margin
    max_x = max(min_x, work_right - width - margin)
    max_y = max(min_y, work_bottom - height - margin)
    return max(min_x, min(x, max_x)), max(min_y, min(y, max_y))


class ImagePreviewDialog:
    """Display an image in a zoomable, draggable viewer."""

    MAX_RENDER_PIXELS = 20_000_000

    def __init__(
        self,
        parent,
        image: Image.Image,
        palette: ThemePalette,
        on_close=None,
    ) -> None:
        self.parent = parent
        self.palette = palette
        self.on_close = on_close
        self.image = image
        self.zoom = 1.0
        self.image_x: float | None = None
        self.image_y: float | None = None
        self.drag_start: tuple[int, int] | None = None
        self.image_item: int | None = None
        self.draw_job: str | None = None
        self.photo_cache: dict[tuple[int, int], ImageTk.PhotoImage] = {}
        self.photo_cache_order: list[tuple[int, int]] = []
        self.user_positioned_image = False
        self.dialog = Toplevel(parent)
        self.dialog.withdraw()
        self.dialog.title('图片预览')
        self.dialog.transient(parent)
        self.dialog.protocol('WM_DELETE_WINDOW', self.close)
        self._set_icon()

        self._setup()
        self.dialog.update_idletasks()
        self._center_over_parent()
        self.dialog.deiconify()
        self.dialog.lift()
        self.dialog.focus_force()
        self.dialog.after(20, self._center_over_parent)

    def _set_icon(self) -> None:
        icon_path = resource_path('app.ico')
        if icon_path.exists():
            try:
                self.dialog.iconbitmap(str(icon_path))
            except Exception:
                pass

    def _setup(self) -> None:
        image_width, image_height = self.image.size
        screen_width = self.dialog.winfo_screenwidth()
        screen_height = self.dialog.winfo_screenheight()
        self.parent.update_idletasks()
        canvas_width = min(max(860, self.parent.winfo_width()), screen_width - 60)
        canvas_height = min(max(620, self.parent.winfo_height() - 40), screen_height - 110)
        self.dialog_width = canvas_width
        self.dialog_height = canvas_height
        self.zoom = min(1.0, canvas_width / image_width, canvas_height / image_height)
        self.dialog.geometry(f'{canvas_width}x{canvas_height}')
        self.dialog.minsize(min(700, canvas_width), min(500, canvas_height))
        self.dialog.configure(bg=self.palette.background)

        self.canvas = Canvas(
            self.dialog,
            bg=self.palette.background,
            highlightthickness=0,
            bd=0,
            cursor='fleur',
        )
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', self._on_canvas_resize)
        self.canvas.bind('<MouseWheel>', self._zoom_at_cursor)
        self.canvas.bind('<Button-4>', lambda event: self._zoom_at_cursor(event, 1))
        self.canvas.bind('<Button-5>', lambda event: self._zoom_at_cursor(event, -1))
        self.canvas.bind('<ButtonPress-1>', self._start_drag)
        self.canvas.bind('<B1-Motion>', self._drag_image)
        self.canvas.bind('<Double-Button-1>', lambda event: self.close())
        self.dialog.after_idle(self._draw_image)

    def _on_canvas_resize(self, event=None) -> None:
        if not self.user_positioned_image:
            self.image_x = self.canvas.winfo_width() / 2
            self.image_y = self.canvas.winfo_height() / 2
        if self.image_item is not None:
            self.canvas.coords(self.image_item, self.image_x, self.image_y)

    def _draw_image(self) -> None:
        self.draw_job = None
        if not self.user_positioned_image or self.image_x is None or self.image_y is None:
            self.image_x = self.canvas.winfo_width() / 2
            self.image_y = self.canvas.winfo_height() / 2
        image_width = max(1, round(self.image.width * self.zoom))
        image_height = max(1, round(self.image.height * self.zoom))
        self.photo = self._photo_for_size(image_width, image_height)
        if self.image_item is None:
            self.image_item = self.canvas.create_image(
                self.image_x,
                self.image_y,
                image=self.photo,
                anchor='center',
            )
        else:
            self.canvas.itemconfig(self.image_item, image=self.photo)
            self.canvas.coords(self.image_item, self.image_x, self.image_y)

    def _photo_for_size(self, width: int, height: int) -> ImageTk.PhotoImage:
        cache_key = (width, height)
        cached = self.photo_cache.get(cache_key)
        if cached is not None:
            return cached

        rendered_image = self.image.resize((width, height), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(rendered_image)
        self.photo_cache[cache_key] = photo
        self.photo_cache_order.append(cache_key)
        while len(self.photo_cache_order) > 6:
            old_key = self.photo_cache_order.pop(0)
            self.photo_cache.pop(old_key, None)
        return photo

    def _schedule_draw_image(self) -> None:
        if self.draw_job is not None:
            self.dialog.after_cancel(self.draw_job)
        self.draw_job = self.dialog.after(20, self._draw_image)

    def _zoom_at_cursor(self, event, direction: int | None = None) -> None:
        wheel_direction = direction if direction is not None else (1 if event.delta > 0 else -1)
        maximum_zoom = min(8.0, math.sqrt(self.MAX_RENDER_PIXELS / (self.image.width * self.image.height)))
        new_zoom = max(0.05, min(maximum_zoom, self.zoom * (1.15 if wheel_direction > 0 else 1 / 1.15)))
        if new_zoom == self.zoom or self.image_x is None or self.image_y is None:
            return
        image_offset_x = (event.x - self.image_x) / self.zoom
        image_offset_y = (event.y - self.image_y) / self.zoom
        self.zoom = new_zoom
        self.image_x = event.x - image_offset_x * self.zoom
        self.image_y = event.y - image_offset_y * self.zoom
        self.user_positioned_image = True
        self._schedule_draw_image()

    def _start_drag(self, event) -> None:
        self.drag_start = (event.x, event.y)

    def _drag_image(self, event) -> None:
        if self.drag_start is None or self.image_x is None or self.image_y is None:
            return
        last_x, last_y = self.drag_start
        self.image_x += event.x - last_x
        self.image_y += event.y - last_y
        self.drag_start = (event.x, event.y)
        self.user_positioned_image = True
        if self.image_item is not None:
            self.canvas.coords(self.image_item, self.image_x, self.image_y)

    def _center_over_parent(self) -> None:
        self.parent.update_idletasks()
        self.dialog.update_idletasks()
        width = self.dialog_width
        height = self.dialog_height
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()
        x = self.parent.winfo_rootx() + (parent_width - width) // 2
        y = self.parent.winfo_rooty() + (parent_height - height) // 2
        x = max(0, min(x, self.dialog.winfo_screenwidth() - width))
        y = max(0, min(y, self.dialog.winfo_screenheight() - height))
        self.dialog.geometry(f'+{x}+{y}')

    def close(self) -> None:
        if self.draw_job is not None:
            try:
                self.dialog.after_cancel(self.draw_job)
            except Exception:
                pass
            self.draw_job = None
        if self.dialog.winfo_exists():
            self.dialog.destroy()
        if self.on_close is not None:
            self.on_close()


class WatermarkConfirmDialog:
    """Let the user confirm a high-confidence watermark candidate."""

    def __init__(
        self,
        parent,
        image: Image.Image,
        remover: WatermarkRemover,
        initial_match: WatermarkMatch | None,
        palette: ThemePalette,
    ) -> None:
        self.parent = parent
        self.image = image
        self.remover = remover
        self.palette = palette
        self.result: WatermarkMatch | None = None
        self.match: WatermarkMatch | None = None
        self.rejection_message = ''
        self.scale = 1.0
        self.detection_context = None

        preferred_size = remover.preferred_size(image)
        self.template_var = StringVar(value=str(preferred_size))
        if initial_match is None:
            self.last_click = (image.width // 2, image.height // 2)
        else:
            self.last_click = (
                initial_match.x + initial_match.size // 2,
                initial_match.y + initial_match.size // 2,
            )

        self.dialog = Toplevel(parent)
        self.dialog.withdraw()
        self.dialog.title('确认水印位置')
        self.dialog.transient(parent)
        self.dialog.protocol('WM_DELETE_WINDOW', self._cancel)
        self._set_icon()
        self._setup_ui()
        self.dialog.update_idletasks()
        self._center_over_parent()
        self.dialog.deiconify()
        self.dialog.after(20, self._center_over_parent)
        self.dialog.grab_set()

    def _set_icon(self) -> None:
        icon_path = resource_path('app.ico')
        if icon_path.exists():
            try:
                self.dialog.iconbitmap(str(icon_path))
            except Exception:
                pass

    def _setup_ui(self) -> None:
        work_left, work_top, work_right, work_bottom = _work_area(self.dialog)
        work_width = work_right - work_left
        work_height = work_bottom - work_top
        controls_width = 300
        dialog_padding = 36
        edge_margin = 40
        titlebar_margin = 88
        available_width = max(280, work_width - controls_width - dialog_padding - edge_margin * 2)
        available_height = max(280, work_height - edge_margin * 2 - titlebar_margin - 48)
        self.scale = min(1.0, available_width / self.image.width, available_height / self.image.height)
        preview_width = max(1, round(self.image.width * self.scale))
        preview_height = max(1, round(self.image.height * self.scale))
        dialog_width = min(work_width - edge_margin * 2, preview_width + controls_width + dialog_padding)
        dialog_height = min(work_height - edge_margin * 2 - titlebar_margin, preview_height + 48)
        self.dialog_width = dialog_width
        self.dialog_height = dialog_height
        self.dialog.geometry(f'{dialog_width}x{dialog_height}')
        self.dialog.minsize(min(640, dialog_width), min(480, dialog_height))

        content = Frame(self.dialog, bg=self.palette.background, padx=12, pady=12)
        content.pack(fill='both', expand=True)
        self.canvas = Canvas(
            content,
            width=preview_width,
            height=preview_height,
            bg=self.palette.surface,
            highlightthickness=0,
            cursor='crosshair',
        )
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.bind('<Button-1>', self._select_near_click)
        preview = self.image.copy()
        if self.scale < 1.0:
            preview = preview.resize((preview_width, preview_height), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(preview)
        self.canvas.create_image(0, 0, anchor='nw', image=self.photo)

        controls = Frame(content, bg=self.palette.background, padx=16)
        controls.pack(side='right', fill='y')
        Label(
            controls,
            text='确认水印位置',
            bg=self.palette.background,
            fg=self.palette.text,
            font=DIALOG_TITLE_FONT,
        ).pack(anchor='w')
        Label(
            controls,
            text=(
                '红框应覆盖完整水印。\n'
                f'仅可确认置信度不低于 {self.remover.MATCH_THRESHOLD:.2f} 且通过水印校验的位置。\n'
                '位置不正确时，请在水印附近单击。'
            ),
            bg=self.palette.background,
            fg=self.palette.muted_text,
            justify='left',
            wraplength=245,
        ).pack(anchor='w', pady=(10, 14))

        template_row = Frame(controls, bg=self.palette.background)
        template_row.pack(anchor='w', pady=(0, 14))
        Label(template_row, text='原始模板：', bg=self.palette.background, fg=self.palette.text).pack(side='left')
        selector = ttk.Combobox(
            template_row,
            textvariable=self.template_var,
            values=('48', '96'),
            state='readonly',
            width=6,
            style='App.TCombobox',
        )
        selector.pack(side='left')
        selector.bind('<<ComboboxSelected>>', self._on_template_change)
        Label(template_row, text='px', bg=self.palette.background, fg=self.palette.text).pack(side='left', padx=(4, 0))

        self.status_var = StringVar(value='正在查找候选位置…')
        Label(
            controls,
            textvariable=self.status_var,
            bg=self.palette.background,
            fg=self.palette.text,
            justify='left',
            wraplength=245,
        ).pack(anchor='w', pady=(0, 14))
        self.confirm_button = Button(
            controls,
            text='确认并记住位置',
            command=self._confirm,
            width=18,
            font=BASE_FONT,
        )
        self.confirm_button.pack(anchor='w', pady=4)
        Button(
            controls,
            text='取消处理',
            command=self._cancel,
            width=18,
            font=BASE_FONT,
        ).pack(anchor='w', pady=4)
        self.dialog.resizable(False, False)
        self._locate()

    def _template_size(self) -> int:
        value = int(self.template_var.get())
        return value if value in self.remover.watermark_images else self.remover.preferred_size(self.image)

    def _draw_match(self) -> None:
        self.canvas.delete('watermark_box')
        if self.match is None:
            self.status_var.set(self.rejection_message or '未找到可确认的候选位置。\n请在水印附近单击后重试。')
            self.confirm_button.config(state='disabled')
            return
        self.canvas.create_rectangle(
            self.match.x * self.scale,
            self.match.y * self.scale,
            (self.match.x + self.match.size) * self.scale,
            (self.match.y + self.match.size) * self.scale,
            outline='#ff3b30',
            width=2,
            tags='watermark_box',
        )
        self.status_var.set(
            f'位置：({self.match.x}, {self.match.y})\n'
            f'原始模板：{self.match.template_size}px\n'
            f'置信度：{self.match.score:.2f}'
        )
        self.confirm_button.config(state='normal')

    def _locate(self) -> None:
        if self.detection_context is None:
            self.detection_context = self.remover.create_detection_context(self.image)
        candidate = self.remover.find_near(
            self.image,
            *self.last_click,
            expected_size=self._template_size(),
            template_size=self._template_size(),
            context=self.detection_context,
        )
        self.match = candidate if self.remover.is_valid(candidate) else None
        if candidate is None:
            self.rejection_message = '未找到候选位置。\n请在水印附近单击后重试。'
        elif candidate.score < self.remover.MATCH_THRESHOLD:
            self.rejection_message = (
                f'候选置信度为 {candidate.score:.2f}，低于 {self.remover.MATCH_THRESHOLD:.2f}。\n'
                '请在水印附近单击后重试。'
            )
        elif self.match is None:
            self.rejection_message = (
                f'候选置信度为 {candidate.score:.2f}，但未通过水印校验。\n'
                '请在水印附近单击后重试。'
            )
        else:
            self.rejection_message = ''
        self._draw_match()

    def _select_near_click(self, event) -> None:
        self.last_click = (
            min(self.image.width - 1, round(event.x / self.scale)),
            min(self.image.height - 1, round(event.y / self.scale)),
        )
        self.status_var.set('正在识别点击位置附近的水印…')
        self.dialog.update_idletasks()
        self._locate()

    def _on_template_change(self, event=None) -> None:
        self._locate()

    def _confirm(self) -> None:
        if self.remover.is_valid(self.match):
            self.result = self.match
            self._close()

    def _cancel(self) -> None:
        self._close()

    def _close(self) -> None:
        if self.dialog.winfo_exists():
            self.dialog.grab_release()
            self.dialog.destroy()

    def _center_over_parent(self) -> None:
        self.parent.update_idletasks()
        self.dialog.update_idletasks()
        width = max(self.dialog_width, self.dialog.winfo_width())
        height = max(self.dialog_height, self.dialog.winfo_height())
        x = self.parent.winfo_rootx() + (self.parent.winfo_width() - width) // 2
        y = self.parent.winfo_rooty() + (self.parent.winfo_height() - height) // 2
        x, y = _clamp_position(self.dialog, width, height + 40, x, y, margin=40)
        self.dialog.geometry(f'+{x}+{y}')

    def show(self) -> WatermarkMatch | None:
        self.parent.wait_window(self.dialog)
        return self.result
