"""Antrian request lagu dari penonton (Twitch, YouTube, TikTok). Disimpan di folder data."""

import json
import re
import threading
import time
from pathlib import Path

MAX_TEXT = 100


def normalize(text):
    """'Tulus — Hati-Hati di Jalan!' -> 'tulus hati hati di jalan' (untuk cek duplikat/cocok)."""
    return " ".join(re.sub(r"[^\w]+", " ", (text or "").lower()).split())


class RequestQueue:
    def __init__(self, path):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        self.items = []
        self._next_id = 1
        if self.path:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.items = [i for i in data.get("items", []) if isinstance(i, dict) and i.get("text")]
                self._next_id = max([i.get("id", 0) for i in self.items] + [0]) + 1
            except (OSError, ValueError, AttributeError):
                pass

    def _save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"items": self.items}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def list(self):
        with self.lock:
            return [dict(i) for i in self.items]

    def add(self, text, user, platform, max_per_user=2, max_total=50, track=None):
        """Return (status, info). status: added | duplicate | user_limit | full | empty.

        track: lagu hasil pencarian Spotify ({uri, title, artist, ...}) kalau putar otomatis aktif."""
        text = " ".join((text or "").split())[:MAX_TEXT]
        key = normalize(text)
        if not key:
            return "empty", {}
        uri = (track or {}).get("uri")
        with self.lock:
            for pos, item in enumerate(self.items, 1):
                same_text = key in (normalize(item["text"]), normalize(item.get("asked", "")))
                if same_text or (uri and (item.get("track") or {}).get("uri") == uri):
                    return "duplicate", {"position": pos, "text": item["text"]}
            mine = [i for i in self.items if i["user"].lower() == user.lower() and i["platform"] == platform]
            if max_per_user and len(mine) >= max_per_user:
                return "user_limit", {"max": max_per_user}
            if max_total and len(self.items) >= max_total:
                return "full", {"max": max_total}
            item = {"id": self._next_id, "text": text, "user": user, "platform": platform, "time": time.time()}
            if track:
                _apply_track(item, track)
            self._next_id += 1
            self.items.append(item)
            self._save()
            return "added", {"position": len(self.items), "text": item["text"], "id": item["id"]}

    def remove(self, item_id):
        with self.lock:
            before = len(self.items)
            self.items = [i for i in self.items if i["id"] != item_id]
            if len(self.items) != before:
                self._save()
                return True
            return False

    def move(self, item_id, delta):
        with self.lock:
            idx = next((n for n, i in enumerate(self.items) if i["id"] == item_id), None)
            if idx is None:
                return False
            new = max(0, min(len(self.items) - 1, idx + delta))
            self.items.insert(new, self.items.pop(idx))
            self._save()
            return True

    def update(self, item_id, **fields):
        with self.lock:
            for item in self.items:
                if item["id"] == item_id:
                    if fields.get("track"):
                        _apply_track(item, fields.pop("track"))
                    item.update(fields)
                    self._save()
                    return True
            return False

    def mark_queued(self, item_id):
        """Request sudah dimasukkan ke antrian Spotify (jangan dikirim dua kali)."""
        return self.update(item_id, queued=True)

    def clear(self):
        with self.lock:
            self.items = []
            self._save()

    def match_playing(self, title, artist=""):
        """Lagu yang baru diputar cocok dengan request? Hapus dari antrian (request terpenuhi)."""
        t = normalize(title)
        if len(t) < 3:
            return None
        artists = [normalize(a) for a in (artist or "").split(",") if normalize(a)]
        with self.lock:
            for item in self.items:
                track = item.get("track")
                if track:  # lagu pasti dari Spotify: cocokkan judul dan artis utamanya
                    hit = normalize(track["title"]) == t and (
                        not artists or normalize(track["artist"].split(",")[0]) in artists)
                else:
                    hit = _leftover(normalize(item["text"]), t, artists) <= FILLER_WORDS
                if hit:
                    self.items.remove(item)
                    self._save()
                    return item
        return None


FILLER_WORDS = 2  # kata lain yang boleh ada di request, mis. "tolong ... dong"


def _apply_track(item, track):
    """Lagu dari Spotify ketemu: tampilkan "Artis - Judul", simpan teks asli penonton di "asked"."""
    item.setdefault("asked", item["text"])
    item["track"] = track
    item["text"] = f"{track['artist']} - {track['title']}"[:MAX_TEXT]


def _remove_once(words, phrase):
    n = len(phrase)
    for i in range(len(words) - n + 1):
        if words[i:i + n] == phrase:
            return words[:i] + words[i + n:], True
    return words, False


def _leftover(request, title, artists):
    """Jumlah kata di request setelah judul (wajib ada utuh) dan nama artis dibuang."""
    words, found = _remove_once(request.split(), title.split())
    if not found:
        return 999
    for a in artists:
        words, _ = _remove_once(words, a.split())
    return len(words)
