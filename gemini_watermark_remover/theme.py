from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    background: str
    surface: str
    sidebar: str
    input_background: str
    border: str
    text: str
    muted_text: str
    accent: str
    accent_text: str
    hover: str
    success: str
    error: str


LIGHT_THEME = ThemePalette(
    background='#f7f7f7',
    surface='#ffffff',
    sidebar='#f1f1f1',
    input_background='#ffffff',
    border='#dedede',
    text='#242424',
    muted_text='#747474',
    accent='#e2e2e2',
    accent_text='#242424',
    hover='#f0f0f0',
    success='#2d7a46',
    error='#b6473e',
)

DARK_THEME = ThemePalette(
    background='#202020',
    surface='#282828',
    sidebar='#242424',
    input_background='#303030',
    border='#3d3d3d',
    text='#ededed',
    muted_text='#a4a4a4',
    accent='#5c5c5c',
    accent_text='#ffffff',
    hover='#343434',
    success='#65a878',
    error='#df7870',
)


def system_theme_mode() -> str:
    """Return the Windows application theme, falling back to light mode."""
    if sys.platform != 'win32':
        return 'light'

    try:
        import winreg

        registry_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
            apps_use_light_theme, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
        return 'light' if apps_use_light_theme else 'dark'
    except OSError:
        return 'light'


def resolve_theme(mode: str | None) -> ThemePalette:
    selected_mode = mode if mode in {'system', 'light', 'dark'} else 'system'
    if selected_mode == 'dark' or (selected_mode == 'system' and system_theme_mode() == 'dark'):
        return DARK_THEME
    return LIGHT_THEME
