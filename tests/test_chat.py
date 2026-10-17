import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from spotify_now_playing import chat_twitch, chat_youtube
from spotify_now_playing.chatbot import ChatBot
from spotify_now_playing.history import History


class FakeConfig(dict):
    def update(self, **values):
        for k, v in values.items():
            if v is None:
                self.pop(k, None)
            else:
                self[k] = v


SONG = {"active": True, "playing": True, "title": "Pamit", "artist": "Tulus", "album": "Gajah"}


def make_bot(now=None, lang="id"):
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    state = {"now": dict(now or SONG)}
    app = SimpleNamespace(cfg=FakeConfig(lang=lang), snapshot=lambda: dict(state["now"]),
                          history=History(tmp.name))
    bot = ChatBot(app)
    return bot, app, state, tmp


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.bot, self.app, self.state, tmp = make_bot()
        self.addCleanup(tmp.cleanup)

    def test_song_command(self):
        self.assertEqual(self.bot.handle("twitch", "budi", "!song"), "@budi Sekarang diputar: Tulus - Pamit")
        self.assertEqual(self.bot.handle("youtube", "ani", "  !SONG tolong "), "@ani Sekarang diputar: Tulus - Pamit")

    def test_not_a_command(self):
        self.assertIsNone(self.bot.handle("twitch", "budi", "lagu apa ini? !song"))
        self.assertIsNone(self.bot.handle("twitch", "budi", ""))

    def test_cooldown_is_per_platform(self):
        self.app.cfg["chat"] = {"cooldown": 30}
        self.assertIsNotNone(self.bot.handle("twitch", "a", "!song"))
        self.assertIsNone(self.bot.handle("twitch", "b", "!song"))      # masih cooldown
        self.assertIsNotNone(self.bot.handle("youtube", "c", "!song"))  # platform lain jalan sendiri

    def test_nothing_playing(self):
        self.state["now"] = {"active": False}
        self.assertEqual(self.bot.handle("twitch", "budi", "!song"), "@budi Tidak ada lagu yang diputar")

    def test_custom_command_and_reply(self):
        self.app.cfg["chat"] = {"song_cmd": "!lagu", "song_reply": "{title} oleh {artist} ({album})"}
        self.assertIsNone(self.bot.handle("twitch", "a", "!song"))
        self.assertEqual(self.bot.handle("twitch", "a", "!lagu"), "Pamit oleh Tulus (Gajah)")

    def test_broken_template_falls_back(self):
        self.app.cfg["chat"] = {"song_reply": "{title.x} {nope}"}
        self.assertEqual(self.bot.handle("twitch", "a", "!song"), "@a Sekarang diputar: Tulus - Pamit")

    def test_disabled_command(self):
        self.app.cfg["chat"] = {"last_cmd": ""}
        self.assertIsNone(self.bot.handle("twitch", "a", "!lastsong"))

    def test_english_defaults(self):
        self.app.cfg["lang"] = "en"
        self.assertEqual(self.bot.handle("twitch", "bob", "!song"), "@bob Now playing: Tulus - Pamit")

    def test_previous_song_skips_current(self):
        for i, title in enumerate(["Lama", "Sebelumnya", "Pamit"]):
            self.app.history.add({"time": 1792246000 + i * 200, "title": title, "artist": "Tulus",
                                  "album": "", "player": ""})
        self.assertEqual(self.bot.handle("twitch", "a", "!lastsong"), "@a Lagu sebelumnya: Tulus - Sebelumnya")

    def test_reply_is_one_short_line(self):
        self.state["now"] = {**SONG, "title": "x\r\n" + "y" * 500}
        reply = self.bot.handle("twitch", "a", "!song")
        self.assertNotIn("\n", reply)
        self.assertLessEqual(len(reply), 200)


