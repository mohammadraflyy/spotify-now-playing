"""Lirik tersinkron dari LRCLIB (https://lrclib.net) — gratis, tanpa API key."""

import json
import re
import threading
import time
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


RETRY_DELAYS = (0.7, 2.0)            # retry singkat per request (LRCLIB kadang 503)
BACKGROUND_RETRY = (5, 15, 30, 60)    # retry di background kalau semua cara gagal


def _get(path, params):
    """GET ke LRCLIB. 404 -> None. 5xx/timeout dicoba ulang beberapa kali."""
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code < 500 or attempt == len(RETRY_DELAYS):
                raise
        except (urllib.error.URLError, TimeoutError, ValueError):
            if attempt == len(RETRY_DELAYS):
                raise
        time.sleep(RETRY_DELAYS[attempt])


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
    """Coba beberapa cara berurutan. Raise hanya kalau SEMUA cara error (bukan sekadar tidak ketemu)."""
    clean = clean_title(title)
    first_artist = artist.split(",")[0].strip()
    attempts = [
        lambda: _get("get", {"track_name": clean, "artist_name": first_artist,
                             "album_name": album, "duration": round(duration)}) if duration else None,
        lambda: _pick(_get("search", {"track_name": clean, "artist_name": first_artist}), duration),
        lambda: _pick(_get("search", {"q": f"{first_artist} {clean}"}), duration),
    ]
    hit, errors = None, []
    for attempt in attempts:
        try:
            hit = attempt()
        except Exception as e:
            errors.append(e)
            continue
        if hit and (hit.get("syncedLyrics") or hit.get("plainLyrics") or hit.get("instrumental")):
            break
        hit = None
    if not hit:
        if len(errors) == len(attempts):
            raise errors[-1]
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
        for retry, delay in enumerate((0, *BACKGROUND_RETRY)):
            if delay:
                time.sleep(delay)
                with self.lock:
                    if self.current["key"] != key:
                        return  # lagu sudah berganti
            try:
                result = search(title, artist, album, duration)
                with self.lock:
                    self.cache[key] = result
                    if self.current["key"] == key:
                        self.current = {"key": key, **result}
                return
            except Exception as e:  # jangan di-cache; coba lagi sebentar lagi
                last = retry == len(BACKGROUND_RETRY)
                msg = str(e) + ("" if last else f" — mencoba lagi dalam {BACKGROUND_RETRY[retry]} detik")
                with self.lock:
                    if self.current["key"] == key:
                        self.current = {"key": key, "status": "error", "lines": [], "plain": "",
                                        "error": msg}

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
