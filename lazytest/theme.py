from __future__ import annotations

import platform
import subprocess

TEXTUAL_DARK_THEME = "textual-dark"
TEXTUAL_LIGHT_THEME = "textual-light"


def system_theme() -> str:
    return TEXTUAL_DARK_THEME if system_prefers_dark_theme() else TEXTUAL_LIGHT_THEME


def system_prefers_dark_theme() -> bool:
    match platform.system():
        case "Darwin":
            return _macos_prefers_dark_theme()
        case "Linux":
            return _gnome_prefers_dark_theme()
        case "Windows":
            return _windows_prefers_dark_theme()
        case _:
            return False


def _macos_prefers_dark_theme() -> bool:
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            check=False,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "dark"


def _gnome_prefers_dark_theme() -> bool:
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            check=False,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "prefer-dark" in result.stdout.lower()


def _windows_prefers_dark_theme() -> bool:
    try:
        import winreg
    except ImportError:
        return False

    path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
    except OSError:
        return False
    return value == 0
