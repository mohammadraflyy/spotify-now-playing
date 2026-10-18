"""Buat ulang screenshot README dan website dengan data contoh (lagu fiktif, cover buatan sendiri).

Pakai: python scripts/screenshots.py
Butuh Google Chrome. Hasilnya ditulis ke docs/screenshots/. Tidak menyentuh pengaturan asli.
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from spotify_now_playing import lyrics, server  # noqa: E402
from spotify_now_playing.chatbot import ChatBot  # noqa: E402
from spotify_now_playing.history import History  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
CHROME = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
          r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]

SONG = {"title": "Senja di Kota Lama", "artist": "Lintas Nada", "album": "Jalan Pulang", "duration": 214.0}
LINES = ["Langit jingga di atas atap", "Langkah pelan menyusuri jalan", "Lampu kota mulai menyala",
         "Kita pulang membawa cerita", "Senja di kota lama", "Tak pernah sama", "Selalu ada yang tertinggal",
         "Di antara suara kereta"]
REQUESTS = [("Lintas Nada - Jalan Pulang", "rani_art", "twitch"), ("Hujan di Bulan Mei", "budi.music", "tiktok"),
            ("Langit Biru - Pagi Tadi", "Dimas Pratama", "youtube"), ("Cerita Kita", "ayu_ws", "tiktok")]


class Config(dict):
    recovered = None

    def update(self, **values):
        for k, v in values.items():
            if v is None:
                self.pop(k, None)
            else:
                self[k] = v


def make_cover():
    """Cover abstrak: gradasi senja dengan matahari dan siluet bukit."""
    size = 640
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    top, bottom = (255, 140, 66), (122, 36, 92)
    for y in range(size):
        t = y / size
        draw.line([(0, y), (size, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    draw.ellipse([200, 230, 440, 470], fill=(255, 214, 120))
    img = img.filter(ImageFilter.GaussianBlur(2))
    draw = ImageDraw.Draw(img)
    draw.polygon([(0, 470), (160, 360), (300, 450), (430, 340), (640, 470), (640, 640), (0, 640)], fill=(58, 20, 54))
    draw.polygon([(0, 540), (220, 450), (420, 530), (640, 460), (640, 640), (0, 640)], fill=(34, 12, 36))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def demo_app(tmp):
    start = time.time() - 83
    cfg = Config(lang="id", source="local", overlay={"bg": "cover", "layout": "row"}, check_updates=True,
                 chat={"twitch": {"enabled": True, "channel": "lintasnada"}, "tiktok": {"enabled": True, "username": "lintasnada"}})

    def snapshot():
        return {"active": True, "playing": True, "ad": False, "device": "Spotify", **SONG,
                "position": (time.time() - start) % SONG["duration"], "updated": time.time(), "cover_version": 1,
                "next": {"title": "Jalan Pulang", "artist": "Lintas Nada", "source": "request", "user": "rani_art",
                         "platform": "twitch"}}

    synced = {"status": "synced", "plain": "", "source": "lrclib", "lrclib_id": 1,
              "lines": [{"t": 70.0 + i * 4.5, "text": line} for i, line in enumerate(LINES)]}
    with mock.patch.object(lyrics, "search", return_value=synced):
        provider = lyrics.LyricsProvider(cache_dir=Path(tmp) / "lyrics")
        provider.track_changed("demo", SONG["title"], SONG["artist"], SONG["album"], SONG["duration"])
        for _ in range(100):
            if provider.get()["status"] == "synced":
                break
            time.sleep(0.02)

    app = SimpleNamespace(
        cfg=cfg, status={"source": "local", "error": ""}, cover=make_cover(), snapshot=snapshot,
        account=SimpleNamespace(logged_in=True, can_control=True, redirect_uri="", logout=lambda: None),
        lyrics=provider, history=History(Path(tmp) / "history"), last_raw=None,
        updates=SimpleNamespace(available=None, status="ok", check_now=lambda: None,
                                install_status={"state": "idle", "progress": 0, "error": ""}))
    app.autoplay = SimpleNamespace(enabled=lambda: True, next=None, status=lambda: {
        "enabled": True, "logged_in": True, "can_control": True, "active": True, "error": ""})
    app.chat = ChatBot(app, tmp)
    for n, (text, user, platform) in enumerate(REQUESTS):
        artist, _, title = text.rpartition(" - ")
        found = {"uri": f"spotify:track:demo{n}", "title": title or text, "artist": artist or "Lintas Nada"}
        app.chat.requests.add(text, user, platform, track=found)
    app.chat.requests.mark_queued(app.chat.requests.list()[0]["id"])
    for chat in (app.chat.twitch, app.chat.youtube, app.chat.tiktok):
        chat.restart = lambda: None
    app.chat.twitch.state = "connected"
    app.chat.tiktok.state = "waiting"
    played = [("Jalan Pulang", "Lintas Nada", None), ("Cerita Kita", "Ayu", None),
              ("Pagi Tadi", "Langit Biru", {"user": "Dimas Pratama", "platform": "youtube"})]
    for i, (title, artist, req) in enumerate(played):  # urut dari yang paling lama, seperti aslinya
        entry = {"time": time.time() - 600 * (len(played) - i), "title": title, "artist": artist, "album": "", "player": "Spotify"}
        if req:
            entry["request"] = req
        app.history.add(entry)
    return app


# alamat loopback lain, supaya URL di screenshot tetap port 8765 walaupun aplikasi asli sedang berjalan
HOST, PORT = "127.0.0.2", 8765


def shoot(chrome, url, name, width, height, bg=None):
    args = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={width},{height}",
            "--virtual-time-budget=4000", f"--screenshot={OUT / name}", url]
    if bg:
        args.insert(1, f"--default-background-color={bg}")
    subprocess.run(args, check=True, capture_output=True, timeout=60)
    if bg == "00000000":  # overlay transparan: buang ruang kosong di sekelilingnya
        img = Image.open(OUT / name)
        box = img.getchannel("A").getbbox()
        if box:
            pad = 12
            img.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad),
                      min(img.height, box[3] + pad))).save(OUT / name)
    print("  ", name)


def main():
    chrome = next((c for c in CHROME if os.path.exists(c)), None) or shutil.which("chrome")
    if not chrome:
        sys.exit("Google Chrome tidak ditemukan")
    tmp = tempfile.mkdtemp()
    app = demo_app(tmp)
    app.account.redirect_uri = f"http://127.0.0.1:{PORT}/callback"
    srv = server.Server((HOST, PORT), server.make_handler(app, PORT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://{HOST}:{PORT}"
    try:
        print("Screenshot ->", OUT)
        shoot(chrome, f"{base}/settings#home", "settings.png", 1100, 880)
        shoot(chrome, f"{base}/settings#card", "settings-card.png", 1100, 860)
        shoot(chrome, f"{base}/settings#lyrics", "settings-lyrics.png", 1100, 860)
        shoot(chrome, f"{base}/settings#requests", "settings-requests.png", 1100, 900)
        shoot(chrome, f"{base}/settings#next", "settings-next.png", 1100, 700)
        shoot(chrome, f"{base}/overlay", "overlay.png", 500, 150, bg="00000000")
        shoot(chrome, f"{base}/requests", "requests.png", 460, 330, bg="00000000")
        shoot(chrome, f"{base}/next", "next.png", 480, 110, bg="00000000")
        app.cfg["lang"] = "en"
        shoot(chrome, f"{base}/settings#home", "settings-en.png", 1100, 800)
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    threading.excepthook = lambda a: None  # thread chat contoh tidak dijalankan
    main()
