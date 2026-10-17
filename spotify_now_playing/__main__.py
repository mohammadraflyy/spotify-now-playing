"""Entry point: python -m spotify_now_playing  (atau SpotifyNowPlaying.exe)."""

import argparse
import ctypes
import json
import logging
import logging.handlers
import os
import sys
import threading
import urllib.request
import webbrowser

from . import APP_NAME, __version__
from .app import NowPlayingApp
from .config import DATA_DIR, Config
from .server import start_server

LOG_FILE = DATA_DIR / "app.log"
log = logging.getLogger("snp")


def already_running(port):
    """True kalau port dipakai oleh instance aplikasi ini sendiri."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=2) as r:
            return "redirect_uri" in json.load(r)
    except Exception:
        return False


def message_box(text, error=False):
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10 if error else 0x40)
    else:
        print(text)


def setup_logging():
    """Tanpa console, error dicatat ke app.log di folder data aplikasi."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=256_000, backupCount=1,
                                                       encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    except OSError:
        pass
    sys.excepthook = lambda *exc: log.error("crash", exc_info=exc)
    threading.excepthook = lambda a: log.error("thread crash", exc_info=(a.exc_type, a.exc_value,
                                                                         a.exc_traceback))


def main():
    p = argparse.ArgumentParser(prog="SpotifyNowPlaying", description=f"{APP_NAME} untuk OBS")
    p.add_argument("--port", type=int, help="port web untuk sesi ini (default 8765)")
    p.add_argument("--no-browser", action="store_true", help="jangan buka halaman pengaturan")
    p.add_argument("--console", action="store_true", help="tampilkan status di console, tanpa ikon tray")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args()

    setup_logging()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    cfg = Config()
    port = args.port or cfg.get("port", 8765)  # --port hanya untuk sesi ini
    settings_url = f"http://127.0.0.1:{port}/settings"

    app = NowPlayingApp(cfg)
    try:
        start_server(app, port)
    except OSError:
        if already_running(port):
            if not args.no_browser:
                webbrowser.open(settings_url)  # sudah jalan di tray: buka pengaturannya saja
        else:
            message_box(f"Port {port} sedang dipakai aplikasi lain.\n\n"
                        f"Tutup aplikasi tersebut, atau jalankan dengan --port 8766.", error=True)
        return

    log.info("start v%s port %s", __version__, port)
    first_run = cfg.first_run
    if first_run:
        cfg.update()  # buat config.json supaya browser tidak terbuka tiap start
    if not args.no_browser and first_run:
        webbrowser.open(settings_url)
    app.updates.start()

    try:
        from .tray import run_tray
    except ImportError:
        args.console = True  # dijalankan dari source tanpa pystray

    if args.console:
        if os.name == "nt":
            ctypes.windll.kernel32.SetConsoleTitleW(f"{APP_NAME} {__version__}")
        print(f"  {APP_NAME} v{__version__}  |  {settings_url}  |  Ctrl+C untuk keluar")
        app.console = True
        try:
            app.run()
        except KeyboardInterrupt:
            pass
        return

    threading.Thread(target=app.run, daemon=True).start()
    run_tray(app, settings_url, greet=not args.no_browser and not first_run)
    log.info("exit")


if __name__ == "__main__":
    main()
