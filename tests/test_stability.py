import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from spotify_now_playing import diagnostics, local_media, updates
from spotify_now_playing.config import Config


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"

    def test_saves_and_keeps_backup_of_previous_version(self):
        c = Config(self.path)
        self.assertTrue(c.first_run)
        c.update(source="local")
        c.update(source="account")
        self.assertEqual(json.loads(self.path.read_text())["source"], "account")
        self.assertEqual(json.loads(Path(str(self.path) + ".bak").read_text())["source"], "local")
        self.assertIsNone(Config(self.path).recovered)

    def test_damaged_file_is_restored_from_backup(self):
        c = Config(self.path)
        c.update(overlay={"layout": "vinyl"})
        c.update(overlay={"layout": "row"})
        self.path.write_text("{ rusak", encoding="utf-8")  # mis. PC mati saat menyimpan
        c2 = Config(self.path)
        self.assertEqual(c2.recovered, "backup")
        self.assertEqual(c2.get("overlay"), {"layout": "vinyl"})
        self.assertFalse(c2.first_run)
        broken = list(Path(self.tmp.name).glob("config.broken-*.json"))
        self.assertEqual(len(broken), 1)  # file rusak disimpan, tidak ditimpa diam-diam

    def test_damaged_file_without_backup(self):
        self.path.write_text("[1, 2]", encoding="utf-8")  # JSON valid tapi bukan object
        c = Config(self.path)
        self.assertEqual(c.recovered, "defaults")
        self.assertEqual(c.get("source"), "auto")


class WatchdogTest(unittest.TestCase):
    def test_hung_call_is_abandoned_and_replaced(self):
        made = []
        release = threading.Event()
        self.addCleanup(release.set)
        w = local_media.Watchdog(lambda: made.append(1) or len(made), timeout=0.2)
        self.assertEqual(w.call(lambda obj: obj), 1)
        with self.assertRaises(TimeoutError):
            w.call(lambda obj: release.wait(5))
        self.assertEqual(w.call(lambda obj: obj), 2)  # objek baru di thread baru
        self.assertEqual(w.restarts, 1)

    def test_errors_are_passed_on(self):
        def boom(obj):
            raise ValueError("x")
        w = local_media.Watchdog(lambda: None)
        with self.assertRaises(ValueError):
            w.call(boom)


class DiagnosticsTest(unittest.TestCase):
    def test_secrets_are_removed(self):
        data = diagnostics.scrub({"enabled": True, "key_hint": "abcd", "secret_hint": "x",
                                  "youtube": {"has_secret": True, "state": "connected", "access_token": "t"}})
        self.assertEqual(data, {"enabled": True, "youtube": {"state": "connected"}})
        text = diagnostics.scrub_text("GET ?uniqueId=tulus&apiKey=abc123 Authorization: Bearer ya29.xyz "
                                      "refresh_token=1//0gAbCdEf token " + "a" * 40)
        for leaked in ("abc123", "ya29.xyz", "1//0gAbCdEf", "a" * 40):
            self.assertNotIn(leaked, text)
        self.assertIn("uniqueId=tulus", text)


RELEASE = {
    "tag_name": "v9.0.0", "html_url": "https://github.com/x/releases/tag/v9.0.0",
    "body": "Catatan\n\nSHA-256: `" + "ab" * 32 + "`\n",
    "assets": [{"name": "SpotifyNowPlaying-Setup-9.0.0.exe", "size": 10,
                "browser_download_url": updates.ASSET_PREFIX + "v9.0.0/SpotifyNowPlaying-Setup-9.0.0.exe"}],
}


class UpdateInstallTest(unittest.TestCase):
    def test_parse_release(self):
        info = updates.parse_release(RELEASE)
        self.assertEqual((info["version"], info["sha256"], info["size"]), ("9.0.0", "ab" * 32, 10))
        other = dict(RELEASE, assets=[dict(RELEASE["assets"][0], browser_download_url="https://evil.example/x.exe")])
        self.assertNotIn("asset_url", updates.parse_release(other))  # hanya dari rilis repo ini
        self.assertNotIn("asset_url", updates.parse_release(dict(RELEASE, body="tanpa checksum")))

    def make(self, digest):
        u = updates.UpdateChecker({})
        u.available = updates.parse_release(RELEASE)
        u.download = lambda url, path, size, progress: progress(10, 10) or digest
        u.ran, u.order = [], []
        u.before_install = lambda: u.order.append("restore")
        u.run_installer = lambda path: (u.order.append("run"), u.ran.append(path))
        return u

    def wait(self, u):
        deadline = time.time() + 2
        while u.install_status["state"] in ("downloading", "verifying") and time.time() < deadline:
            time.sleep(0.02)

    def test_install_runs_verified_installer(self):
        u = self.make("ab" * 32)
        with mock.patch.object(updates, "can_install", return_value=True):
            self.assertIsNone(u.install())
        self.wait(u)
        self.assertEqual(u.install_status["state"], "starting")
        self.assertTrue(u.ran[0].endswith("SpotifyNowPlaying-Setup-9.0.0.exe"))
        self.assertEqual(u.order, ["restore", "run"])  # suara Spotify dipulihkan sebelum aplikasi ditutup

    def test_checksum_mismatch_is_refused(self):
        u = self.make("cd" * 32)
        with mock.patch.object(updates, "can_install", return_value=True):
            u.install()
        self.wait(u)
        self.assertEqual(u.install_status["state"], "error")
        self.assertIn("Checksum", u.install_status["error"])
        self.assertEqual(u.ran, [])

    def test_not_from_source(self):
        u = self.make("ab" * 32)
        with mock.patch.object(updates, "can_install", return_value=False):
            self.assertIn("di-install", u.install())


if __name__ == "__main__":
    unittest.main()
