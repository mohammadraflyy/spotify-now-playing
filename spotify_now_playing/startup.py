"""Jalankan otomatis saat Windows menyala (registry Run milik user, tanpa admin)."""

import sys

try:
    import winreg
except ImportError:  # bukan Windows
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "SpotifyNowPlaying"


def supported():
    """Hanya untuk exe hasil build (bukan saat dijalankan dari source)."""
    return winreg is not None and getattr(sys, "frozen", False)


def command():
    return f'"{sys.executable}" --no-browser'


def is_enabled():
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE)
        return True
    except OSError:
        return False


def set_enabled(on):
    if not supported():
        raise OSError("Hanya tersedia di versi yang di-install")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, VALUE)
            except FileNotFoundError:
                pass
