import json
import socket
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest import mock

from spotify_now_playing import local_media, lyrics, server, updates


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
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.app = SimpleNamespace(
            cfg=FakeConfig(), status={"source": "idle", "error": ""}, cover=b"",
            account=SimpleNamespace(logged_in=False, redirect_uri="", logout=lambda: None),
            lyrics=lyrics.LyricsProvider(), updates=SimpleNamespace(available=None, check_now=lambda: None),
            snapshot=lambda: {"active": False})
        cls.server = server.start_server(cls.app, cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

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
        self.assertIn("lirik", err["error"].lower())

    def test_lyrics_search(self):
        with mock.patch.object(lyrics, "candidates", return_value=[{"id": 1}]) as c:
            status, body = self.post("/api/lyrics/search", {"title": "Judul", "artist": "Artis"})
        self.assertEqual((status, body), (200, {"results": [{"id": 1}]}))
        c.assert_called_once_with("Judul", "Artis")

    def test_second_server_on_same_port_fails(self):
        # dipakai untuk deteksi "aplikasi sudah berjalan"
        with self.assertRaises(OSError):
            server.start_server(self.app, self.port)

    def test_rejects_other_origin(self):
        status, _ = self.post("/api/config", {"source": "local"}, origin="https://evil.example")
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
