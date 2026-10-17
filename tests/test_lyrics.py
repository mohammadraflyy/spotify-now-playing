import tempfile
import time
import unittest
from unittest import mock

from spotify_now_playing import lyrics

SYNCED = "[00:01.50] satu\n[00:03.00] dua\n[00:05.25][00:09.00] ulang\nbaris tanpa waktu\n"


def wait_for(cond, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class ParseTest(unittest.TestCase):
    def test_parse_lrc(self):
        self.assertEqual(lyrics.parse_lrc(SYNCED),
                         [(1.5, "satu"), (3.0, "dua"), (5.25, "ulang"), (9.0, "ulang")])

    def test_parse_lrc_empty(self):
        self.assertEqual(lyrics.parse_lrc(None), [])
        self.assertEqual(lyrics.parse_lrc("tanpa timestamp"), [])

    def test_clean_title(self):
        cases = {
            "Song - 2011 Remaster": "Song",
            "Song (Remastered 2009)": "Song",
            "Song - Live": "Song",
            "Song (feat. Someone)": "Song",
            "Hati-Hati di Jalan": "Hati-Hati di Jalan",
            "(Live)": "(Live)",  # jangan sampai jadi kosong
        }
        for raw, want in cases.items():
            self.assertEqual(lyrics.clean_title(raw), want, raw)


class PickTest(unittest.TestCase):
    def test_prefers_close_duration_then_synced(self):
        results = [
            {"id": 1, "duration": 200, "plainLyrics": "x"},
            {"id": 2, "duration": 202, "syncedLyrics": "[00:01.00]a"},
            {"id": 3, "duration": 260, "syncedLyrics": "[00:01.00]a"},
        ]
        self.assertEqual(lyrics._pick(results, 200)["id"], 2)

    def test_rejects_other_song(self):
        self.assertIsNone(lyrics._pick([{"duration": 300, "syncedLyrics": "[00:01.00]a"}], 200))

    def test_ignores_empty(self):
        self.assertIsNone(lyrics._pick([{"duration": 200}], 200))


class SearchTest(unittest.TestCase):
    def test_falls_back_to_search(self):
        calls = []

        def fake_get(path, params):
            calls.append(path)
            if path == "get":
                return None
            return [{"id": 7, "duration": 180, "syncedLyrics": SYNCED}]

        with mock.patch.object(lyrics, "_get", fake_get):
            r = lyrics.search("Song (feat. X)", "Artist, Other", "Album", 180)
        self.assertEqual(calls, ["get", "search"])
        self.assertEqual(r["status"], "synced")
        self.assertEqual(r["lrclib_id"], 7)
        self.assertEqual(r["lines"][0], {"t": 1.5, "text": "satu"})

    def test_raises_only_when_all_fail(self):
        def boom(path, params):
            raise OSError("503")
        with mock.patch.object(lyrics, "_get", boom):
            with self.assertRaises(OSError):
                lyrics.search("a", "b", "c", 100)

    def test_partial_failure_is_an_error_not_none(self):
        # /get 404 lalu /search 503: belum pasti tidak ada lirik, jadi jangan di-cache sebagai "none"
        def fake_get(path, params):
            if path == "get":
                return None
            raise OSError("503")
        with mock.patch.object(lyrics, "_get", fake_get):
            with self.assertRaises(OSError):
                lyrics.search("a", "b", "c", 100)

    def test_not_found(self):
        with mock.patch.object(lyrics, "_get", lambda p, q: None if p == "get" else []):
            self.assertEqual(lyrics.search("a", "b", "c", 100)["status"], "none")

    def test_candidates(self):
        rows = [{"id": 1, "trackName": "T", "artistName": "A", "albumName": "B", "duration": 99,
                 "syncedLyrics": "[00:01.00]x"}, {"trackName": "tanpa id"}]
        with mock.patch.object(lyrics, "_get", lambda p, q: rows):
            got = lyrics.candidates("T", "A")
        self.assertEqual(got, [{"id": 1, "title": "T", "artist": "A", "album": "B", "duration": 99,
                                "synced": True, "instrumental": False}])


class ProviderTest(unittest.TestCase):
    def setUp(self):
        # thread pencarian di background bisa masih menulis cache saat test selesai
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.result ={"status": "synced", "lines": [{"t": 1.0, "text": "a"}, {"t": 4.0, "text": "b"}],
                       "plain": "", "source": "lrclib", "lrclib_id": 5}
        patcher = mock.patch.object(lyrics, "search", side_effect=lambda *a: dict(self.result))
        self.search = patcher.start()
        self.addCleanup(patcher.stop)

    def provider(self):
        return lyrics.LyricsProvider(cache_dir=self.tmp.name)

    def play(self, p, key="k1"):
        p.track_changed(key, "Judul", "Artis", "Album", 200)
        self.assertTrue(wait_for(lambda: p.get()["status"] == "synced"))
        # file cache ditulis sesudah status berubah (di luar lock); tunggu sampai benar-benar ada
        self.assertTrue(wait_for(lambda: p.disk._path(p.get()["ckey"]).exists()))

    def test_fetch_and_line_at(self):
        p = self.provider()
        self.play(p)
        self.assertEqual(p.line_at(0.5), "")
        self.assertEqual(p.line_at(2.0), "a")
        self.assertEqual(p.line_at(2.0, offset=2.5), "b")

    def test_disk_cache_survives_restart(self):
        self.play(self.provider())
        self.search.side_effect = OSError("LRCLIB down")
        p = self.provider()
        p.track_changed("k1", "Judul", "Artis", "Album", 200)
        self.assertEqual(p.get()["status"], "synced")  # langsung dari disk, tanpa request
        self.assertEqual(self.search.call_count, 1)

    def test_same_song_from_other_source_shares_cache(self):
        p = self.provider()
        self.play(p, key="spotify:track:abc")
        p.track_changed("Judul|Artis|Album", "Judul", "Artis", "Album", 200)
        self.assertEqual(p.get()["status"], "synced")
        self.assertEqual(self.search.call_count, 1)

    def test_song_offset_persists(self):
        p = self.provider()
        self.play(p)
        p.set_offset(1.5)
        self.assertEqual(p.line_at(2.0), "a")
        self.assertEqual(p.line_at(2.6), "b")
        p2 = self.provider()
        p2.track_changed("k1", "Judul", "Artis", "Album", 200)
        self.assertEqual(p2.get()["offset"], 1.5)

    def test_slow_disk_write_does_not_overwrite_newer_offset(self):
        # tulisan pertama (dari thread pencarian) lambat; offset diatur selagi tulisan itu berjalan
        real_save = lyrics.LyricsCache.save
        calls = []

        def slow_save(cache, ckey, entry):
            calls.append(entry.get("offset"))
            if len(calls) == 1:
                time.sleep(0.3)
            real_save(cache, ckey, entry)

        with mock.patch.object(lyrics.LyricsCache, "save", slow_save):
            p = self.provider()
            self.play(p)
            p.set_offset(1.5)
            time.sleep(0.5)
        p2 = self.provider()
        p2.track_changed("k1", "Judul", "Artis", "Album", 200)
        self.assertEqual(p2.get()["offset"], 1.5)

    def test_offset_is_clamped(self):
        p = self.provider()
        self.play(p)
        self.assertEqual(p.set_offset(99)["offset"], 10.0)

    def test_use_lrc_and_reset(self):
        p = self.provider()
        self.play(p)
        rev = p.get()["rev"]
        cur = p.use_lrc(SYNCED)
        self.assertEqual(cur["source"], "file")
        self.assertEqual(len(cur["lines"]), 4)
        self.assertGreater(cur["rev"], rev)
        # pilihan manual tetap ada setelah restart
        p2 = self.provider()
        p2.track_changed("k1", "Judul", "Artis", "Album", 200)
        self.assertEqual(p2.get()["source"], "file")
        p2.reset()
        self.assertTrue(wait_for(lambda: p2.get()["source"] == "lrclib"))

    def test_use_lrc_rejects_plain_text(self):
        p = self.provider()
        self.play(p)
        with self.assertRaises(ValueError):
            p.use_lrc("tidak ada timestamp")

    def test_use_lrclib(self):
        p = self.provider()
        self.play(p)
        with mock.patch.object(lyrics, "_get", return_value={"id": 9, "syncedLyrics": "[00:02.00]x"}) as g:
            cur = p.use_lrclib("9")
        g.assert_called_once_with("get/9", {})
        self.assertEqual((cur["source"], cur["lrclib_id"]), ("manual", 9))

    def test_actions_need_a_song(self):
        p = self.provider()
        for call in (lambda: p.use_lrc(SYNCED), lambda: p.set_offset(1), p.reset):
            with self.assertRaises(ValueError):
                call()

    def test_none_result_expires(self):
        cache = lyrics.LyricsCache(self.tmp.name)
        cache.save("x", {"status": "none", "lines": [], "saved": time.time()})
        self.assertIsNotNone(cache.load("x"))
        with mock.patch.object(lyrics.time, "time", return_value=time.time() + lyrics.NONE_TTL + 10):
            self.assertIsNone(cache.load("x"))

    def test_none_in_memory_is_rechecked(self):
        # aplikasi tray bisa jalan berminggu-minggu: "tidak ketemu" di memori juga harus kedaluwarsa
        self.result = {"status": "none", "lines": [], "plain": "", "source": "lrclib"}
        p = self.provider()
        p.track_changed("k1", "Judul", "Artis", "Album", 200)
        self.assertTrue(wait_for(lambda: p.get()["status"] == "none"))
        p.track_changed("k2", "Lain", "Artis", "Album", 200)
        self.assertTrue(wait_for(lambda: p.get()["status"] == "none" and p.get()["key"] == "k2"))
        self.result = {"status": "synced", "lines": [{"t": 1.0, "text": "a"}], "plain": "", "source": "lrclib"}
        with mock.patch.object(lyrics.time, "time", return_value=time.time() + lyrics.NONE_TTL + 10):
            p.track_changed("k1", "Judul", "Artis", "Album", 200)
        self.assertTrue(wait_for(lambda: p.get()["status"] == "synced"))

    def test_manual_pick_survives_failing_retry(self):
        # LRCLIB down: pencarian otomatis gagal dan menunggu retry; user memakai file .lrc
        self.search.side_effect = OSError("503")
        with mock.patch.object(lyrics, "BACKGROUND_RETRY", (0.05, 0.05)):
            p = self.provider()
            p.track_changed("k1", "Judul", "Artis", "Album", 200)
            self.assertTrue(wait_for(lambda: p.get()["status"] == "error"))
            p.use_lrc(SYNCED)
            time.sleep(0.3)  # retry berikutnya selesai (dan gagal)
        self.assertEqual((p.get()["status"], p.get()["source"]), ("synced", "file"))

    def test_fix_for_previous_song_is_rejected(self):
        p = self.provider()
        self.play(p)
        ckey_a = p.get()["ckey"]
        p.track_changed("k2", "Lagu B", "Artis", "Album", 200)
        self.assertTrue(wait_for(lambda: p.get()["status"] == "synced"))  # tunggu thread pencarian selesai
        with self.assertRaises(ValueError):
            p.use_lrc(SYNCED, ckey=ckey_a)
        with self.assertRaises(ValueError):
            p.set_offset(1, ckey=ckey_a)
        self.assertNotEqual(p.get()["source"], "file")

    def test_reset_cancels_old_fetch(self):
        p = self.provider()
        self.play(p)
        p.use_lrc(SYNCED)
        p.reset(p.get()["ckey"])
        self.assertTrue(wait_for(lambda: p.get()["source"] == "lrclib"))
        time.sleep(0.1)
        self.assertEqual(self.search.call_count, 2)  # satu pencarian awal + satu setelah reset


if __name__ == "__main__":
    unittest.main()
