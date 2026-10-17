import tempfile
import unittest

from spotify_now_playing.history import MIN_PLAY, History

SONG = {"active": True, "playing": True, "title": "Judul", "artist": "Artis", "album": "A", "device": "Spotify"}


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.h = History(self.tmp.name)

    def play(self, song, start, seconds, step=0.5):
        t = start
        while t <= start + seconds:
            self.h.observe(song, now=t)
            t += step
        return t

    def all_entries(self):
        return [e for d in self.h.dates() for e in self.h.entries(d)]

    def test_logs_after_min_play(self):
        self.play(SONG, 1792246000, MIN_PLAY - 2)
        self.assertEqual(self.all_entries(), [])
        self.play(SONG, 1792246000 + MIN_PLAY - 1.5, 3)
        entries = self.all_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["time"], 1792246000)  # jam mulai lagu, bukan jam dicatat
        self.assertEqual(entries[0]["player"], "Spotify")

    def test_skipped_song_not_logged_and_no_duplicates(self):
        t = self.play(SONG, 1792246000, 5)
        t = self.play({**SONG, "title": "Lain"}, t, MIN_PLAY + 5)
        self.play({**SONG, "title": "Lain"}, t, 60)
        self.assertEqual([e["title"] for e in self.all_entries()], ["Lain"])

    def test_paused_time_does_not_count(self):
        self.play({**SONG, "playing": False}, 1792246000, 60)
        self.assertEqual(self.all_entries(), [])

    def test_text_and_clear(self):
        self.play(SONG, 1792246000, MIN_PLAY + 1)
        date = self.h.dates()[0]
        self.assertRegex(self.h.text(date), r"^\d\d:\d\d  Artis - Judul\n$")
        self.h.clear(date)
        self.assertEqual(self.h.dates(), [])

    def test_rejects_bad_dates(self):
        self.assertEqual(self.h.entries("../config"), [])
        self.h.clear("../config")  # tidak boleh error / menghapus apa pun


if __name__ == "__main__":
    unittest.main()
