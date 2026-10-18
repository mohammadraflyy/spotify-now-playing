"""Teks untuk bagian aplikasi di luar browser (tray, notifikasi, dialog)."""

import ctypes

TEXT = {
    "id": {
        "open_settings": "Buka pengaturan",
        "open_folder": "Buka folder file teks",
        "startup": "Jalankan saat Windows menyala",
        "donate": "Dukung lewat Trakteer",
        "quit": "Keluar",
        "download": "Update ke versi {version}",
        "installing": "Mengunduh versi {version}. Aplikasi akan tertutup sebentar lalu terbuka lagi.",
        "update_found": "Versi {version} tersedia. Klik kanan ikon ini untuk update.",
        "greet": "Berjalan di system tray. Klik ikonnya untuk membuka pengaturan.",
        "nothing": "Tidak ada lagu yang diputar",
        "ad_break": "Jeda sebentar",
        "config_backup": "File pengaturan rusak, jadi dipulihkan dari cadangan terakhir.",
        "config_defaults": "File pengaturan rusak dan tidak ada cadangan, jadi pengaturan kembali ke awal. File lamanya disimpan di folder data.",
        "paused": " (pause)",
        "port_busy": "Port {port} sedang dipakai aplikasi lain.\n\nTutup aplikasi tersebut, atau jalankan dengan --port 8766.",
    },
    "en": {
        "open_settings": "Open settings",
        "open_folder": "Open text files folder",
        "startup": "Run when Windows starts",
        "donate": "Support on Trakteer",
        "quit": "Quit",
        "download": "Update to version {version}",
        "installing": "Downloading version {version}. The app will close for a moment and open again.",
        "update_found": "Version {version} is available. Right-click this icon to update.",
        "greet": "Running in the system tray. Click the icon to open settings.",
        "nothing": "Nothing is playing",
        "ad_break": "Short break",
        "config_backup": "The settings file was damaged, so it was restored from the last backup.",
        "config_defaults": "The settings file was damaged and there was no backup, so settings were reset. The old file is kept in the data folder.",
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
