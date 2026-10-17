"""Loop utama: ambil lagu dari sumber terpilih, simpan state, tulis file untuk OBS."""

import logging
import sys
import threading
import time

from . import local_media
from .config import DATA_DIR, OUTPUT_DIR
from .lyrics import LyricsProvider
from .spotify_api import SpotifyAccount
from .history import History
from .updates import UpdateChecker

log = logging.getLogger("snp")

API_BACKOFF = 60     # detik jeda ke API setelah gagal (mode otomatis)
API_INTERVAL = 2.0   # jangan terlalu sering ke Web API (rate limit)
LOCAL_INTERVAL = 0.5
TEXT_FILES = ("nowplaying.txt", "title.txt", "artist.txt", "album.txt", "progress.txt", "lyrics.txt")


def format_line(fmt, s):
    """Format nowplaying.txt / now.txt, mis. "{artist} - {title}"."""
    try:
        return (fmt or "{artist} - {title}").format(title=s["title"], artist=s["artist"], album=s["album"])
    except (KeyError, IndexError, ValueError, AttributeError):
        return f"{s['artist']} - {s['title']}"


def fmt_time(sec):
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


class NowPlayingApp:
    def __init__(self, config):
        self.cfg = config
        self.account = SpotifyAccount(config)
        self.local = (local_media.LocalSpotify(lambda: config.get("players") == "all")
                      if local_media.AVAILABLE else None)
        self.lyrics = LyricsProvider(cache_dir=DATA_DIR / "lyrics")
        self.updates = UpdateChecker(config)
        self.history = History(DATA_DIR / "history")
        self.console = False  # True: tampilkan status di console (--console)
        self.lock = threading.Lock()
        self.state = {
            "playing": False, "active": False,
            "title": "", "artist": "", "album": "", "device": "",
            "position": 0.0, "duration": 0.0,
            "updated": 0.0,  # epoch saat position diambil
            "cover_version": 0,
        }
        self.cover = b""
        self.status = {"source": "idle", "error": ""}
        self._last_id = None
        self._api_blocked_until = 0
        self._api_error = ""

    # -------------------------------------------------------------- read --

    def snapshot(self):
        """State dengan posisi yang sudah dihitung sampai detik ini."""
        with self.lock:
            s = dict(self.state)
        if s["playing"]:
            s["position"] = min(s["position"] + time.time() - s["updated"], s["duration"] or 1e9)
        return s

    # -------------------------------------------------------------- loop --

    def run(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                delay = self.tick()
            except Exception:  # jangan sampai loop mati diam-diam di belakang ikon tray
                log.exception("tick gagal")
                self.status = {"source": "idle", "error": "Terjadi error, lihat app.log"}
                delay = 2
            time.sleep(delay)

    def tick(self):
        source = self.cfg.get("source", "auto")
        info, used, error, delay = None, "idle", "", API_INTERVAL

        if source in ("auto", "account") and self.account.logged_in and (
                source == "account" or time.time() >= self._api_blocked_until):
            try:
                info = self.account.now_playing()
                used, self._api_error = "account", ""
            except Exception as e:
                self._api_error = error = str(e)
                self._api_blocked_until = time.time() + API_BACKOFF
                delay = 10
        elif source == "account":
            error = "Belum login ke akun Spotify"

        if source == "local" or (source == "auto" and used != "account"):
            if self.local:
                try:
                    info = self.local.now_playing()
                    used, delay = "local", LOCAL_INTERVAL
                    if source == "auto" and self.account.logged_in and self._api_error:
                        error = f"{self._api_error} — sementara memakai Spotify Desktop lokal"
                except Exception as e:
                    error = error or f"Mode lokal error: {e}"
            elif source == "local":
                error = "Mode lokal tidak tersedia di sistem ini"

        if error and error != self.status.get("error"):
            log.warning(error)
        self.status = {"source": used, "error": error}
        self._apply(info)
        snap = self.snapshot()
        self._write_files(snap)
        self.history.observe(snap)
        self._render_console(snap)
        return delay

    def _apply(self, info):
        if info is None:
            with self.lock:
                self.state.update(active=False, playing=False)
            return
        if info["id"] != self._last_id:
            try:
                self.cover = info["cover"]() or b""
            except Exception:
                self.cover = b""
            if self.cover:
                try:
                    (OUTPUT_DIR / "cover.jpg").write_bytes(self.cover)
                except OSError:
                    pass
            with self.lock:
                self.state["cover_version"] += 1
            self._last_id = info["id"]
            self.lyrics.track_changed(info["id"], info["title"], info["artist"],
                                      info["album"], info["duration"])
        with self.lock:
            self.state.update(active=True, updated=time.time(),
                              **{k: info[k] for k in ("title", "artist", "album", "device",
                                                      "position", "duration", "playing")})

    # ------------------------------------------------------------ output --

    def _write_files(self, s):
        text = self.cfg.get("text", {})
        if not s["active"] or (not s["playing"] and text.get("hide_paused")):
            for f in TEXT_FILES:
                _write_text(f, "")
            return
        line = format_line(text.get("format"), s)
        _write_text("nowplaying.txt", line + "   ")  # spasi: enak untuk filter scroll OBS
        _write_text("title.txt", s["title"])
        _write_text("artist.txt", s["artist"])
        _write_text("album.txt", s["album"])
        # sebagian player (mis. browser) tidak memberi durasi: jangan tulis "0:00 / 0:00"
        _write_text("progress.txt", f"{fmt_time(s['position'])} / {fmt_time(s['duration'])}" if s["duration"] else "")
        offset = float(self.cfg.get("lyrics", {}).get("offset") or 0)
        _write_text("lyrics.txt", self.lyrics.line_at(s["position"], offset))

    def _render_console(self, s):
        if not self.console:
            return
        if self.status["error"] and not s["active"]:
            line = f"  ⚠  {self.status['error']}"
        elif not s["active"]:
            line = "  ⏹  Tidak ada lagu yang diputar"
        else:
            icon = "▶" if s["playing"] else "⏸"
            line = (f"  {icon}  {s['artist']} — {s['title']}  "
                    f"[{fmt_time(s['position'])} / {fmt_time(s['duration'])}]"
                    + (f"  @ {s['device']}" if s["device"] else ""))
        try:
            sys.stdout.write("\r" + line[:110].ljust(110))
            sys.stdout.flush()
        except (OSError, ValueError, AttributeError):
            pass  # tanpa console (mis. dijalankan tersembunyi)


def _write_text(name, text):
    path = OUTPUT_DIR / name
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass  # file mungkin sedang dibaca OBS, coba lagi di tick berikutnya
