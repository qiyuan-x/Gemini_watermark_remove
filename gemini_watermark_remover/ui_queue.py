from __future__ import annotations

import queue
from collections.abc import Callable
from tkinter import Tk


class UiQueue:
    """Run worker-thread callbacks on the Tk main thread."""

    def __init__(self, root: Tk, interval_ms: int = 40) -> None:
        self.root = root
        self.interval_ms = interval_ms
        self.queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self.after_id: str | None = None
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._schedule()

    def stop(self) -> None:
        self.running = False
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def post(self, callback: Callable[[], None]) -> None:
        self.queue.put(callback)

    def _schedule(self) -> None:
        if self.running:
            self.after_id = self.root.after(self.interval_ms, self._poll)

    def _poll(self) -> None:
        self.after_id = None
        while True:
            try:
                callback = self.queue.get_nowait()
            except queue.Empty:
                break
            callback()
        self._schedule()
