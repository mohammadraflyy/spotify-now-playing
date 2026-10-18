import tempfile
import unittest
from types import SimpleNamespace

from spotify_now_playing.autoplay import LEAD, AutoPlayer
from spotify_now_playing.chatbot import ChatBot
from spotify_now_playing.song_requests import RequestQueue


class FakeConfig(dict):
    def update(self, **values):
        for k, v in values.items():
            if v is None:
                self.pop(k, None)
            else:
                self[k] = v


def track(title, artist):
    return {"uri": f"spotify:track:{title.lower()}", "id": title.lower(), "title": title, "artist": artist,
            "album": "", "duration": 200.0}


CATALOG = {"pamit": track("Pamit", "Tulus"), "evaluasi": track("Evaluasi", "Hindia")}


class Setup(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.snap = {"active": True, "ad": False, "playing": True, "title": "Lagu A", "artist": "X",
                     "position": 10.0, "duration": 200.0}
        self.app = SimpleNamespace(cfg=FakeConfig(), snapshot=lambda: dict(self.snap),
                                   account=SimpleNamespace(logged_in=True, can_control=True))
        self.app.chat = ChatBot(self.app, tmp.name)
        self.queued, self.searches = [], []
        self.spotify_next = track("Dari Playlist", "Band")

        def search(account, text):
            self.searches.append(text)
            return next((t for k, t in CATALOG.items() if k in text.lower()), None)

        self.ap = AutoPlayer(self.app, search=search, add=lambda acc, uri: self.queued.append(uri),
                             peek=lambda acc: self.spotify_next)
        self.app.autoplay = self.ap

    def near_end(self, title="Lagu A"):
        self.snap.update(title=title, position=self.snap["duration"] - LEAD + 2)


class RequestTest(Setup):
    def test_request_is_looked_up_on_spotify(self):
        self.assertEqual(self.app.chat.handle("tiktok", "budi", "!request tulus pamit dong"), "added")
        item = self.app.chat.requests.list()[0]
        self.assertEqual(item["track"]["uri"], "spotify:track:pamit")
        self.assertEqual(self.app.chat.handle("twitch", "ani", "!request Pamit - Tulus"), "duplicate")  # lagu sama
        self.assertEqual(self.app.chat.handle("tiktok", "cici", "!request lagu yang tidak ada"), "not_found")
        self.assertEqual(len(self.app.chat.requests.list()), 1)

    def test_spotify_error_falls_back_to_manual(self):
        def boom(account, text):
            raise RuntimeError("503")
        self.ap.search = boom
        self.assertEqual(self.app.chat.handle("tiktok", "budi", "!request Pamit"), "added")
        self.assertNotIn("track", self.app.chat.requests.list()[0])

    def test_off_without_premium_login(self):
        self.app.account.can_control = False
        self.app.chat.handle("tiktok", "budi", "!request Pamit")
        self.assertEqual(self.searches, [])


class PushTest(Setup):
    def test_pushes_top_request_once_near_the_end(self):
        for text in ("!request Pamit", "!request Evaluasi"):
            self.app.chat.handle("tiktok", "budi", text)
        self.ap.step(0)
        self.assertEqual(self.queued, [])  # masih jauh dari akhir lagu
        self.near_end()
        self.ap.step(1)
        self.ap.step(2)
        self.assertEqual(self.queued, ["spotify:track:pamit"])  # sekali per lagu
        self.assertTrue(self.app.chat.requests.list()[0]["queued"])
        # request diputar -> keluar dari antrian; menjelang akhir lagu itu, request berikutnya dikirim
        self.app.chat.requests.match_playing("Pamit", "Tulus")
        self.snap.update(title="Pamit", artist="Tulus", position=5)
        self.ap.step(3)
        self.near_end("Pamit")
        self.ap.step(4)
        self.assertEqual(self.queued, ["spotify:track:pamit", "spotify:track:evaluasi"])

    def test_reorder_is_respected(self):
        for text in ("!request Pamit", "!request Evaluasi"):
            self.app.chat.handle("tiktok", "budi", text)
        second = self.app.chat.requests.list()[1]["id"]
        self.app.chat.requests.move(second, -1)
        self.near_end()
        self.ap.step(1)
        self.assertEqual(self.queued, ["spotify:track:evaluasi"])

    def test_old_request_is_searched_when_pushed(self):
        self.app.chat.requests.add("Evaluasi", "budi", "tiktok")  # masuk sebelum login
        self.app.chat.requests.add("tidak ada", "ani", "tiktok")
        self.near_end()
        self.ap.step(1)
        self.assertEqual(self.queued, ["spotify:track:evaluasi"])
        self.app.chat.requests.match_playing("Evaluasi", "Hindia")
        self.near_end("Evaluasi")
        self.ap.step(2)
        self.assertEqual(len(self.queued), 1)
        self.assertTrue(self.app.chat.requests.list()[0]["not_found"])

    def test_search_url_needs_no_extra_scope(self):
        from spotify_now_playing import spotify_api
        paths = []
        acc = type("A", (), {"get": lambda self, path: paths.append(path) or (200, {"tracks": {"items": []}})})()
        self.assertIsNone(spotify_api.search_track(acc, "Pamit"))
        self.assertNotIn("market=", paths[0])  # market=from_token butuh izin user-read-private

    def test_request_without_track_is_resolved_for_next(self):
        self.app.chat.requests.add("Evaluasi", "budi", "tiktok")  # masuk saat pencarian gagal
        self.ap.step(0)
        self.assertEqual((self.ap.next["title"], self.ap.next["source"]), ("Evaluasi", "request"))
        self.assertEqual(self.queued, [])  # belum dikirim: lagu sekarang masih lama

    def test_nothing_during_ads_or_pause(self):
        self.app.chat.handle("tiktok", "budi", "!request Pamit")
        self.near_end()
        self.snap["playing"] = False
        self.ap.step(1)
        self.snap.update(playing=True, ad=True)
        self.ap.step(2)
        self.assertEqual(self.queued, [])

    def test_error_is_reported(self):
        self.app.chat.handle("tiktok", "budi", "!request Pamit")

        def fail(account, uri):
            raise RuntimeError("Spotify tidak aktif")
        self.ap.add = fail
        self.near_end()
        self.ap.step(1)
        self.assertIn("tidak aktif", self.ap.status()["error"])
        self.assertNotIn("queued", self.app.chat.requests.list()[0])


class NextTest(Setup):
    def test_next_prefers_request_then_spotify_queue(self):
        self.ap.step(0)
        self.assertEqual((self.ap.next["title"], self.ap.next["source"]), ("Dari Playlist", "spotify"))
        self.app.chat.handle("tiktok", "budi", "!request Pamit")
        self.ap.step(1)
        self.assertEqual(self.ap.next, {"title": "Pamit", "artist": "Tulus", "source": "request",
                                        "user": "budi", "platform": "tiktok"})

    def test_spotify_queue_is_polled_sparingly(self):
        calls = []
        self.ap.peek = lambda acc: calls.append(1) or self.spotify_next
        for now in range(10):
            self.ap.step(now)
        self.assertEqual(len(calls), 1)
        self.snap["title"] = "Lagu B"  # ganti lagu: baca lagi
        self.ap.step(11)
        self.assertEqual(len(calls), 2)

    def test_no_next_without_login(self):
        self.app.account = SimpleNamespace(logged_in=False, can_control=False)
        self.ap.step(0)
        self.assertIsNone(self.ap.next)


class BestMatchTest(unittest.TestCase):
    def pick(self, query, rows):
        from spotify_now_playing.spotify_api import best_match
        got = best_match(query, [track(t, a) for a, t in rows])
        return f"{got['artist']} - {got['title']}" if got else None

    def test_picks_title_named_in_request(self):
        rows = [("Tulus", "Hati-Hati di Jalan"), ("Tulus", "Pamit"), ("Tulus", "Pamit - Live")]
        self.assertEqual(self.pick("tulus pamit", rows), "Tulus - Pamit")
        self.assertEqual(self.pick("tolong putar pamit dong kak", rows), "Tulus - Pamit")
        self.assertEqual(self.pick("tulus pamit live", rows), "Tulus - Pamit - Live")  # versi diminta

    def test_title_must_not_be_just_the_artist_name(self):
        rows = [("Nadin Amizah", "Nadin Amizah"), ("Nadin Amizah", "Bertaut")]
        self.assertEqual(self.pick("nadin amizah bertaut", rows), "Nadin Amizah - Bertaut")

    def test_falls_back_to_spotify_order(self):
        self.assertEqual(self.pick("tlus pamitt", [("Tulus", "Pamit"), ("X", "Y")]), "Tulus - Pamit")
        self.assertIsNone(self.pick("apa saja", []))


class MatchTest(unittest.TestCase):
    def test_request_shows_matched_song(self):
        q = RequestQueue(None)
        q.add("tolong putar pamit dong", "budi", "tiktok", track=track("Pamit", "Tulus"))
        item = q.list()[0]
        self.assertEqual((item["text"], item["asked"]), ("Tulus - Pamit", "tolong putar pamit dong"))
        self.assertEqual(q.add("tolong putar pamit dong", "ani", "tiktok")[0], "duplicate")  # teks asli sama
        q.add("evaluasi", "cici", "twitch")
        q.update(q.list()[1]["id"], track=track("Evaluasi", "Hindia"))  # dicari belakangan
        self.assertEqual(q.list()[1]["text"], "Hindia - Evaluasi")

    def test_match_uses_spotify_track(self):
        q = RequestQueue(None)
        q.add("tolong putar lagu galau dari tulus dong", "budi", "tiktok", track=track("Pamit", "Tulus"))
        self.assertIsNone(q.match_playing("Pamit", "Artis Lain"))
        self.assertEqual(q.match_playing("Pamit", "Tulus")["user"], "budi")


if __name__ == "__main__":
    unittest.main()
