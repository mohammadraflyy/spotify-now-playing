import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from spotify_now_playing import chat_twitch, chat_youtube
from spotify_now_playing.chatbot import ChatBot


class FakeConfig(dict):
    def update(self, **values):
        for k, v in values.items():
            if v is None:
                self.pop(k, None)
            else:
                self[k] = v


def make_bot(cfg=None):
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    app = SimpleNamespace(cfg=cfg if cfg is not None else FakeConfig())
    return ChatBot(app, tmp.name), app, tmp


class ChatBotTest(unittest.TestCase):
    def setUp(self):
        self.bot, self.app, tmp = make_bot()
        self.addCleanup(tmp.cleanup)

    def test_request_command(self):
        self.assertEqual(self.bot.request_text("!request Tulus - Pamit"), "Tulus - Pamit")
        self.assertEqual(self.bot.request_text("  !REQUEST   Hindia  "), "Hindia")
        self.assertEqual(self.bot.request_text("!request"), "")
        self.assertIsNone(self.bot.request_text("tolong !request Pamit"))
        self.assertIsNone(self.bot.request_text("!song"))

    def test_handle_adds_to_queue_without_reply(self):
        self.assertEqual(self.bot.handle("twitch", "budi", "!request Tulus - Pamit"), "added")
        self.assertEqual(self.bot.handle("youtube", "ani", "!request tulus pamit"), "duplicate")
        self.assertIsNone(self.bot.handle("tiktok", "cici", "halo semua"))
        self.assertEqual([(i["platform"], i["text"]) for i in self.bot.requests.list()], [("twitch", "Tulus - Pamit")])

    def test_settings(self):
        self.app.cfg["chat"] = {"request_cmd": "!sr", "request_max_user": 1}
        self.assertEqual(self.bot.handle("tiktok", "budi", "!sr Lagu A"), "added")
        self.assertEqual(self.bot.handle("tiktok", "budi", "!sr Lagu B"), "user_limit")
        self.app.cfg["chat"] = {"request_enabled": False}
        self.assertIsNone(self.bot.handle("tiktok", "x", "!request Lagu C"))

    def test_migration_drops_old_logins_and_keeps_channel(self):
        cfg = FakeConfig(twitch_auth={"login": "Tulus", "access_token": "x"}, youtube_bot_auth={"access_token": "y"},
                         chat={"twitch": {"enabled": True}})
        bot, _, tmp = make_bot(cfg)
        self.addCleanup(tmp.cleanup)
        self.assertNotIn("twitch_auth", cfg)
        self.assertNotIn("youtube_bot_auth", cfg)
        self.assertEqual(cfg["chat"]["twitch"], {"enabled": True, "channel": "tulus"})
        self.assertEqual(bot.status()["twitch"]["channel"], "tulus")


class IrcTest(unittest.TestCase):
    def test_parse_privmsg_with_tags(self):
        m = chat_twitch.parse_irc("@badges=;display-name=Budi\\sKeren;id=1 :budi!budi@budi.tmi.twitch.tv "
                                  "PRIVMSG #tulus :!request Pamit")
        self.assertEqual(m["command"], "PRIVMSG")
        self.assertEqual(m["params"], ["#tulus", "!request Pamit"])
        self.assertEqual(m["tags"]["display-name"], "Budi Keren")

    def test_parse_ping_and_numeric(self):
        self.assertEqual(chat_twitch.parse_irc("PING :tmi.twitch.tv")["params"], ["tmi.twitch.tv"])
        self.assertEqual(chat_twitch.parse_irc(":tmi.twitch.tv 001 justinfan1 :Welcome")["command"], "001")

    def make_chat(self):
        got = []
        chat = chat_twitch.TwitchChat(FakeConfig(), lambda p, u, t: got.append((p, u, t)))
        sent = []
        chat._sock = SimpleNamespace(sendall=lambda b: sent.append(b.decode()))
        return chat, got, sent

    def test_messages_are_passed_on_and_never_answered(self):
        chat, got, sent = self.make_chat()
        chat._handle("@display-name=Budi :budi!budi@x PRIVMSG #tulus :!request Pamit")
        chat._handle(":ani!ani@x PRIVMSG #tulus :halo")
        self.assertEqual(got, [("twitch", "Budi", "!request Pamit"), ("twitch", "ani", "halo")])
        self.assertEqual(sent, [])  # listener: tidak pernah mengirim PRIVMSG

    def test_ping_pong_and_state(self):
        chat, _, sent = self.make_chat()
        chat._handle("PING :tmi.twitch.tv")
        chat._handle(":tmi.twitch.tv 001 justinfan12345 :Welcome, GLHF!")
        self.assertEqual(sent, ["PONG :tmi.twitch.tv\r\n"])
        self.assertEqual(chat.state, "connected")

    def test_anonymous_login(self):
        chat = chat_twitch.TwitchChat(FakeConfig(chat={"twitch": {"enabled": True, "channel": "#Tulus"}}),
                                      lambda *a: None)
        sent = []

        class FakeSSL:
            def sendall(self, b):
                sent.append(b.decode().strip())

            def settimeout(self, t):
                pass

            def recv(self, n):
                return b""

            def close(self):
                pass

        with mock.patch.object(chat_twitch.socket, "create_connection", return_value=object()), \
             mock.patch.object(chat_twitch.ssl, "create_default_context") as ctx:
            ctx.return_value.wrap_socket.return_value = FakeSSL()
            with self.assertRaises(ConnectionError):
                chat._session()
        self.assertRegex(sent[1], r"^NICK justinfan\d+$")
        self.assertEqual(sent[2], "JOIN #tulus")
        self.assertFalse(any(line.startswith("PASS") for line in sent))

    def test_setup_state_without_channel(self):
        chat = chat_twitch.TwitchChat(FakeConfig(chat={"twitch": {"enabled": True, "channel": "a b"}}),
                                      lambda *a: None)
        chat.start()
        deadline = time.time() + 2
        while chat.state != "setup" and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(chat.state, "setup")


