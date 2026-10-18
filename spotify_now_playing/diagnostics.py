"""Info diagnosa untuk laporan masalah. Hanya dibuat saat diminta dari halaman pengaturan, tidak dikirim ke
mana pun: user sendiri yang menyalin dan membagikannya. Token, key, dan secret disamarkan."""

import json
import platform
import re
import sys
import time

from . import __version__
from .config import LOG_FILE

LOG_LINES = 50
# kunci yang tidak boleh ikut, walaupun cuma petunjuk 4 karakter terakhir
SECRET_KEY = re.compile(r"secret|token|key|hint|password|auth|code|verifier", re.I)
SECRET_TEXT = [
    (re.compile(r"(?i)((?:access_token|refresh_token|token|apikey|api_key|key|secret|code|password)[\"']?\s*[=:]\s*[\"']?)[^\s&\"',}]+"), r"\1***"),
    (re.compile(r"(?i)(bearer\s+)[\w.\-~+/]+=*"), r"\1***"),
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "***"),  # string panjang mirip token
]


def scrub(value):
    """Hapus field rahasia dari dict/list secara rekursif."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if not SECRET_KEY.search(str(k))}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def scrub_text(text):
    for pattern, repl in SECRET_TEXT:
        text = pattern.sub(repl, text)
    return text


def tail(path, n=LOG_LINES):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(belum ada app.log)"
    return "\n".join(lines[-n:]) or "(app.log kosong)"


def report(app):
    cfg = app.cfg
    snap = app.snapshot()
    try:
        chat = app.chat.status()
    except Exception as e:  # noqa: BLE001  (diagnosa tidak boleh gagal total)
        chat = {"error": str(e)}
    ad_audio = getattr(app, "ad_audio", None)
    local = getattr(app, "local", None)
    settings = {k: cfg.get(k) for k in ("source", "players", "lang", "check_updates", "ads", "text")}
    sections = [
        ("Aplikasi", {
            "versi": __version__,
            "windows": platform.platform(),
            "python": sys.version.split()[0],
            "waktu": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "frozen": bool(getattr(sys, "frozen", False)),
        }),
        ("Pengaturan", settings),
        ("Status", {
            **dict(app.status),
            "login_spotify": bool(getattr(app.account, "logged_in", False)),
            "watchdog_restart": getattr(local, "restarts", None),
        }),
        ("Lagu sekarang", {k: snap.get(k) for k in ("active", "playing", "ad", "title", "artist", "album",
                                                    "device", "position", "duration")}),
        ("Data mentah dari player", getattr(app, "last_raw", None)),
        ("Iklan", {
            "mode_berjalan": getattr(ad_audio, "applied", None),
            "mode_dipakai": ad_audio.mode() if ad_audio else None,
            "perlu_dipulihkan": cfg.get("ad_restore"),
        }),
        ("Chat", chat),
        ("Antrian request", {"jumlah": len(app.chat.requests.list())}),
        ("Update", {"status": app.updates.status, "tersedia": app.updates.available,
                    "install": getattr(app.updates, "install_status", None)}),
    ]
    out = [f"=== Spotify Now Playing: info diagnosa ==="]
    for title, data in sections:
        out.append(f"\n[{title}]\n{json.dumps(scrub(data), ensure_ascii=False, indent=2, default=str)}")
    out.append(f"\n[app.log, {LOG_LINES} baris terakhir]\n{tail(LOG_FILE)}")
    return scrub_text("\n".join(out)) + "\n"
