"""Ikon di system tray: pengganti jendela console."""

import os
import threading
import time
import webbrowser

import pystray
from PIL import Image

from . import APP_NAME, startup
from .config import OUTPUT_DIR, WEB_DIR


def run_tray(app, settings_url, greet):
    """Blok sampai user memilih Keluar. `greet`: tampilkan notifikasi 'berjalan di tray'."""

    def open_settings(icon=None, item=None):
        webbrowser.open(settings_url)

    def open_folder(icon, item):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(OUTPUT_DIR)

    def open_update(icon, item):
        if app.updates.available:
            webbrowser.open(app.updates.available["url"])

    def toggle_startup(icon, item):
        try:
            startup.set_enabled(not startup.is_enabled())
        except OSError as e:
            icon.notify(str(e), APP_NAME)

    def quit_app(icon, item):
        icon.stop()

    def update_label(item):
        a = app.updates.available
        return f"Download versi {a['version']}" if a else ""

    icon = pystray.Icon(
        "SpotifyNowPlaying", Image.open(WEB_DIR / "icon.ico"), APP_NAME,
        pystray.Menu(
            pystray.MenuItem("Buka pengaturan", open_settings, default=True),
            pystray.MenuItem(update_label, open_update, visible=lambda item: bool(app.updates.available)),
            pystray.MenuItem("Buka folder file teks", open_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Jalankan saat Windows menyala", toggle_startup,
                             checked=lambda item: startup.is_enabled(), enabled=startup.supported()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Keluar", quit_app),
        ))

    def on_update(info):
        icon.notify(f"Versi {info['version']} tersedia. Klik kanan ikon ini untuk download.", APP_NAME)
        icon.update_menu()

    def watch_title():
        last = None
        while True:
            s = app.snapshot()
            if s["active"]:
                state = "" if s["playing"] else " (pause)"
                title = f"{s['artist']} — {s['title']}{state}"
            elif app.status.get("error"):
                title = app.status["error"]
            else:
                title = "Tidak ada lagu yang diputar"
            title = f"{APP_NAME}\n{title}"[:127]  # batas tooltip Windows
            if title != last:
                last = icon.title = title
            time.sleep(1)

    def setup(icon):
        icon.visible = True
        app.updates.on_found = on_update
        threading.Thread(target=watch_title, daemon=True).start()
        if greet:
            icon.notify("Berjalan di system tray. Klik ikonnya untuk membuka pengaturan.", APP_NAME)

    icon.run(setup=setup)
