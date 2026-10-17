"""Entry point: python -m spotify_now_playing  (atau SpotifyNowPlaying.exe)."""

import argparse
import ctypes
import json
import os
import sys
import urllib.request
import webbrowser

from . import APP_NAME, __version__
from .app import NowPlayingApp
from .config import CONFIG_FILE, OUTPUT_DIR, Config
from .server import start_server


def already_running(port):
    """True kalau port dipakai oleh instance aplikasi ini sendiri."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=2) as r:
            return "redirect_uri" in json.load(r)
    except Exception:
        return False


def main():
    p = argparse.ArgumentParser(prog="SpotifyNowPlaying", description=f"{APP_NAME} untuk OBS")
    p.add_argument("--port", type=int, help="port web (default 8765, tersimpan di pengaturan)")
    p.add_argument("--no-browser", action="store_true", help="jangan buka halaman pengaturan")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args()

    if os.name == "nt":
        os.system("")  # aktifkan ANSI di console lama
        ctypes.windll.kernel32.SetConsoleTitleW(f"{APP_NAME} {__version__}")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    cfg = Config()
    if args.port:
        cfg.update(port=args.port)
    port = cfg.get("port", 8765)
    settings_url = f"http://127.0.0.1:{port}/settings"

    app = NowPlayingApp(cfg)
    try:
        start_server(app, port)
    except OSError:
        if already_running(port):
            print("  Aplikasi sudah berjalan, membuka halaman pengaturan...")
            webbrowser.open(settings_url)
        else:
            print(f"  Port {port} dipakai aplikasi lain. Jalankan dengan --port 8766")
            input("  Tekan Enter untuk keluar...")
        return

    print("=" * 64)
    print(f"  {APP_NAME} untuk OBS  v{__version__}")
    print("=" * 64)
    print(f"  Pengaturan     : {settings_url}")
    print(f"  Browser source : http://127.0.0.1:{port}/overlay")
    print(f"  File teks      : {OUTPUT_DIR}")
    print(f"  Config         : {CONFIG_FILE}")
    print("  Tutup jendela ini atau tekan Ctrl+C untuk keluar.")
    print("-" * 64)

    if cfg.first_run:
        cfg.update()  # buat config.json supaya browser tidak terbuka tiap start
    if not args.no_browser and cfg.first_run:
        webbrowser.open(settings_url)

    try:
        app.run()
    except KeyboardInterrupt:
        print("\n  Bye!")


if __name__ == "__main__":
    main()
