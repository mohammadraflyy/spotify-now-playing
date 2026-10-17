"""Lirik tersinkron dari LRCLIB (https://lrclib.net) — gratis, tanpa API key."""

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

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
NONE_TTL = 3 * 24 * 3600              # "lirik tidak ketemu" dicek ulang setelah 3 hari
CACHE_MAX_FILES = 3000


def _get(path, params):
    """GET ke LRCLIB. 404 -> None. 5xx/timeout dicoba ulang beberapa kali."""
    url = f"{API}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
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


def _result(hit, source="lrclib"):
    """Hasil LRCLIB -> format yang dipakai overlay."""
    if hit.get("instrumental"):
        return {"status": "instrumental", "lines": [], "plain": "", "source": source,
                "lrclib_id": hit.get("id")}
    lines = parse_lrc(hit.get("syncedLyrics"))
    return {"status": "synced" if lines else "plain",
            "lines": [{"t": t, "text": w} for t, w in lines],
            "plain": hit.get("plainLyrics") or "", "source": source, "lrclib_id": hit.get("id")}


def search(title, artist, album, duration):
    """Coba beberapa cara berurutan. Raise hanya kalau SEMUA cara error (bukan sekadar tidak ketemu)."""
    clean = clean_title(title)
    first_artist = artist.split(",")[0].strip()
    attempts = [
        lambda: _get("get", {"track_name": clean, "artist_name": first_artist,
                             "album_name": album, "duration": round(duration)}) if duration else None,
        lambda: _pick(_get("search", {"track_name": clean, "artist_name": first_artist}), duration),
        lambda: _pick(_get("search", {"q": f"{first_artist} {clean}".strip()}), duration),
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
        return {"status": "none", "lines": [], "plain": "", "source": "lrclib"}
    return _result(hit)


def candidates(title, artist):
    """Daftar hasil pencarian LRCLIB untuk dipilih manual di halaman pengaturan."""
    params = {"track_name": title, "artist_name": artist} if artist else {"q": title}
    results = _get("search", params) or []
    if artist and not results:
        results = _get("search", {"q": f"{artist} {title}"}) or []
    return [{"id": r.get("id"), "title": r.get("trackName") or "", "artist": r.get("artistName") or "",
             "album": r.get("albumName") or "", "duration": r.get("duration") or 0,
             "synced": bool(r.get("syncedLyrics")), "instrumental": bool(r.get("instrumental"))}
            for r in results[:30] if r.get("id")]


def cache_key(title, artist, album):
    """Kunci cache yang sama untuk mode lokal dan mode akun."""
    raw = "|".join((x or "").strip().lower() for x in (title, artist, album))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


class LyricsCache:
    """Lirik tersimpan di disk (satu file JSON per lagu), jadi tetap ada walaupun LRCLIB sedang down."""

    def __init__(self, folder):
        self.folder = Path(folder) if folder else None
        self._pruned = False

    def _path(self, ckey):
        return self.folder / f"{ckey}.json"

    def load(self, ckey):
        if not self.folder:
            return None
        try:
            entry = json.loads(self._path(ckey).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        # "tidak ketemu" dicek ulang berkala, siapa tahu liriknya sudah ditambahkan ke LRCLIB
        if entry.get("status") == "none" and time.time() - entry.get("saved", 0) > NONE_TTL:
            return None
        return entry

    def save(self, ckey, entry):
        if not self.folder:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self._path(ckey).with_suffix(".tmp")
            tmp.write_text(json.dumps({**entry, "saved": time.time()}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path(ckey))
            if not self._pruned:
                self._pruned = True
                self._prune()
        except OSError:
            pass

    def delete(self, ckey):
        if self.folder:
            try:
                self._path(ckey).unlink()
            except OSError:
                pass

    def _prune(self):
        files = sorted(self.folder.glob("*.json"), key=lambda f: f.stat().st_mtime)
        for f in files[:max(0, len(files) - CACHE_MAX_FILES)]:
            try:
                f.unlink()
            except OSError:
                pass


EMPTY = {"key": "", "ckey": "", "status": "idle", "lines": [], "plain": "", "offset": 0.0,
         "source": "", "track": {}}


def _public(entry):
    return {k: entry[k] for k in ("status", "lines", "plain", "offset", "source", "lrclib_id") if k in entry}


class LyricsProvider:
    """Ambil lirik di background saat lagu berganti, dengan cache di memori dan disk."""

    def __init__(self, cache_dir=None):
        self.lock = threading.Lock()
        self.memory = {}
        self.disk = LyricsCache(cache_dir)
        self.rev = 0
        self.current = {**EMPTY, "rev": 0}

    def _set(self, **values):
        """Ganti lirik yang sedang aktif (panggil sambil memegang self.lock)."""
        self.rev += 1
        self.current = {**EMPTY, **values, "rev": self.rev}

    def track_changed(self, key, title, artist, album, duration):
        ckey = cache_key(title, artist, album)
        track = {"title": title, "artist": artist, "album": album, "duration": duration}
        with self.lock:
            if key == self.current["key"]:
                return
            entry = self.memory.get(ckey) or self.disk.load(ckey)
            if entry:
                self.memory[ckey] = entry
                self._set(key=key, ckey=ckey, track=track, **_public(entry))
                return
            self._set(key=key, ckey=ckey, track=track, status="loading")
        threading.Thread(target=self._fetch, args=(key, ckey, title, artist, album, duration),
                         daemon=True).start()

    def clear(self):
        with self.lock:
            self._set()

    def _store(self, ckey, entry):
        self.memory[ckey] = entry
        self.disk.save(ckey, entry)

    def _fetch(self, key, ckey, title, artist, album, duration):
        for retry, delay in enumerate((0, *BACKGROUND_RETRY)):
            if delay:
                time.sleep(delay)
                with self.lock:
                    if self.current["key"] != key:
                        return  # lagu sudah berganti
            try:
                result = search(title, artist, album, duration)
                with self.lock:
                    if self.memory.get(ckey, {}).get("source") in ("manual", "file"):
                        return  # sudah dipilih manual selama pencarian berjalan
                    self._store(ckey, result)
                    if self.current["key"] == key:
                        self._set(key=key, ckey=ckey, track=self.current["track"], **_public(result))
                return
            except Exception as e:  # jangan di-cache; coba lagi sebentar lagi
                last = retry == len(BACKGROUND_RETRY)
                msg = str(e) + ("" if last else f" — mencoba lagi dalam {BACKGROUND_RETRY[retry]} detik")
                with self.lock:
                    if self.current["key"] == key:
                        self._set(key=key, ckey=ckey, track=self.current["track"],
                                  status="error", error=msg)

    # ---------------------------------------------------- perbaikan manual --

    def _replace(self, result):
        """Simpan lirik pilihan user untuk lagu yang sedang diputar."""
        with self.lock:
            cur = self.current
            if not cur["ckey"]:
                raise ValueError("Belum ada lagu yang diputar")
            entry = {**result, "offset": cur.get("offset", 0.0)}
            self._store(cur["ckey"], entry)
            self._set(key=cur["key"], ckey=cur["ckey"], track=cur["track"], **_public(entry))
            return dict(self.current)

    def use_lrclib(self, lrclib_id):
        hit = _get(f"get/{int(lrclib_id)}", {})
        if not hit:
            raise ValueError("Lirik tidak ditemukan di LRCLIB")
        return self._replace(_result(hit, source="manual"))

    def use_lrc(self, text):
        lines = parse_lrc(text)
        if not lines:
            raise ValueError("File .lrc tidak berisi baris bertimestamp seperti [01:23.45]")
        return self._replace({"status": "synced", "lines": [{"t": t, "text": w} for t, w in lines],
                              "plain": "", "source": "file"})

    def set_offset(self, offset):
        offset = max(-10.0, min(10.0, float(offset)))
        with self.lock:
            cur = self.current
            entry = self.memory.get(cur["ckey"]) if cur["ckey"] else None
            if entry is None:
                raise ValueError("Tunggu sampai lirik lagu ini selesai dimuat")
            entry = {**entry, "offset": offset}
            self._store(cur["ckey"], entry)
            self._set(key=cur["key"], ckey=cur["ckey"], track=cur["track"], **_public(entry))
            return dict(self.current)

    def reset(self):
        """Hapus pilihan manual dan offset lagu ini, lalu cari ulang otomatis."""
        with self.lock:
            cur = self.current
            if not cur["ckey"]:
                raise ValueError("Belum ada lagu yang diputar")
            self.memory.pop(cur["ckey"], None)
            self.disk.delete(cur["ckey"])
            key, track = cur["key"], cur["track"]
            self.current = {**cur, "key": ""}  # supaya track_changed mencari ulang
        self.track_changed(key, track["title"], track["artist"], track["album"], track["duration"])
        return self.get()

    # ---------------------------------------------------------------- baca --

    def get(self):
        with self.lock:
            return dict(self.current)

    def line_at(self, position, offset=0.0):
        """Baris lirik yang sedang dinyanyikan pada posisi (detik)."""
        with self.lock:
            lines = self.current["lines"]
            offset += self.current.get("offset") or 0.0
        text = ""
        for ln in lines:
            if ln["t"] > position + offset:
                break
            text = ln["text"]
        return text
