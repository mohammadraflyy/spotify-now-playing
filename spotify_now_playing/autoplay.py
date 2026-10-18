"""Putar otomatis request penonton lewat antrian Spotify, dan info "lagu selanjutnya".

Butuh login Akun Spotify Premium dengan izin mengontrol pemutaran. Request tidak dikirim ke Spotify
sekaligus: request teratas baru dimasukkan ke antrian Spotify menjelang lagu yang sedang diputar
selesai. Dengan begitu urutan dan hapus di halaman pengaturan tetap berlaku (antrian Spotify tidak
bisa diubah urutannya dari luar), dan setelah request habis Spotify lanjut ke playlist sendiri.
"""

import logging
import threading
import time

from . import spotify_api

log = logging.getLogger("snp")

LEAD = 15         # detik sebelum lagu selesai: request berikutnya masuk antrian Spotify
QUEUE_POLL = 15   # detik antar pembacaan antrian Spotify untuk "lagu selanjutnya"
RETRY_SEARCH = 30  # detik sebelum mencari ulang request yang pencariannya gagal


class AutoPlayer:
    def __init__(self, app, search=spotify_api.search_track, add=spotify_api.add_to_queue,
                 peek=spotify_api.queue_next):
        self.app = app
        self.search, self.add, self.peek = search, add, peek
        self.next = None          # {"title", "artist", "source": "request"|"spotify", "user", "platform"}
        self.error = ""
        self.pushed_for = None    # lagu yang sedang diputar saat request terakhir dikirim
        self._spotify_next = None
        self._peek_key, self._peek_at = None, 0.0
        self._started = False
        self._tried = {}          # id request -> waktu pencarian terakhir yang gagal

    def enabled(self):
        return bool(self.app.chat.settings().get("request_autoplay")) and self.app.account.can_control

    def start(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                self.step(time.time())
            except Exception:  # noqa: BLE001  (thread ini tidak boleh mati)
                log.exception("autoplay gagal")
            time.sleep(1)

    def step(self, now):
        snap = self.app.snapshot()
        items = self.app.chat.requests.list()
        auto = self.enabled()
        if auto and self._resolve(items, now):
            items = self.app.chat.requests.list()
        playing_song = snap.get("active") and not snap.get("ad")
        self.next = self._next(auto, items, snap, now) if playing_song else None
        if not auto or not playing_song or not snap.get("playing") or not snap.get("duration"):
            return
        if snap["duration"] - snap["position"] > LEAD:
            return
        key = f"{snap['title']}|{snap['artist']}"
        item = next((i for i in items if not i.get("queued") and not i.get("not_found")), None)
        if self.pushed_for == key or not item:
            return
        self.pushed_for = key  # sekali per lagu, berhasil atau tidak
        self._push(item)

    def _resolve(self, items, now):
        """Cari lagu untuk request teratas yang belum punya (mis. masuk saat Spotify sedang error),
        supaya "lagu selanjutnya" langsung benar. True kalau antrian berubah."""
        item = next((i for i in items if not i.get("track") and not i.get("not_found")), None)
        if not item or now - self._tried.get(item["id"], -RETRY_SEARCH) < RETRY_SEARCH:
            return False
        try:
            track = self.search(self.app.account, item["text"])
        except Exception as e:  # noqa: BLE001  (dicoba lagi nanti)
            self._tried[item["id"]] = now
            log.warning("pencarian Spotify gagal untuk %r: %s", item["text"], e)
            return False
        self.app.chat.requests.update(item["id"], **({"track": track} if track else {"not_found": True}))
        return True

    def _next(self, auto, items, snap, now):
        if auto:
            item = next((i for i in items if i.get("track")), None)
            if item:
                t = item["track"]
                return {"title": t["title"], "artist": t["artist"], "source": "request",
                        "user": item["user"], "platform": item["platform"]}
        if not self.app.account.logged_in:
            return None
        key = f"{snap['title']}|{snap['artist']}"
        if key != self._peek_key or now >= self._peek_at:
            self._peek_key, self._peek_at = key, now + QUEUE_POLL
            try:
                self._spotify_next = self.peek(self.app.account)
            except Exception as e:  # noqa: BLE001  (info tambahan saja)
                log.debug("antrian Spotify tidak terbaca: %s", e)
                self._spotify_next = None
        t = self._spotify_next
        return {"title": t["title"], "artist": t["artist"], "source": "spotify"} if t else None

    def _push(self, item):
        queue = self.app.chat.requests
        track = item.get("track")
        try:
            if not track:  # request masuk sebelum login (atau pencarian sempat gagal): cari sekarang
                try:
                    track = self.search(self.app.account, item["text"])
                except Exception as e:  # noqa: BLE001
                    raise RuntimeError(f"Gagal mencari lagu di Spotify: {e}") from None
                if not track:
                    queue.update(item["id"], not_found=True)
                    return
                queue.update(item["id"], track=track)
            self.add(self.app.account, track["uri"])
            queue.mark_queued(item["id"])
            self.error = ""
            log.info("request masuk antrian Spotify: %s - %s (oleh %s)", track["artist"], track["title"], item["user"])
        except Exception as e:  # noqa: BLE001  (ditampilkan di halaman pengaturan)
            self.error = str(e)
            log.warning("gagal memasukkan request ke antrian Spotify: %s", e)

    def find(self, text):
        """Cari lagu untuk request baru. None = tidak ketemu; error API diteruskan."""
        return self.search(self.app.account, text)

    def status(self):
        acc = self.app.account
        return {"enabled": bool(self.app.chat.settings().get("request_autoplay")), "logged_in": acc.logged_in,
                "can_control": acc.can_control, "active": self.enabled(), "error": self.error}
