"""Cek versi baru di GitHub Releases. Opt-in: hanya jalan kalau diaktifkan di pengaturan."""

import json
import re
import threading
import time
import urllib.request

from . import __version__

REPO = "mohammadraflyy/spotify-now-playing"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
CHECK_EVERY = 24 * 3600


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
    return {"version": (data.get("tag_name") or "").lstrip("v"), "url": data.get("html_url") or RELEASES_URL}


class UpdateChecker:
    def __init__(self, cfg, on_found=None):
        self.cfg = cfg
        self.on_found = on_found     # dipanggil sekali per versi baru, mis. untuk notifikasi tray
        self.available = None        # {"version", "url"} kalau ada versi lebih baru
        self.status = "off"          # off | checking | ok | error
        self.wake = threading.Event()
        self._notified = None

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
