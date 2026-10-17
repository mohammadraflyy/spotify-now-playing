"""Bot chat bawaan: menjawab !song, !lastsong, perintah buatan user, dan menerima !request lagu.

Setiap platform punya koneksinya sendiri (chat_twitch.py, chat_youtube.py, chat_tiktok.py).
Semuanya memanggil ChatBot.handle(platform, user, text), dan jawabannya dikirim balik ke
platform asal pesan. TikTok hanya listener: request dicatat, tapi tidak ada balasan di chat.
"""

import threading
import time

from . import i18n
from .chat_tiktok import TikTokChat
from .chat_twitch import TwitchChat
from .chat_youtube import YouTubeChat
from .song_requests import RequestQueue

DEFAULTS = {"song_cmd": "!song", "last_cmd": "!lastsong", "cooldown": 5,
            "request_enabled": True, "request_cmd": "!request", "request_max_user": 2, "request_max_total": 50}
REPLIES = {
    "id": {
        "song": "@{user} Sekarang diputar: {artist} - {title}",
        "last": "@{user} Lagu sebelumnya: {artist} - {title}",
        "none": "@{user} Tidak ada lagu yang diputar",
        "request_added": "@{user} request masuk: {request} (antrian ke-{position})",
        "request_duplicate": "@{user} {request} sudah ada di antrian (ke-{position})",
        "request_user_limit": "@{user} kamu sudah punya {max} request di antrian",
        "request_full": "@{user} antrian request sedang penuh",
        "request_empty": "@{user} ketik {cmd} judul lagu, misalnya {cmd} Tulus - Pamit",
    },
    "en": {
        "song": "@{user} Now playing: {artist} - {title}",
        "last": "@{user} Previous song: {artist} - {title}",
        "none": "@{user} Nothing is playing right now",
        "request_added": "@{user} request added: {request} (#{position} in the queue)",
        "request_duplicate": "@{user} {request} is already in the queue (#{position})",
        "request_user_limit": "@{user} you already have {max} requests in the queue",
        "request_full": "@{user} the request queue is full right now",
        "request_empty": "@{user} type {cmd} and a song title, for example {cmd} Tulus - Pamit",
    },
}
MAX_REPLY = 200  # YouTube membatasi 200 karakter, Twitch 500


def render(template, fallback, **values):
    """Isi template; kalau template buatan user rusak, pakai template bawaan."""
    for tpl in (template, fallback):
        try:
            return tpl.format(**values).replace("\r", " ").replace("\n", " ").strip()[:MAX_REPLY]
        except (KeyError, IndexError, ValueError, AttributeError):
            continue
    return ""


