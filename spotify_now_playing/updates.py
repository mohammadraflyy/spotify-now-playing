"""Cek versi baru di GitHub Releases (opt-in), dan pasang update dengan sekali klik.

Update: installer dari rilis GitHub di-download ke folder temp, dicocokkan dengan SHA-256 yang
tercantum di catatan rilis, lalu dijalankan dalam mode silent. Installer menutup aplikasi ini,
memasang versi baru, lalu menjalankannya lagi."""

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from . import __version__

REPO = "mohammadraflyy/spotify-now-playing"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
CHECK_EVERY = 24 * 3600
ASSET_NAME = re.compile(r"^SpotifyNowPlaying-Setup-[\d.]+\.exe$")
ASSET_PREFIX = f"https://github.com/{REPO}/releases/download/"
SHA256 = re.compile(r"SHA-256:\s*`?([0-9a-fA-F]{64})")
MAX_SIZE = 200 * 1024 * 1024

log = logging.getLogger("snp")


def parse_version(text):
    """'v1.4.0' -> (1, 4, 0). Bagian yang bukan angka diabaikan."""
    return tuple(int(n) for n in re.findall(r"\d+", text or "")[:3]) or (0,)


def is_newer(latest, current=__version__):
    return parse_version(latest) > parse_version(current)


def fetch_latest():
    req = urllib.request.Request(LATEST_API, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"SpotifyNowPlaying/{__version__}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.load(r)
    return parse_release(data)


def parse_release(data):
    info = {"version": (data.get("tag_name") or "").lstrip("v"), "url": data.get("html_url") or RELEASES_URL}
    asset = next((a for a in data.get("assets") or [] if ASSET_NAME.match(a.get("name") or "")), None)
    sha = SHA256.search(data.get("body") or "")
    url = (asset or {}).get("browser_download_url") or ""
    if asset and sha and url.startswith(ASSET_PREFIX):
        info.update(asset_url=url, asset_name=asset["name"], size=asset.get("size") or 0, sha256=sha.group(1).lower())
    return info


def can_install():
    """Update otomatis hanya untuk versi yang di-install (exe), bukan saat dijalankan dari source."""
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


class UpdateChecker:
    def __init__(self, cfg, on_found=None):
        self.cfg = cfg
        self.on_found = on_found     # dipanggil sekali per versi baru, mis. untuk notifikasi tray
        self.available = None        # {"version", "url"} kalau ada versi lebih baru
        self.status = "off"          # off | checking | ok | error
        self.wake = threading.Event()
        self._notified = None
        self.install_status = {"state": "idle", "progress": 0, "error": ""}
        self.before_install = None   # dipanggil tepat sebelum installer dijalankan (mis. pulihkan suara)
        self.run_installer = _run_installer
        self.download = _download

    def enabled(self):
        return bool(self.cfg.get("check_updates", False))

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def check_now(self):
        if self.enabled() and self.status in ("off", "error"):
            self.status = "checking"
        self.wake.set()

    def _loop(self):
        while True:
            if self.enabled():
                if self.status != "ok":
                    self.status = "checking"
                try:
                    latest = fetch_latest()
                    self.available = latest if is_newer(latest["version"]) else None
                    self.status = "ok"
                except Exception:
                    self.status = "error"  # offline / rate limit: coba lagi nanti
                if self.available and self._notified != self.available["version"] and self.on_found:
                    self._notified = self.available["version"]
                    self.on_found(self.available)
            else:
                self.available, self.status = None, "off"
            self.wake.wait(CHECK_EVERY)
            self.wake.clear()

    # ----------------------------------------------------------- install --

    def install(self):
        """Mulai update di background. Return pesan error, atau None kalau sudah dimulai."""
        info = self.available
        if not can_install():
            return "Update otomatis hanya untuk versi yang di-install"
        if not info or not info.get("asset_url"):
            return "Installer versi baru tidak ditemukan di halaman rilis"
        if self.install_status["state"] in ("downloading", "verifying", "starting"):
            return None
        self.install_status = {"state": "downloading", "progress": 0, "error": ""}
        threading.Thread(target=self._install, args=(info,), daemon=True).start()
        return None

    def _install(self, info):
        path = os.path.join(tempfile.gettempdir(), info["asset_name"])
        try:
            def progress(done, total):
                self.install_status["progress"] = int(done * 100 / total) if total else 0
            digest = self.download(info["asset_url"], path, info.get("size") or 0, progress)
            self.install_status.update(state="verifying", progress=100)
            if digest != info["sha256"]:
                raise ValueError("Checksum installer tidak cocok, update dibatalkan")
            self.install_status["state"] = "starting"
            log.info("memasang update %s", info["version"])
            if self.before_install:
                self.before_install()
            self.run_installer(path)
        except Exception as e:  # noqa: BLE001  (ditampilkan ke user, bukan crash)
            log.warning("update gagal: %s", e)
            self.install_status = {"state": "error", "progress": 0, "error": str(e)}
            try:
                os.remove(path)
            except OSError:
                pass


def _download(url, path, size, progress):
    """Download ke `path`, return SHA-256 (hex). Gagal kalau ukurannya tidak sesuai."""
    req = urllib.request.Request(url, headers={"User-Agent": f"SpotifyNowPlaying/{__version__}"})
    sha, done = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or size or 0)
        while chunk := r.read(256 * 1024):
            done += len(chunk)
            if done > MAX_SIZE:
                raise ValueError("Installer terlalu besar")
            sha.update(chunk)
            f.write(chunk)
            progress(done, total)
    if size and done != size:
        raise ValueError("Download installer tidak lengkap")
    return sha.hexdigest()


def _run_installer(path):
    # /SILENT: tampil progress saja; installer menutup aplikasi ini lalu menjalankannya lagi
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"], close_fds=True, creationflags=flags)
