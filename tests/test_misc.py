import json
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest import mock

from spotify_now_playing import local_media, lyrics, server, updates
from spotify_now_playing.chatbot import ChatBot
from spotify_now_playing.history import History


class UpdatesTest(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updates.parse_version("v1.4.0"), (1, 4, 0))
        self.assertEqual(updates.parse_version("1.10"), (1, 10))
        self.assertEqual(updates.parse_version(""), (0,))

    def test_is_newer(self):
        self.assertTrue(updates.is_newer("v1.10.0", "1.9.3"))
        self.assertFalse(updates.is_newer("v1.4.0", "1.4.0"))
        self.assertFalse(updates.is_newer("1.3.9", "1.4.0"))

    def test_disabled_by_default(self):
        self.assertFalse(updates.UpdateChecker({}).enabled())


class PlayerNameTest(unittest.TestCase):
    def test_known_players(self):
        self.assertEqual(local_media.player_name("Spotify.exe"), "Spotify")
        self.assertEqual(local_media.player_name("MSEdge"), "Microsoft Edge")
        self.assertEqual(local_media.player_name("AppleInc.AppleMusicWin_nzyj5cx40ttak!App"), "Apple Music")

    def test_unknown_player(self):
        self.assertEqual(local_media.player_name("Contoso.Player_abc!App"), "Player")
        self.assertEqual(local_media.player_name("strange.exe"), "strange")
        self.assertEqual(local_media.player_name(None), "Player")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class FakeConfig(dict):
    def update(self, **values):
        for k, v in values.items():
            if v is None:
                self.pop(k, None)
            else:
                self[k] = v


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.now = {"active": False}
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.app = SimpleNamespace(
            cfg=FakeConfig(), status={"source": "idle", "error": ""}, cover=b"",
            account=SimpleNamespace(logged_in=False, redirect_uri="", logout=lambda: None),
            lyrics=lyrics.LyricsProvider(),
            updates=SimpleNamespace(available=None, status="off", check_now=lambda: None),
            history=History(cls.tmp.name), snapshot=lambda: dict(cls.now))
        cls.app.chat = ChatBot(cls.app)
        cls.server = server.start_server(cls.app, cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path):
        with urllib.request.urlopen(self.url(path), timeout=5) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def post(self, path, body, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(self.url(path), json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.load(e)

    def test_local_fonts_and_favicon(self):
        status, ctype, body = self.get("/static/fonts/inter-latin.woff2")
        self.assertEqual((status, ctype), (200, "font/woff2"))
        self.assertEqual(body[:4], b"wOF2")
        self.assertIn(b"@font-face", self.get("/static/fonts.css")[2])
        self.assertEqual(self.get("/favicon.ico")[1], "image/x-icon")

    def test_pages_do_not_use_google_fonts(self):
        for page in ("/overlay", "/lyrics", "/settings"):
            self.assertNotIn(b"fonts.googleapis.com", self.get(page)[2], page)

    def test_static_path_traversal(self):
        for path in ("/static/../server.py", "/static/fonts/../../config.py", "/static/x.py"):
            with self.assertRaises(urllib.error.HTTPError, msg=path) as ctx:
                self.get(path)
            ctx.exception.close()

    def test_presets_validation(self):
        status, cfg = self.post("/api/config", {"presets": {"gaming": {"width": 500}}})
        self.assertEqual(status, 200)
        self.assertEqual(cfg["presets"], {"gaming": {"width": 500}})
        status, _ = self.post("/api/config", {"presets": {"Nama Aneh!": {}}})
        self.assertEqual(status, 400)

    def test_players_and_updates_flags(self):
        _, cfg = self.post("/api/config", {"players": "all", "check_updates": True})
        self.assertEqual((cfg["players"], cfg["check_updates"]), ("all", True))
        _, cfg = self.post("/api/config", {"players": "nope"})
        self.assertEqual(cfg["players"], "all")

    def test_lyrics_actions_without_song(self):
        status, err = self.post("/api/lyrics/offset", {"offset": 1})
        self.assertEqual(status, 400)
        self.assertIn("lagu", err["error"].lower())

    def test_lyrics_search(self):
        with mock.patch.object(lyrics, "candidates", return_value=[{"id": 1}]) as c:
            status, body = self.post("/api/lyrics/search", {"title": "Judul", "artist": "Artis"})
        self.assertEqual((status, body), (200, {"results": [{"id": 1}]}))
        c.assert_called_once_with("Judul", "Artis")

    def test_now_txt(self):
        type(self).now = {"active": False}
        self.assertEqual(self.get("/api/now.txt?empty=-")[2], b"-")
        type(self).now = {"active": True, "title": "Judul", "artist": "Artis", "album": "A"}
        status, ctype, body = self.get("/api/now.txt")
        self.assertEqual((status, ctype, body.decode()), (200, "text/plain; charset=utf-8", "Artis - Judul"))
        self.assertEqual(self.get("/api/now.txt?format=%7Btitle%7D%20oleh%20%7Bartist%7D")[2].decode(),
                         "Judul oleh Artis")
        self.assertEqual(self.get("/api/now.txt?format=%7Btitle.x%7D")[2].decode(), "Artis - Judul")

    def test_settings_export_import_without_secrets(self):
        cfg = self.app.cfg
        cfg.update(overlay={"layout": "vinyl"}, client_secret="rahasia", tiktok_api_key="kunci",
                   ads={"mode": "quiet", "volume": 20, "text": "", "mute_pauses": True},
                   chat={"request_cmd": "!sr", "twitch": {"enabled": True, "channel": "tulus"},
                         "tiktok": {"enabled": False, "username": "tulus"}})
        status, ctype, body = self.get("/api/settings/export")
        text = body.decode()
        self.assertNotIn("rahasia", text)
        self.assertNotIn("kunci", text)
        data = json.loads(text)
        self.assertEqual(data["settings"]["overlay"], {"layout": "vinyl"})
        self.assertNotIn("mute_pauses", data["settings"]["ads"])
        cfg.update(overlay={"layout": "row"}, chat={})
        data["settings"]["chat"]["tiktok"]["api_key"] = "disisipkan"  # file diedit manual
        with mock.patch.object(self.app.chat.twitch, "restart"), mock.patch.object(self.app.chat.youtube, "restart"), \
             mock.patch.object(self.app.chat.tiktok, "restart"):
            status, _ = self.post("/api/settings/import", data)
        self.assertEqual(status, 200)
        self.assertEqual(cfg["overlay"], {"layout": "vinyl"})
        self.assertEqual(cfg["chat"]["twitch"]["channel"], "tulus")
        self.assertEqual(cfg["tiktok_api_key"], "kunci")  # tidak tertimpa isi file
        self.assertEqual(self.post("/api/settings/import", {"settings": {}})[0], 400)

    def test_diagnostics(self):
        self.app.cfg.update(tiktok_api_key="kunci-rahasia-123")
        status, ctype, body = self.get("/api/diagnostics")
        self.assertEqual(status, 200)
        self.assertIn("info diagnosa", body.decode())
        self.assertNotIn("kunci-rahasia-123", body.decode())

    def test_history_endpoints(self):
        self.app.history.add({"time": 1792246000, "title": "Lagu", "artist": "Artis", "album": "", "player": ""})
        h = json.loads(self.get("/api/history")[2])
        self.assertEqual(len(h["entries"]), 1)
        status, _, body = self.get(f"/api/history.txt?date={h['date']}&inline=1")
        self.assertIn("Artis - Lagu", body.decode())
        self.post("/api/history/clear", {"date": h["date"]})
        self.assertEqual(json.loads(self.get("/api/history")[2])["entries"], [])

    def test_history_txt_rejects_bad_date(self):
        with urllib.request.urlopen(self.url('/api/history.txt?date=x%22%0D%0AX:1'), timeout=5) as r:
            self.assertNotIn("X", dict(r.headers))
            self.assertIn('filename="riwayat-lagu-.txt"', r.headers["Content-Disposition"])

    def test_lang(self):
        _, cfg = self.post("/api/config", {"lang": "en"})
        self.assertEqual(cfg["lang"], "en")
        _, cfg = self.post("/api/config", {"lang": "xx"})
        self.assertEqual(cfg["lang"], "en")

    def test_chat_config(self):
        status, chat = self.post("/api/chat/config", {"request_cmd": "!sr", "request_max_user": 3,
                                                       "twitch": {"enabled": True, "channel": "#Tulus"}})
        self.assertEqual(status, 200)
        self.assertEqual((chat["request_cmd"], chat["request_max_user"]), ("!sr", 3))
        self.assertEqual((chat["twitch"]["channel"], chat["twitch"]["enabled"]), ("tulus", True))
        self.assertNotIn("client_id", chat["twitch"])  # Twitch tanpa login
        self.post("/api/chat/config", {"request_cmd": "!request", "request_max_user": 2,
                                       "twitch": {"enabled": False, "channel": ""}})

    def test_chat_config_validation(self):
        for body in ({"request_cmd": "dua kata"}, {"request_max_user": "x"},
                     {"youtube": {"client_id": "<script>"}}, {"twitch": {"channel": "nama aneh!"}}):
            status, _ = self.post("/api/chat/config", body)
            self.assertEqual(status, 400, body)

    def test_removed_reply_endpoints(self):
        for path in ("/api/chat/test", "/api/chat/twitch/login", "/api/chat/youtube/logout-bot"):
            status, _ = self.post(path, {})
            self.assertEqual(status, 404, path)

    def test_request_queue_endpoints(self):
        q = self.app.chat.requests
        q.clear()
        a = q.add("Lagu A", "budi", "tiktok")[1]["id"]
        b = q.add("Lagu B", "ani", "twitch")[1]["id"]
        status, ctype, body = self.get("/api/requests")
        r = json.loads(body)
        self.assertEqual(([i["text"] for i in r["items"]], r["cmd"], r["enabled"]), (["Lagu A", "Lagu B"], "!request", True))
        _, r = self.post("/api/requests/move", {"id": b, "delta": -1})
        self.assertEqual([i["id"] for i in r["items"]], [b, a])
        _, r = self.post("/api/requests/move", {"id": b, "delta": "naik"})  # input aneh tidak bikin error
        _, r = self.post("/api/requests/remove", {"id": a})
        self.assertEqual([i["id"] for i in r["items"]], [b])
        _, r = self.post("/api/requests/clear", {})
        self.assertEqual(r["items"], [])
        self.assertIn(b"Song Requests", self.get("/requests")[2])

    def test_tiktok_config(self):
        status, chat = self.post("/api/chat/config", {"tiktok": {"username": "@Tulus.Music", "api_key": "abcd1234"}})
        self.assertEqual(status, 200)
        self.assertEqual((chat["tiktok"]["username"], chat["tiktok"]["has_key"]), ("tulus.music", True))
        self.assertNotIn("abcd1234", json.dumps(chat))
        status, _ = self.post("/api/chat/config", {"tiktok": {"username": "nama aneh!"}})
        self.assertEqual(status, 400)
        self.post("/api/chat/config", {"tiktok": {"username": "", "api_key": ""}})

    def test_chat_secrets_not_exposed(self):
        self.post("/api/chat/config", {"youtube": {"client_id": "abc.apps.googleusercontent.com",
                                                   "client_secret": "rahasia1234"}})
        body = self.get("/api/chat")[2].decode()
        self.assertNotIn("rahasia1234", body)
        self.assertIn("1234", body)  # hanya 4 karakter terakhir sebagai petunjuk

    def test_youtube_login_without_credentials_redirects_back(self):
        self.app.cfg.pop("youtube_client_secret", None)
        opener = urllib.request.build_opener(NoRedirect)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            opener.open(self.url("/youtube/login"), timeout=5)
        self.assertEqual(ctx.exception.code, 302)
        self.assertTrue(ctx.exception.headers["Location"].startswith("/settings?chat=error"))
        ctx.exception.close()

    def test_second_server_on_same_port_fails(self):
        # dipakai untuk deteksi "aplikasi sudah berjalan"
        with self.assertRaises(OSError):
            server.start_server(self.app, self.port)

    def test_rejects_other_origin(self):
        status, _ = self.post("/api/config", {"source": "local"}, origin="https://evil.example")
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
