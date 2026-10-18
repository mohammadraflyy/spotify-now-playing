"""Lokasi file dan penyimpanan pengaturan.

- pengaturan : %APPDATA%\\SpotifyNowPlaying\\config.json
- output     : Documents\\Spotify Now Playing  (file teks + cover untuk OBS)
"""

import ctypes
import json
import os
import shutil
import threading
import time
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent / "web"  # ikut ter-bundle oleh PyInstaller
DATA_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "SpotifyNowPlaying"
CONFIG_FILE = DATA_DIR / "config.json"
LOG_FILE = DATA_DIR / "app.log"

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
    """config.json, dengan cadangan config.json.bak dari penyimpanan sebelumnya.

    Kalau config.json rusak (mis. PC mati saat menyimpan), cadangannya dipakai dan file yang rusak
    disimpan sebagai config.broken-<waktu>.json, bukan ditimpa diam-diam."""

    def __init__(self, path=None):
        self.path = Path(path) if path else CONFIG_FILE
        self.backup = self.path.with_name(self.path.name + ".bak")
        self.lock = threading.Lock()
        self.recovered = None  # None | "backup" | "defaults": dipakai untuk memberi tahu user
        self.first_run = not self.path.exists() and not self.backup.exists()
        self.data = dict(DEFAULTS)
        self.data.update(self._load())

    def _load(self):
        try:
            return _read(self.path)
        except FileNotFoundError:
            pass
        except OSError:
            return _try_read(self.backup) or {}  # terkunci sementara: jangan ganti nama file aslinya
        except ValueError:
            broken = self.path.with_name(f"config.broken-{time.strftime('%Y%m%d-%H%M%S')}.json")
            try:
                self.path.replace(broken)
            except OSError:
                pass
            self.recovered = "defaults"
        data = _try_read(self.backup)
        if data is not None:
            self.recovered = "backup"
            return data
        return {}

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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())  # tanpa ini, mati listrik bisa meninggalkan file kosong
        if self.path.exists():
            try:
                shutil.copyfile(self.path, self.backup)
            except OSError:
                pass
        tmp.replace(self.path)


def _read(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config bukan object JSON")
    return data


def _try_read(path):
    try:
        return _read(path)
    except (OSError, ValueError):
        return None
