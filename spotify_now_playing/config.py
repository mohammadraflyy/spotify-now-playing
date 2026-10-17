"""Lokasi file dan penyimpanan pengaturan.

- pengaturan : %APPDATA%\\SpotifyNowPlaying\\config.json
- output     : Documents\\Spotify Now Playing  (file teks + cover untuk OBS)
"""

import ctypes
import json
import os
import threading
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent / "web"  # ikut ter-bundle oleh PyInstaller
DATA_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "SpotifyNowPlaying"
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULTS = {"source": "auto", "port": 8765, "overlay": {}}


def documents_dir():
    """Folder Documents asli (ikut kalau dipindah ke OneDrive)."""
    buf = ctypes.create_unicode_buffer(260)
    try:
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # CSIDL_PERSONAL
            return Path(buf.value)
    except (AttributeError, OSError):
        pass
    return Path.home() / "Documents"


OUTPUT_DIR = documents_dir() / "Spotify Now Playing"


class Config:
    def __init__(self):
        self.lock = threading.Lock()
        self.first_run = not CONFIG_FILE.exists()
        self.data = dict(DEFAULTS)
        try:
            self.data.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key):
        return self.data[key]

    def update(self, **values):
        with self.lock:
            for k, v in values.items():
                if v is None:
                    self.data.pop(k, None)
                else:
                    self.data[k] = v
            self._save()

    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_FILE)
