"""Listener chat live: membaca request lagu dari chat Twitch, YouTube, dan TikTok.

Hanya membaca. Tidak ada pesan yang dikirim ke chat mana pun. Setiap platform punya koneksinya
sendiri (chat_twitch.py, chat_youtube.py, chat_tiktok.py) dan memanggil ChatBot.handle(); request
yang valid masuk ke antrian (song_requests.py) yang tampil di halaman pengaturan dan overlay OBS.
"""

import collections
import logging
import threading
import time
from datetime import datetime, timedelta

from .chat_tiktok import TikTokChat
from .chat_twitch import TwitchChat
from .chat_youtube import YouTubeChat
from .song_requests import FILLER_WORDS, RequestQueue, _leftover, normalize

DEFAULTS = {"request_enabled": True, "request_cmd": "!request", "request_max_user": 2, "request_max_total": 50,
            "request_autoplay": True,
            "request_block": "",            # kata/artis yang ditolak, dipisah koma atau baris baru
            "request_max_minutes": 10,      # durasi lagu maksimal (0 = tanpa batas; butuh login Akun Spotify)
            "request_recent_minutes": 30}   # tolak lagu yang diputar dalam N menit terakhir (0 = mati)
EVENTS = 20  # kejadian request terakhir yang disimpan untuk notifikasi overlay
log = logging.getLogger("snp")


class ChatBot:
    def __init__(self, app, data_dir=None):
        self.app = app
        self.requests = RequestQueue(f"{data_dir}/requests.json" if data_dir else None)
        self.events = collections.deque(maxlen=EVENTS)
        self._seq = 0
        self._events_lock = threading.Lock()
        self._migrate()
        self.twitch = TwitchChat(app.cfg, self.handle)
        self.youtube = YouTubeChat(app.cfg, self.handle)
        self.tiktok = TikTokChat(app.cfg, self.handle)

    def _migrate(self):
        """Versi <= 1.9 membalas di chat: hapus login yang tidak dipakai lagi, pertahankan channel Twitch."""
        cfg = self.app.cfg
        login = (cfg.get("twitch_auth") or {}).get("login")
        chat = dict(cfg.get("chat") or {})
        twitch = dict(chat.get("twitch") or {})
        if login and not twitch.get("channel"):
            chat["twitch"] = {**twitch, "channel": login.lower()}
            cfg.update(chat=chat)
        for key in ("twitch_auth", "youtube_bot_auth"):
            if cfg.get(key):
                cfg.update(**{key: None})

    def settings(self):
        return {**DEFAULTS, **(self.app.cfg.get("chat") or {})}

    def request_text(self, text):
        """'!request Tulus - Pamit' -> 'Tulus - Pamit'; None kalau bukan perintah request."""
        s = self.settings()
        cmd = (s.get("request_cmd") or "").strip()
        words = (text or "").strip().split(maxsplit=1)
        if not s.get("request_enabled") or not cmd or not words or words[0].lower() != cmd.lower():
            return None
        return words[1] if len(words) > 1 else ""

    def handle(self, platform, user, text):
        """Pesan chat masuk. Request yang valid masuk antrian; tidak ada balasan ke chat."""
        song = self.request_text(text)
        if song is None:
            return None
        status, shown = self._decide(song, user, platform, self.settings())
        self._event(status, user, platform, shown)
        return status

    def _decide(self, song, user, platform, s):
        """Return (status, teks lagu yang ditampilkan di notifikasi)."""
        song = " ".join(song.split())
        if not song:
            return "empty", ""
        if self._blocked(song, s):
            return "blocked", song
        track = None
        autoplay = getattr(self.app, "autoplay", None)
        if autoplay and autoplay.can_search():
            try:
                track = autoplay.find(song)
            except Exception as e:  # noqa: BLE001  (Spotify bermasalah: tetap masuk antrian, dicari ulang nanti)
                log.warning("pencarian Spotify gagal untuk %r: %s", song, e)
            else:
                if track is None:
                    return "not_found", song  # jangan isi antrian dengan lagu yang tidak ada di Spotify
        shown = f"{track['artist']} - {track['title']}" if track else song
        if track and self._blocked(f"{track['artist']} {track['title']}", s):
            return "blocked", shown
        limit = _int(s.get("request_max_minutes"))
        if track and limit and track.get("duration", 0) > limit * 60:
            return "too_long", shown
        if self._recently_played(track, song, _int(s.get("request_recent_minutes"))):
            return "recent", shown
        status, info = self.requests.add(song, user, platform, s["request_max_user"], s["request_max_total"],
                                         track=track)
        return status, info.get("text", shown) if status in ("added", "duplicate") else shown

    @staticmethod
    def _blocked(text, s):
        words = [normalize(w) for w in str(s.get("request_block") or "").replace("\n", ",").split(",")]
        text = f" {normalize(text)} "
        return any(w and f" {w} " in text for w in words)

    def _recently_played(self, track, song, minutes):
        """Lagu ini sedang diputar, atau sudah diputar dalam `minutes` menit terakhir?"""
        if not minutes:
            return False
        played = []
        snap = self.app.snapshot() if hasattr(self.app, "snapshot") else {}
        if snap.get("active") and not snap.get("ad"):
            played.append((snap.get("title", ""), snap.get("artist", "")))
        history = getattr(self.app, "history", None)
        if history:
            since = time.time() - minutes * 60
            for day in {datetime.now(), datetime.now() - timedelta(minutes=minutes)}:
                played += [(e.get("title", ""), e.get("artist", "")) for e in history.entries(day.strftime("%Y-%m-%d"))
                           if e.get("time", 0) >= since]
        for title, artist in played:
            t = normalize(title)
            if not t:
                continue
            if track:
                if normalize(track["title"]) == t and normalize(track["artist"].split(",")[0]) in normalize(artist):
                    return True
            elif _leftover(normalize(song), t, [normalize(a) for a in artist.split(",")]) <= FILLER_WORDS:
                return True
        return False

    def _event(self, status, user, platform, song):
        with self._events_lock:
            self._seq += 1
            self.events.append({"seq": self._seq, "status": status, "user": user, "platform": platform,
                                "song": song, "time": time.time()})

    def recent_events(self):
        with self._events_lock:
            return list(self.events)

    def start(self):
        self.twitch.start()
        self.youtube.start()
        self.tiktok.start()

    def status(self):
        s = self.settings()
        return {
            "request_enabled": bool(s["request_enabled"]), "request_cmd": s["request_cmd"],
            "request_max_user": s["request_max_user"], "request_max_total": s["request_max_total"],
            "request_autoplay": bool(s["request_autoplay"]),
            "request_block": s["request_block"], "request_max_minutes": _int(s["request_max_minutes"]),
            "request_recent_minutes": _int(s["request_recent_minutes"]),
            "autoplay": self.app.autoplay.status() if getattr(self.app, "autoplay", None) else None,
            "twitch": self.twitch.status(),
            "youtube": self.youtube.status(),
            "tiktok": self.tiktok.status(),
        }


def _int(v):
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0
