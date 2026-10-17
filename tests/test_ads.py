import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spotify_now_playing import app as app_mod, audio, local_media, spotify_api


class FakeConfig(dict):
    def update(self, **values):
        for k, v in values.items():
            if v is None:
                self.pop(k, None)
            else:
                self[k] = v


class FakeBackend:
    def __init__(self, volume=0.8, sessions=1):
        self.volume, self.muted, self.sessions, self.calls = volume, False, sessions, []

    def set_mute(self, on):
        self.calls.append(("mute", on))
        if self.sessions:
            self.muted = on
        return self.sessions

    def get_volume(self):
        return self.volume if self.sessions else None

    def set_volume(self, level):
        self.calls.append(("volume", level))
        if self.sessions:
            self.volume = level
        return self.sessions


class AdAudioTest(unittest.TestCase):
    def make(self, cfg=None, **kw):
        self.cfg = cfg if cfg is not None else FakeConfig()
        self.backend = FakeBackend(**kw)
        return audio.AdAudio(self.cfg, self.backend)

    def test_mute_during_ad_and_restore(self):
        a = self.make()
        a.update(True, True, now=0)
        self.assertTrue(self.backend.muted)
        self.assertEqual(self.cfg["ad_restore"], {"mute": True})  # tersimpan kalau aplikasi tertutup
        a.update(True, True, now=1)
        self.assertEqual(self.backend.calls, [("mute", True)])  # tidak diulang setiap tick
        a.update(False, True, now=30)
        self.assertFalse(self.backend.muted)
        self.assertNotIn("ad_restore", self.cfg)

    def test_falls_back_to_quiet_when_spotify_pauses_muted_ad(self):
        a = self.make()
        a.update(True, True, now=0)
        a.update(True, False, now=1.5)  # Spotify menjeda iklan setelah dibisukan
        self.assertFalse(self.backend.muted)
        self.assertEqual(self.backend.volume, 0.1)
        self.assertTrue(self.cfg["ads"]["mute_pauses"])
        a.update(False, True, now=30)
        self.assertEqual(self.backend.volume, 0.8)  # volume asli kembali
        self.assertEqual(a.mode(), "quiet")  # iklan berikutnya langsung dikecilkan

    def test_manual_pause_later_is_not_a_fallback(self):
        a = self.make()
        a.update(True, True, now=0)
        a.update(True, False, now=20)
        self.assertTrue(self.backend.muted)
        self.assertNotIn("ads", self.cfg)

    def test_quiet_mode_respects_lower_user_volume(self):
        a = self.make(FakeConfig(ads={"mode": "quiet", "volume": 20}), volume=0.05)
        a.update(True, True, now=0)
        self.assertEqual(self.backend.calls, [])  # sudah lebih pelan dari 20%
        a = self.make(FakeConfig(ads={"mode": "quiet", "volume": 20}), volume=0.9)
        a.update(True, True, now=0)
        self.assertEqual(self.backend.volume, 0.2)

    def test_off_mode(self):
        a = self.make(FakeConfig(ads={"mode": "off"}))
        a.update(True, True, now=0)
        a.update(False, True, now=1)
        self.assertEqual(self.backend.calls, [])

    def test_retries_until_spotify_has_a_session(self):
        a = self.make(sessions=0)
        a.update(True, True, now=0)
        self.assertIsNone(a.applied)
        self.backend.sessions = 1
        a.update(True, True, now=0.5)
        self.assertTrue(self.backend.muted)

    def test_restore_left_over_from_crash(self):
        cfg = FakeConfig(ad_restore={"volume": 0.7})
        a = self.make(cfg, volume=0.1)
        self.assertEqual(self.backend.volume, 0.7)
        self.assertNotIn("ad_restore", cfg)

    def test_restore_waits_while_spotify_is_closed(self):
        a = self.make(sessions=1)
        a.update(True, True, now=0)
        self.backend.sessions = 0           # Spotify ditutup di tengah iklan
        a.update(False, False, now=10)
        self.assertIn("ad_restore", self.cfg)
        self.backend.sessions = 1
        a.update(False, True, now=12)       # belum waktunya mencoba lagi
        self.assertIn("ad_restore", self.cfg)
        a.update(False, True, now=16)
        self.assertNotIn("ad_restore", self.cfg)
        self.assertFalse(self.backend.muted)


class DetectTest(unittest.TestCase):
    def test_local_heuristic(self):
        self.assertTrue(local_media.looks_like_ad("Advertisement", "", ""))
        self.assertTrue(local_media.looks_like_ad("Coba Produk X", "", ""))
        self.assertTrue(local_media.looks_like_ad("Spotify", "Spotify", ""))
        self.assertFalse(local_media.looks_like_ad("Pamit", "Tulus", "Gajah"))

    def test_web_api(self):
        acc = spotify_api.SpotifyAccount.__new__(spotify_api.SpotifyAccount)
        data = {"currently_playing_type": "ad", "is_playing": True, "item": None, "device": {"name": "PC"}}
        with mock.patch.object(acc, "get", return_value=(200, data)):
            info = acc.now_playing()
        self.assertTrue(info["ad"])
        self.assertEqual(info["device"], "PC")


class AppTest(unittest.TestCase):
    def test_ad_state_files_and_history(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        with mock.patch.object(app_mod, "DATA_DIR", root), mock.patch.object(app_mod, "OUTPUT_DIR", root),              mock.patch.object(app_mod.audio, "AVAILABLE", False), mock.patch.object(local_media, "AVAILABLE", False):
            a = app_mod.NowPlayingApp(FakeConfig(lang="id"))
            a.lyrics = mock.Mock()
            a._apply(local_media.ad_info(True, "Spotify"))
            s = a.snapshot()
            self.assertEqual((s["active"], s["ad"], s["title"], s["duration"]), (True, True, "Jeda sebentar", 0.0))
            a._write_files(s)
            self.assertEqual((root / "nowplaying.txt").read_text(encoding="utf-8"), "Jeda sebentar   ")
            self.assertEqual((root / "title.txt").read_text(encoding="utf-8"), "")
            a.lyrics.track_changed.assert_not_called()
            a.cfg["ads"] = {"text": "Iklan dulu ya"}
            a._apply(local_media.ad_info(True, "Spotify"))
            self.assertEqual(a.snapshot()["title"], "Iklan dulu ya")


if __name__ == "__main__":
    unittest.main()
