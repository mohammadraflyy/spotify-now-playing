"""Baca Spotify Desktop di PC ini lewat Windows Media Controls (tanpa API)."""

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


class LocalSpotify:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._manager = None

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def now_playing(self):
        return self._run(self._now_playing())

    async def _now_playing(self):
        if self._manager is None:
            self._manager = await SessionManager.request_async()
        session = next((s for s in self._manager.get_sessions()
                        if "spotify" in (s.source_app_user_model_id or "").lower()), None)
        if session is None:
            return None
        props = await session.try_get_media_properties_async()
        if not props.title:
            return None

        playing = session.get_playback_info().playback_status == PlaybackStatus.PLAYING
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
            "device": "Spotify Desktop (lokal)",
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
