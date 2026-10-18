"""Baca Spotify Desktop (atau player lain) di PC ini lewat Windows Media Controls (tanpa API)."""

import asyncio
import queue
import threading
from datetime import datetime, timezone

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    from winrt.windows.storage.streams import Buffer, InputStreamOptions
    import winrt.windows.foundation.collections  # noqa: F401  (dibutuhkan get_sessions)
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


# potongan AppUserModelID -> nama yang ditampilkan
PLAYER_NAMES = (
    ("spotify", "Spotify"), ("applemusic", "Apple Music"), ("tidal", "TIDAL"),
    ("deezer", "Deezer"), ("youtube", "YouTube Music"), ("msedge", "Microsoft Edge"),
    ("chrome", "Google Chrome"), ("firefox", "Firefox"), ("opera", "Opera"), ("brave", "Brave"),
    ("zunemusic", "Media Player"), ("foobar", "foobar2000"), ("musicbee", "MusicBee"),
    ("aimp", "AIMP"), ("vlc", "VLC"),
)


def player_name(app_id):
    low = (app_id or "").lower()
    for part, name in PLAYER_NAMES:
        if part in low:
            return name
    stem = (app_id or "").split("!")[0].split("_")[0].removesuffix(".exe")
    return stem.split(".")[-1] or "Player"


def is_spotify(session):
    return "spotify" in (session.source_app_user_model_id or "").lower()


AD_NAMES = {"advertisement", "spotify", "iklan"}


def looks_like_ad(title, artist, album):
    """Spotify Desktop tidak memberi tanda iklan: iklan muncul tanpa artis, atau berjudul "Advertisement"."""
    title, artist = (title or "").strip().lower(), (artist or "").strip().lower()
    return not artist or title in AD_NAMES or (artist in AD_NAMES and not album)


def ad_info(playing, device):
    return {"id": "ad", "ad": True, "title": "", "artist": "", "album": "", "cover": lambda: b"",
            "duration": 0.0, "position": 0.0, "playing": playing, "device": device}


class Watchdog:
    """Jalankan panggilan ke objek yang bisa macet (Windows Media Controls saat player hang) di
    thread sendiri, dengan batas waktu. Kalau macet, thread itu ditinggalkan dan objek baru dibuat
    di thread baru, supaya overlay tidak ikut membeku sampai aplikasi di-restart."""

    def __init__(self, factory, timeout=5.0):
        self.factory, self.timeout = factory, timeout
        self.restarts = 0
        self._start()

    def _start(self):
        self.jobs = queue.Queue()
        threading.Thread(target=self._worker, args=(self.jobs,), daemon=True).start()

    def _worker(self, jobs):
        obj = None
        while True:
            fn, box, done = jobs.get()
            if fn is None:
                return  # sudah diganti thread baru selagi macet
            try:
                if obj is None:
                    obj = self.factory()  # dibuat di thread ini, dipakai hanya di thread ini
                box["value"] = fn(obj)
            except BaseException as e:  # noqa: BLE001  (diteruskan ke pemanggil)
                box["error"] = e
            done.set()

    def call(self, fn):
        box, done = {}, threading.Event()
        self.jobs.put((fn, box, done))
        if not done.wait(self.timeout):
            self.jobs.put((None, None, None))
            self.restarts += 1
            self._start()
            raise TimeoutError("player tidak merespons, menyambung ulang")
        if "error" in box:
            raise box["error"]
        return box["value"]


class LocalSpotify:
    def __init__(self, all_players=lambda: False):
        self._loop = asyncio.new_event_loop()
        self._manager = None
        self._all_players = all_players  # callable: True = baca semua player, bukan cuma Spotify

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def now_playing(self):
        return self._run(self._now_playing())

    async def _now_playing(self):
        if self._manager is None:
            self._manager = await SessionManager.request_async()
        sessions = list(self._manager.get_sessions())
        if not self._all_players():
            sessions = [s for s in sessions if is_spotify(s)]
        # utamakan yang sedang memutar, lalu Spotify, lalu urutan dari Windows
        status = {id(s): s.get_playback_info().playback_status for s in sessions}
        sessions.sort(key=lambda s: (status[id(s)] != PlaybackStatus.PLAYING, not is_spotify(s)))
        session = props = None
        for s in sessions:
            p = await s.try_get_media_properties_async()
            if p.title:
                session, props = s, p
                break
            if is_spotify(s) and status[id(s)] == PlaybackStatus.PLAYING:
                info = ad_info(True, "Spotify")  # Spotify berbunyi tanpa judul: iklan
                info["raw"] = _raw(s, p, status[id(s)])
                return info
        if session is None:
            return None

        playing = status[id(session)] == PlaybackStatus.PLAYING
        raw = _raw(session, props, status[id(session)])
        if is_spotify(session) and looks_like_ad(props.title, props.artist, props.album_title):
            info = ad_info(playing, "Spotify")
            info["raw"] = raw
            return info
        tl = session.get_timeline_properties()
        duration = (tl.end_time - tl.start_time).total_seconds()
        position = tl.position.total_seconds()
        if playing and tl.last_updated_time:  # Spotify jarang update posisi -> interpolasi
            last = tl.last_updated_time
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            if 0 < elapsed < 3600:
                position += elapsed
        if duration > 0:
            position = min(position, duration)

        thumb = props.thumbnail
        return {
            "id": f"{props.title}|{props.artist}|{props.album_title}",
            "title": props.title,
            "artist": props.artist or "",
            "album": props.album_title or "",
            "cover": lambda: self._run(self._read_thumb(thumb)),
            "duration": duration,
            "position": position,
            "playing": playing,
            "device": player_name(session.source_app_user_model_id),
            "raw": raw,
        }

    def close(self):
        self._loop.close()

    @staticmethod
    async def _read_thumb(thumb):
        if thumb is None:
            return b""
        stream = await thumb.open_read_async()
        if not stream.size:
            return b""
        buf = Buffer(stream.size)
        await stream.read_async(buf, stream.size, InputStreamOptions.READ_AHEAD)
        return bytes(memoryview(buf))


def _raw(session, props, status):
    """Data mentah dari Windows untuk info diagnosa (mis. memastikan bentuk iklan Spotify)."""
    try:
        kind = getattr(props.playback_type, "name", "") if props.playback_type is not None else ""
    except Exception:  # noqa: BLE001  (tidak semua player mengisinya)
        kind = ""
    return {"app": session.source_app_user_model_id or "", "status": getattr(status, "name", str(status)), "title": props.title or "",
            "artist": props.artist or "", "album": props.album_title or "", "type": kind}
