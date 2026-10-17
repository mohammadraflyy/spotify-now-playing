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
    """Coba beberapa cara berurutan. Kalau tidak ketemu dan ada cara yang error, raise:
    hasil "tidak ada lirik" hanya dipercaya (dan di-cache) kalau semua cara benar-benar menjawab."""
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
        if errors:
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




def _fresh(entry):
    """Hasil "tidak ketemu" dicek ulang setelah NONE_TTL, siapa tahu liriknya sudah ditambahkan ke LRCLIB."""
    if entry and entry.get("status") == "none" and time.time() - entry.get("saved", 0) > NONE_TTL:
        return None
    return entry


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
            return _fresh(json.loads(self._path(ckey).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    def save(self, ckey, entry):
        if not self.folder:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self._path(ckey).with_suffix(".tmp")
            tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path(ckey))
        except OSError:
            return
        if not self._pruned:
            self._pruned = True
            threading.Thread(target=self._prune, daemon=True).start()

    def delete(self, ckey):
        if self.folder:
            try:
                self._path(ckey).unlink()
            except OSError:
                pass

    def _prune(self):
        try:
            files = sorted(self.folder.glob("*.json"), key=lambda f: f.stat().st_mtime)
        except OSError:
            return
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
    """Ambil lirik di background saat lagu berganti, dengan cache di memori dan disk.

    Setiap perubahan (ganti lagu, pilihan manual, reset) menaikkan `gen`. Pencarian di background
    hanya boleh menulis hasil kalau `gen`-nya masih sama, jadi hasil lama tidak menimpa yang baru.
    Akses disk selalu di luar lock supaya loop utama (line_at) tidak tertahan.
    """

    def __init__(self, cache_dir=None):
        self.lock = threading.Lock()
        self.memory = {}
        self.disk = LyricsCache(cache_dir)
        self.rev = 0
        self.gen = 0
        self.current = {**EMPTY, "rev": 0}

    def _set(self, **values):
        """Ganti lirik yang sedang aktif (panggil sambil memegang self.lock)."""
        self.rev += 1
        self.current = {**EMPTY, **values, "rev": self.rev}

    def _remember(self, ckey, entry):
        """Simpan ke memori (panggil sambil memegang self.lock); tulis ke disk sesudahnya."""
        entry = {**entry, "saved": time.time()}
        self.memory[ckey] = entry
        return entry

    def track_changed(self, key, title, artist, album, duration):
        ckey = cache_key(title, artist, album)
        track = {"title": title, "artist": artist, "album": album, "duration": duration}
        with self.lock:
            if key == self.current["key"]:
                return
            self.gen += 1
            entry = _fresh(self.memory.get(ckey))
        if entry is None:
            entry = self.disk.load(ckey)
        with self.lock:
            if entry:
                self.memory[ckey] = entry
                self._set(key=key, ckey=ckey, track=track, **_public(entry))
            else:
                self._start_fetch(key, ckey, track)

    def _start_fetch(self, key, ckey, track):
        """Panggil sambil memegang self.lock."""
        self.gen += 1
        self._set(key=key, ckey=ckey, track=track, status="loading")
        threading.Thread(target=self._fetch, args=(self.gen, key, ckey, track), daemon=True).start()

    def clear(self):
        with self.lock:
            self.gen += 1
            self._set()

    def _fetch(self, gen, key, ckey, track):
        for retry, delay in enumerate((0, *BACKGROUND_RETRY)):
            if delay:
                time.sleep(delay)
                with self.lock:
                    if gen != self.gen:
                        return  # lagu berganti atau lirik sudah dipilih manual
            try:
                result = search(track["title"], track["artist"], track["album"], track["duration"])
            except Exception as e:  # jangan di-cache; coba lagi sebentar lagi
                last = retry == len(BACKGROUND_RETRY)
                msg = str(e) + ("" if last else f" — mencoba lagi dalam {BACKGROUND_RETRY[retry]} detik")
                with self.lock:
                    if gen == self.gen:
                        self._set(key=key, ckey=ckey, track=track, status="error", error=msg)
                continue
            with self.lock:
                if gen != self.gen:
                    return
                entry = self._remember(ckey, result)
                self._set(key=key, ckey=ckey, track=track, **_public(entry))
            self.disk.save(ckey, entry)
            return

    # ---------------------------------------------------- perbaikan manual --

    def _check(self, ckey):
        """Lagu yang sedang aktif, dan pastikan masih lagu yang dimaksud halaman pengaturan."""
        cur = self.current
        if not cur["ckey"]:
            raise ValueError("Belum ada lagu yang diputar")
        if ckey and ckey != cur["ckey"]:
            raise ValueError("Lagunya sudah berganti. Coba lagi untuk lagu yang sedang diputar.")
        return cur

    def _replace(self, result, ckey):
        """Simpan lirik pilihan user untuk lagu `ckey` (harus lagu yang sedang diputar)."""
        with self.lock:
            cur = self._check(ckey)
            self.gen += 1  # batalkan pencarian otomatis yang masih berjalan
            entry = self._remember(cur["ckey"], {**result, "offset": cur.get("offset", 0.0)})
            self._set(key=cur["key"], ckey=cur["ckey"], track=cur["track"], **_public(entry))
            snapshot = dict(self.current)
        self.disk.save(cur["ckey"], entry)
        return snapshot

    def use_lrclib(self, lrclib_id, ckey=None):
        with self.lock:
            self._check(ckey)
        hit = _get(f"get/{int(lrclib_id)}", {})
        if not hit:
            raise ValueError("Lirik tidak ditemukan di LRCLIB")
        return self._replace(_result(hit, source="manual"), ckey)

    def use_lrc(self, text, ckey=None):
        lines = parse_lrc(text)
        if not lines:
            raise ValueError("File .lrc tidak berisi baris bertimestamp seperti [01:23.45]")
        return self._replace({"status": "synced", "lines": [{"t": t, "text": w} for t, w in lines],
                              "plain": "", "source": "file"}, ckey)

    def set_offset(self, offset, ckey=None):
        offset = max(-10.0, min(10.0, float(offset)))
        with self.lock:
            cur = self._check(ckey)
            entry = self.memory.get(cur["ckey"])
            if entry is None or cur["status"] in ("loading", "error"):
                raise ValueError("Tunggu sampai lirik lagu ini selesai dimuat")
            entry = self._remember(cur["ckey"], {**entry, "offset": offset})
            self._set(key=cur["key"], ckey=cur["ckey"], track=cur["track"], **_public(entry))
            snapshot = dict(self.current)
        self.disk.save(cur["ckey"], entry)
        return snapshot

    def reset(self, ckey=None):
        """Hapus pilihan manual dan offset lagu ini, lalu cari ulang otomatis."""
        with self.lock:
            cur = self._check(ckey)
            self.gen += 1
            self.memory.pop(cur["ckey"], None)
        self.disk.delete(cur["ckey"])
        with self.lock:
            if self.current["ckey"] == cur["ckey"]:
                self._start_fetch(cur["key"], cur["ckey"], cur["track"])
            return dict(self.current)

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
