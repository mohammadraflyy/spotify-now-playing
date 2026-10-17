"""Teks untuk bagian aplikasi di luar browser (tray, notifikasi, dialog)."""

import ctypes

TEXT = {
    "id": {
        "open_settings": "Buka pengaturan",
        "open_folder": "Buka folder file teks",
        "startup": "Jalankan saat Windows menyala",
        "donate": "Dukung lewat Trakteer",
        "quit": "Keluar",
        "download": "Download versi {version}",
        "update_found": "Versi {version} tersedia. Klik kanan ikon ini untuk download.",
        "greet": "Berjalan di system tray. Klik ikonnya untuk membuka pengaturan.",
        "nothing": "Tidak ada lagu yang diputar",
        "ad_break": "Jeda sebentar",
        "paused": " (pause)",
        "port_busy": "Port {port} sedang dipakai aplikasi lain.\n\nTutup aplikasi tersebut, atau jalankan dengan --port 8766.",
    },
    "en": {
        "open_settings": "Open settings",
        "open_folder": "Open text files folder",
        "startup": "Run when Windows starts",
        "donate": "Support on Trakteer",
        "quit": "Quit",
        "download": "Download version {version}",
        "update_found": "Version {version} is available. Right-click this icon to download it.",
        "greet": "Running in the system tray. Click the icon to open settings.",
        "nothing": "Nothing is playing",
        "ad_break": "Short break",
        "paused": " (paused)",
        "port_busy": "Port {port} is used by another app.\n\nClose that app, or run with --port 8766.",
    },
}


def system_lang():
    """Bahasa tampilan Windows: Indonesia -> "id", selain itu "en"."""
    try:
        return "id" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x21 else "en"
    except (AttributeError, OSError):
        return "id"


def lang(cfg):
    value = cfg.get("lang")
    return value if value in TEXT else system_lang()


def t(cfg, key, **kw):
    return TEXT[lang(cfg)][key].format(**kw)