class YouTubeTest(unittest.TestCase):
    def test_poll_reads_new_messages_only(self):
        handled = []
        chat = chat_youtube.YouTubeChat(FakeConfig(), lambda p, u, t: handled.append((p, u, t)))
        msg = lambda text: {"snippet": {"displayMessage": text}, "authorDetails": {"displayName": "Ani"}}
        pages = [
            {"items": [msg("!request lama")], "nextPageToken": "a", "pollingIntervalMillis": 0},  # sebelum tersambung
            {"items": [msg("halo"), msg("!request Pamit")], "nextPageToken": "b", "pollingIntervalMillis": 0},
        ]
        methods = []

        def fake_api(method, path, params):
            methods.append(method)
            if pages:
                return pages.pop(0)
            raise chat_youtube.YouTubeError("ended", "liveChatEnded")

        with mock.patch.object(chat, "_api", fake_api), mock.patch.object(chat_youtube, "POLL_MIN", 0):
            chat._poll("chat1")
        self.assertEqual(handled, [("youtube", "Ani", "halo"), ("youtube", "Ani", "!request Pamit")])
        self.assertEqual(set(methods), {"GET"})  # tidak pernah mengirim pesan

    def test_login_url_is_read_only(self):
        cfg = FakeConfig(chat={"youtube": {"client_id": "abc.apps.googleusercontent.com"}}, youtube_client_secret="s")
        chat = chat_youtube.YouTubeChat(cfg, lambda *a: None)
        chat.redirect_uri = "http://127.0.0.1:8765/youtube/callback"
        url = chat.login_url()
        self.assertIn("youtube.readonly", url)
        self.assertNotIn("force-ssl", url)
        self.assertIn("code_challenge_method=S256", url)
        with self.assertRaises(ValueError):
            chat.finish_login("state-lain", "code")

    def test_finish_login(self):
        cfg = FakeConfig(chat={"youtube": {"client_id": "abc.apps.googleusercontent.com"}}, youtube_client_secret="s")
        chat = chat_youtube.YouTubeChat(cfg, lambda *a: None)
        state = chat.login_url().split("state=")[1].split("&")[0]
        tok = {"access_token": "t", "refresh_token": "r", "expires_in": 3600}
        with mock.patch.object(chat_youtube, "_request", return_value=tok), \
             mock.patch.object(chat, "_api", return_value={"items": [{"snippet": {"title": "Tulus"}}]}):
            chat.finish_login(state, "code")
        self.assertEqual((cfg["youtube_auth"]["channel"], cfg["youtube_auth"]["refresh_token"]), ("Tulus", "r"))

    def test_login_url_needs_credentials(self):
        with self.assertRaises(ValueError):
            chat_youtube.YouTubeChat(FakeConfig(), lambda *a: None).login_url()

    def test_expired_refresh_token(self):
        cfg = FakeConfig(chat={"youtube": {"client_id": "abc"}}, youtube_client_secret="s",
                         youtube_auth={"access_token": "x", "refresh_token": "r", "expires_at": 0})
        chat = chat_youtube.YouTubeChat(cfg, lambda *a: None)
        with mock.patch.object(chat_youtube, "_request", side_effect=chat_youtube.YouTubeError("bad", "invalid_grant")):
            with self.assertRaises(chat_youtube.AuthFailed):
                chat._token()


if __name__ == "__main__":
    unittest.main()
