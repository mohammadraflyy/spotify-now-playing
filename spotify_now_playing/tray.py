"""Ikon di system tray: pengganti jendela console."""

import os
import threading
import time
import webbrowser

import pystray
from PIL import Image

from . import APP_NAME, DONATE_URL, i18n, startup
from .config import OUTPUT_DIR, WEB_DIR


def run_tray(app, settings_url, greet):
    """Blok sampai user memilih Keluar. `greet`: tampilkan notifikasi 'berjalan di tray'."""

    def open_settings(icon=None, item=None):
        webbrowser.open(settings_url)

    def open_folder(icon, item):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(OUTPUT_DIR)

    def open_update(icon, item):
        if not app.updates.available:
            return
        if app.updates.install():  # tidak bisa dipasang otomatis (mis. dari source): buka halaman rilis
            webbrowser.open(app.updates.available["url"])
        else:
            icon.notify(tr("installing", version=app.updates.available["version"]), APP_NAME)

    def open_donate(icon, item):
        webbrowser.open(DONATE_URL)

    def toggle_startup(icon, item):
        try:
            startup.set_enabled(not startup.is_enabled())
        except OSError as e:
            icon.notify(str(e), APP_NAME)

    def tr(key, **kw):
        return i18n.t(app.cfg, key, **kw)

    def quit_app(icon, item):
        icon.stop()

    def update_label(item):
        a = app.updates.available
        return tr("download", version=a["version"]) if a else ""

    icon = pystray.Icon(
        "SpotifyNowPlaying", Image.open(WEB_DIR / "icon.ico"), APP_NAME,
        pystray.Menu(
            pystray.MenuItem(lambda item: tr("open_settings"), open_settings, default=True),
            pystray.MenuItem(update_label, open_update, visible=lambda item: bool(app.updates.available)),
            pystray.MenuItem(lambda item: tr("open_folder"), open_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: tr("startup"), toggle_startup,
                             checked=lambda item: startup.is_enabled(), enabled=startup.supported()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: tr("donate"), open_donate),
            pystray.MenuItem(lambda item: tr("quit"), quit_app),
        ))

    def on_update(info):
        icon.notify(tr("update_found", version=info["version"]), APP_NAME)
        icon.update_menu()

    def watch_title():
        last = None
        while True:
            s = app.snapshot()
            if s["active"] and s.get("ad"):
                title = s["title"]
            elif s["active"]:
                state = "" if s["playing"] else tr("paused")
                title = f"{s['artist']} — {s['title']}{state}"
            elif app.status.get("error"):
                title = app.status["error"]
            else:
                title = tr("nothing")
            title = f"{APP_NAME}\n{title}"[:127]  # batas tooltip Windows
            if title != last:
                last = icon.title = title
            time.sleep(1)

    def setup(icon):
        icon.visible = True
        app.updates.on_found = on_update
        app.updates.start()  # setelah on_found terpasang, supaya notifikasi pertama tidak terlewat
        threading.Thread(target=watch_title, daemon=True).start()
        if app.cfg.recovered:
            icon.notify(tr("config_" + app.cfg.recovered), APP_NAME)  # lebih penting dari sapaan
        elif greet:
            icon.notify(tr("greet"), APP_NAME)

    icon.run(setup=setup)
