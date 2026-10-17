"""Listener chat live: membaca request lagu dari chat Twitch, YouTube, dan TikTok.

Hanya membaca. Tidak ada pesan yang dikirim ke chat mana pun. Setiap platform punya koneksinya
sendiri (chat_twitch.py, chat_youtube.py, chat_tiktok.py) dan memanggil ChatBot.handle(); request
yang valid masuk ke antrian (song_requests.py) yang tampil di halaman pengaturan dan overlay OBS.
"""

from .chat_tiktok import TikTokChat
from .chat_twitch import TwitchChat
from .chat_youtube import YouTubeChat
from .song_requests import RequestQueue

DEFAULTS = {"request_enabled": True, "request_cmd": "!request", "request_max_user": 2, "request_max_total": 50}


class ChatBot:
    def __init__(self, app, data_dir=None):
        self.app = app
        self.requests = RequestQueue(f"{data_dir}/requests.json" if data_dir else None)
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
        s = self.settings()
        status, _ = self.requests.add(song, user, platform, s["request_max_user"], s["request_max_total"])
        return status

    def start(self):
        self.twitch.start()
        self.youtube.start()
        self.tiktok.start()

    def status(self):
        s = self.settings()
        return {
            "request_enabled": bool(s["request_enabled"]), "request_cmd": s["request_cmd"],
            "request_max_user": s["request_max_user"], "request_max_total": s["request_max_total"],
            "twitch": self.twitch.status(),
            "youtube": self.youtube.status(),
            "tiktok": self.tiktok.status(),
        }
