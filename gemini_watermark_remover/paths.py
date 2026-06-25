from __future__ import annotations

import ctypes
import sys
from pathlib import Path


def enable_high_dpi() -> None:
    """Enable native Windows DPI rendering before Tk is created."""
    if sys.platform != 'win32':
        return

    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(-4):
            return
    except (AttributeError, OSError):
        pass

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def application_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_path(filename: str) -> Path:
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys._MEIPASS) / 'assets'
    else:
        base_dir = application_dir() / 'assets'
    return base_dir / filename


def data_dir() -> Path:
    path = application_dir() / 'data'
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / 'config.json'
