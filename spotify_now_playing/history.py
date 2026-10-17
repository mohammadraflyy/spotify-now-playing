"""Riwayat lagu yang diputar, satu file per hari di folder data (tidak pernah dikirim ke mana pun)."""

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

MIN_PLAY = 15  # detik diputar sebelum masuk riwayat (lagu yang di-skip tidak dicatat)
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class History:
    def __init__(self, folder):
        self.folder = Path(folder) if folder else None
        self.lock = threading.Lock()
        self._key = None
        self._start = 0.0
        self._played = 0.0
        self._last = 0.0
        self._logged = False

    def observe(self, s, now=None):
        """Dipanggil setiap tick dengan snapshot lagu yang sedang diputar."""
        now = time.time() if now is None else now
        if not s.get("active"):
            self._last = now
            return
        key = f"{s['title']}|{s['artist']}"
        if key != self._key:
            self._key, self._start, self._played, self._logged = key, now, 0.0, False
        elif s.get("playing"):
            self._played += min(now - self._last, 5)  # jeda panjang (sleep/hibernate) tidak dihitung
        self._last = now
        if not self._logged and self._played >= MIN_PLAY:
            self._logged = True
            self.add({"time": self._start, "title": s["title"], "artist": s["artist"],
                      "album": s.get("album", ""), "player": s.get("device", "")})

    def _file(self, date):
        return self.folder / f"{date}.jsonl"

    def add(self, entry):
        if not self.folder:
            return
        date = datetime.fromtimestamp(entry["time"]).strftime("%Y-%m-%d")
        with self.lock:
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                with self._file(date).open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError:
                pass

    def dates(self):
        if not self.folder or not self.folder.is_dir():
            return []
        return sorted((f.stem for f in self.folder.glob("*.jsonl") if DATE.match(f.stem)), reverse=True)

    def entries(self, date):
        if not self.folder or not DATE.match(date or ""):
            return []
        out = []
        with self.lock:
            try:
                lines = self._file(date).read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass  # baris rusak (mis. listrik mati saat menulis)
        return out

    def text(self, date):
        """'21:03  Tulus - Hati-Hati di Jalan' per baris, untuk deskripsi VOD."""
        return "".join(f"{datetime.fromtimestamp(e['time']).strftime('%H:%M')}  {e['artist']} - {e['title']}\n"
                       for e in self.entries(date))

    def clear(self, date):
        if self.folder and DATE.match(date or ""):
            with self.lock:
                try:
                    self._file(date).unlink()
                except OSError:
                    pass