class ChatBot:
    def __init__(self, app, data_dir=None):
        self.app = app
        self.lock = threading.Lock()
        self._last_used = {}
        self.requests = RequestQueue(f"{data_dir}/requests.json" if data_dir else None)
        self.twitch = TwitchChat(app.cfg, self.handle)
        self.youtube = YouTubeChat(app.cfg, self.handle)
        self.tiktok = TikTokChat(app.cfg, self.handle)

    def settings(self):
        return {**DEFAULTS, **(self.app.cfg.get("chat") or {})}

    def template(self, kind):
        lang = i18n.lang(self.app.cfg)
        return (self.settings().get(f"{kind}_reply") or REPLIES[lang][kind]), REPLIES[lang][kind]

    def command_kind(self, text):
        words = (text or "").strip().split()
        if not words:
            return None
        cmd, s = words[0].lower(), self.settings()
        for kind in ("song", "last"):
            if s.get(f"{kind}_cmd") and cmd == s[f"{kind}_cmd"].strip().lower():
                return kind
        if s.get("request_enabled") and s.get("request_cmd") and cmd == s["request_cmd"].strip().lower():
            return "request"
        for i, c in enumerate(self.custom()):
            if cmd == c["cmd"].lower():
                return f"custom:{i}"
        return None

    def custom(self):
        """Perintah buatan user: [{"cmd": "!discord", "reply": "..."}]."""
        return [c for c in self.settings().get("custom") or []
                if isinstance(c, dict) and c.get("cmd") and c.get("reply")]

    def handle(self, platform, user, text):
        """Pesan chat masuk. Return teks jawaban, atau None kalau bukan perintah / masih cooldown."""
        kind = self.command_kind(text)
        if not kind:
            return None
        if kind == "request":  # punya batas per penonton sendiri, tanpa cooldown
            return self.request(user, text, platform)
        if platform == "tiktok":
            return None  # TikTok hanya listener: perintah yang butuh balasan diabaikan
        cooldown = max(0, min(600, float(self.settings().get("cooldown") or 0)))
        now = time.monotonic()
        with self.lock:
            last = self._last_used.get((platform, kind))
            if last is not None and now - last < cooldown:
                return None
            self._last_used[(platform, kind)] = now
        return self.answer(kind, user)

    def answer(self, kind, user, text=""):
        """Balasan untuk perintah. Request di sini hanya pratinjau (tidak masuk antrian)."""
        if kind == "request":
            return self.request(user, text, None, dry_run=True)
        if kind.startswith("custom:"):
            reply = self.custom()[int(kind[7:])]["reply"]
            song = self.current_song() or {}
            return render(reply, "", user=user, title=song.get("title", ""), artist=song.get("artist", ""),
                          album=song.get("album", ""))
        song = self.current_song() if kind == "song" else self.previous_song()
        if song is None:
            tpl, fallback = self.template("none")
            return render(tpl, fallback, user=user, title="", artist="", album="")
        tpl, fallback = self.template(kind)
        return render(tpl, fallback, user=user, title=song["title"], artist=song["artist"],
                      album=song.get("album", ""))

    def request(self, user, text, platform, dry_run=False):
        s = self.settings()
        cmd = s["request_cmd"]
        song = text.strip()[len(cmd):].strip() if text.strip().lower().startswith(cmd.lower()) else ""
        lang = i18n.lang(self.app.cfg)
        if dry_run:
            status, info = ("added", {"position": len(self.requests.list()) + 1, "text": song}) if song else ("empty", {})
        else:
            status, info = self.requests.add(song, user, platform, s["request_max_user"], s["request_max_total"])
        tpl = REPLIES[lang][f"request_{status}"]
        return render(tpl, tpl, user=user, request=info.get("text", song), position=info.get("position", ""),
                      max=info.get("max", ""), cmd=cmd)

    def current_song(self):
        s = self.app.snapshot()
        return s if s.get("active") else None

    def previous_song(self):
        """Lagu terakhir di riwayat yang bukan lagu yang sedang diputar."""
        cur = self.current_song()
        cur_key = f"{cur['title']}|{cur['artist']}" if cur else None
        history = self.app.history
        for date in history.dates()[:2]:
            for e in reversed(history.entries(date)):
                if f"{e['title']}|{e['artist']}" != cur_key:
                    return e
        return None

    def start(self):
        self.twitch.start()
        self.youtube.start()
        self.tiktok.start()

    def status(self):
        s = self.settings()
        lang = i18n.lang(self.app.cfg)
        return {
            "song_cmd": s["song_cmd"], "last_cmd": s["last_cmd"], "cooldown": s["cooldown"],
            "song_reply": s.get("song_reply") or "", "last_reply": s.get("last_reply") or "",
            "none_reply": s.get("none_reply") or "",
            "custom": self.custom(),
            "request_enabled": bool(s["request_enabled"]), "request_cmd": s["request_cmd"],
            "request_max_user": s["request_max_user"], "request_max_total": s["request_max_total"],
            "default_replies": REPLIES[lang],
            "twitch": self.twitch.status(),
            "youtube": self.youtube.status(),
            "tiktok": self.tiktok.status(),
        }
