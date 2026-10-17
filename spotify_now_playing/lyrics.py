"""Lirik tersinkron dari LRCLIB (https://lrclib.net) — gratis, tanpa API key."""

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

API = "https://lrclib.net/api"
USER_AGENT = f"SpotifyNowPlaying/{__version__} (https://lrclib.net)"
LRC_LINE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
# "Song - 2011 Remaster", "Song (Remastered 2009)", "Song - Live", "Song (feat. X)"
NOISE = re.compile(r"\s*(?:-\s+.*(?:remaster|version|live|edit|mix|mono|stereo).*$"
                   r"|[\(\[][^\)\]]*(?:remaster|version|live|edit|mix|feat\.?|ft\.|with )[^\)\]]*[\)\]])",
                   re.IGNORECASE)


def clean_title(title):
    return NOISE.sub("", title).strip() or title


def parse_lrc(text):
    """'[01:02.34] baris' -> [(62.34, 'baris'), ...] urut waktu."""
    lines = []
    for raw in (text or "").splitlines():
        stamps = LRC_LINE.findall(raw)
        if not stamps:
            continue
        words = LRC_LINE.sub("", raw).strip()
        for m, s in stamps:
            lines.append((int(m) * 60 + float(s), words))
    lines.sort(key=lambda x: x[0])
    return lines


def _get(path, params):
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _pick(results, duration):
    """Pilih hasil pencarian: durasi paling dekat, utamakan yang tersinkron."""
    results = [r for r in results or [] if r.get("syncedLyrics") or r.get("plainLyrics")]
    if not results:
        return None
    def score(r):
        diff = abs((r.get("duration") or 0) - duration) if duration else 0
        return (diff > 5, not r.get("syncedLyrics"), diff)
    best = min(results, key=score)
    if duration and abs((best.get("duration") or 0) - duration) > 15:
        return None  # kemungkinan lagu lain
    return best


def search(title, artist, album, duration):
    clean = clean_title(title)
    first_artist = artist.split(",")[0].strip()
    hit = None
    if duration:
        try:
            hit = _get("get", {"track_name": clean, "artist_name": first_artist,
                               "album_name": album, "duration": round(duration)})
        except (urllib.error.HTTPError, OSError):
            hit = None  # /get kadang 503, lanjut ke pencarian
    if not hit or not (hit.get("syncedLyrics") or hit.get("plainLyrics")):
        hit = _pick(_get("search", {"track_name": clean, "artist_name": first_artist}), duration)
    if not hit:
        hit = _pick(_get("search", {"q": f"{first_artist} {clean}"}), duration)
    if not hit:
        return {"status": "none", "lines": [], "plain": ""}
    if hit.get("instrumental"):
        return {"status": "instrumental", "lines": [], "plain": ""}
    lines = parse_lrc(hit.get("syncedLyrics"))
    return {"status": "synced" if lines else "plain",
            "lines": [{"t": t, "text": w} for t, w in lines],
            "plain": hit.get("plainLyrics") or ""}


class LyricsProvider:
    """Ambil lirik di background saat lagu berganti, dengan cache."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self.current = {"key": "", "status": "idle", "lines": [], "plain": ""}

    def track_changed(self, key, title, artist, album, duration):
        with self.lock:
            if key == self.current["key"]:
                return
            if key in self.cache:
                self.current = {"key": key, **self.cache[key]}
                return
            self.current = {"key": key, "status": "loading", "lines": [], "plain": ""}
        threading.Thread(target=self._fetch, args=(key, title, artist, album, duration),
                         daemon=True).start()

    def clear(self):
        with self.lock:
            self.current = {"key": "", "status": "idle", "lines": [], "plain": ""}

    def _fetch(self, key, title, artist, album, duration):
        try:
            result = search(title, artist, album, duration)
            with self.lock:
                self.cache[key] = result
        except Exception as e:  # jaringan error: jangan cache, coba lagi di lagu berikutnya
            result = {"status": "error", "lines": [], "plain": "", "error": str(e)}
        with self.lock:
            if self.current["key"] == key:
                self.current = {"key": key, **result}

    def get(self):
        with self.lock:
            return dict(self.current)

    def line_at(self, position, offset=0.0):
        """Baris lirik yang sedang dinyanyikan pada posisi (detik)."""
        with self.lock:
            lines = self.current["lines"]
        text = ""
        for ln in lines:
            if ln["t"] > position + offset:
                break
            text = ln["text"]
        return text
