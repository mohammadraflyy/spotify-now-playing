"""Baca Spotify Desktop (atau player lain) di PC ini lewat Windows Media Controls (tanpa API)."""

import asyncio
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
        if session is None:
            return None

        playing = status[id(session)] == PlaybackStatus.PLAYING
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
            "device": f"{player_name(session.source_app_user_model_id)} (lokal)",
        }

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
