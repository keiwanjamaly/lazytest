from __future__ import annotations

import subprocess
import sys
import types

from lazytest import theme


def test_macos_dark_theme_uses_apple_interface_style(
    monkeypatch,
) -> None:
    monkeypatch.setattr(theme.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        theme.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "Dark\n", ""),
    )

    assert theme.system_theme() == theme.TEXTUAL_DARK_THEME


def test_macos_light_theme_is_default_when_apple_style_is_absent(
    monkeypatch,
) -> None:
    monkeypatch.setattr(theme.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        theme.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )

    assert theme.system_theme() == theme.TEXTUAL_LIGHT_THEME


def test_linux_dark_theme_uses_gnome_color_scheme(monkeypatch) -> None:
    monkeypatch.setattr(theme.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        theme.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            "'prefer-dark'\n",
            "",
        ),
    )

    assert theme.system_theme() == theme.TEXTUAL_DARK_THEME


def test_windows_dark_theme_uses_apps_use_light_theme(
    monkeypatch,
) -> None:
    fake_winreg = types.SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        OpenKey=lambda *args: _FakeKey(),
        QueryValueEx=lambda *args: (0, None),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(theme.platform, "system", lambda: "Windows")

    assert theme.system_theme() == theme.TEXTUAL_DARK_THEME


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None