class IrcTest(unittest.TestCase):
    def test_parse_privmsg_with_tags(self):
        m = chat_twitch.parse_irc("@badges=;display-name=Budi\\sKeren;id=1 :budi!budi@budi.tmi.twitch.tv "
                                  "PRIVMSG #tulus :!song sekarang")
        self.assertEqual(m["command"], "PRIVMSG")
        self.assertEqual(m["params"], ["#tulus", "!song sekarang"])
        self.assertEqual(m["tags"]["display-name"], "Budi Keren")
        self.assertEqual(m["prefix"], "budi!budi@budi.tmi.twitch.tv")

    def test_parse_ping_and_numeric(self):
        self.assertEqual(chat_twitch.parse_irc("PING :tmi.twitch.tv")["params"], ["tmi.twitch.tv"])
        self.assertEqual(chat_twitch.parse_irc(":tmi.twitch.tv 001 bot :Welcome")["command"], "001")

    def make_chat(self, reply="halo"):
        chat = chat_twitch.TwitchChat(FakeConfig(), lambda platform, user, text: reply if text == "!song" else None)
        sent = []
        chat._sock = SimpleNamespace(sendall=lambda b: sent.append(b.decode()))
        return chat, sent

    def test_replies_to_command(self):
        chat, sent = self.make_chat()
        chat._handle("@display-name=Budi :budi!budi@x PRIVMSG #tulus :!song", "tulus")
        chat._handle(":ani!ani@x PRIVMSG #tulus :halo semua", "tulus")
        self.assertEqual(sent, ["PRIVMSG #tulus :halo\r\n"])

    def test_ping_pong_and_state(self):
        chat, sent = self.make_chat()
        chat._handle("PING :tmi.twitch.tv", "tulus")
        chat._handle("@emote-only=0 :tmi.twitch.tv ROOMSTATE #tulus", "tulus")
        self.assertEqual(sent, ["PONG :tmi.twitch.tv\r\n"])
        self.assertEqual(chat.state, "connected")

    def test_auth_failure(self):
        chat, _ = self.make_chat()
        with self.assertRaises(chat_twitch.AuthFailed):
            chat._handle(":tmi.twitch.tv NOTICE * :Login authentication failed", "tulus")

    def test_device_login_needs_client_id(self):
        chat, _ = self.make_chat()
        with self.assertRaises(ValueError):
            chat.begin_login()


class YouTubeTest(unittest.TestCase):
    def test_poll_skips_old_messages_and_replies_to_new(self):
        handled = []
        chat = chat_youtube.YouTubeChat(FakeConfig(), lambda p, u, t: handled.append((p, u, t)) or
                                        ("balas" if t == "!song" else None))
        msg = lambda text: {"snippet": {"displayMessage": text}, "authorDetails": {"displayName": "Ani"}}
        pages = [
            {"items": [msg("!song")], "nextPageToken": "a", "pollingIntervalMillis": 0},  # sebelum bot nyambung
            {"items": [msg("halo"), msg("!song")], "nextPageToken": "b", "pollingIntervalMillis": 0},
        ]
        sent = []

        def fake_api(method, path, params, body=None):
            if method == "POST":
                sent.append(body["snippet"]["textMessageDetails"]["messageText"])
                return {}
            if pages:
                return pages.pop(0)
            raise chat_youtube.YouTubeError("ended", "liveChatEnded")

        with mock.patch.object(chat, "_api", fake_api), mock.patch.object(chat_youtube, "POLL_MIN", 0):
            chat._poll("chat1")
        self.assertEqual(handled, [("youtube", "Ani", "halo"), ("youtube", "Ani", "!song")])
        self.assertEqual(sent, ["balas"])

    def test_login_url_needs_credentials(self):
        chat = chat_youtube.YouTubeChat(FakeConfig(), lambda *a: None)
        with self.assertRaises(ValueError):
            chat.login_url()

    def test_login_url_uses_pkce(self):
        cfg = FakeConfig(chat={"youtube": {"client_id": "abc.apps.googleusercontent.com"}},
                         youtube_client_secret="s")
        chat = chat_youtube.YouTubeChat(cfg, lambda *a: None)
        chat.redirect_uri = "http://127.0.0.1:8765/youtube/callback"
        url = chat.login_url()
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("access_type=offline", url)
        with self.assertRaises(ValueError):
            chat.finish_login("state-lain", "code")

    def test_expired_refresh_token_logs_out(self):
        cfg = FakeConfig(chat={"youtube": {"client_id": "abc"}}, youtube_client_secret="s",
                         youtube_auth={"access_token": "x", "refresh_token": "r", "expires_at": 0})
        chat = chat_youtube.YouTubeChat(cfg, lambda *a: None)
        with mock.patch.object(chat_youtube, "_request",
                               side_effect=chat_youtube.YouTubeError("bad", "invalid_grant")):
            with self.assertRaises(chat_youtube.AuthFailed):
                chat._token()


if __name__ == "__main__":
    unittest.main()
