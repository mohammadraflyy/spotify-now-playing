"""Web server lokal: overlay OBS, halaman pengaturan, dan API JSON."""

import json
import os
import re
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, i18n, local_media, lyrics, startup
from .app import format_line
from .config import DATA_DIR, OUTPUT_DIR, WEB_DIR

PAGES = {
    "/": "overlay.html", "/overlay": "overlay.html", "/overlay.html": "overlay.html",
    "/settings": "settings.html", "/settings.html": "settings.html",
    "/lyrics": "lyrics.html", "/lyrics.html": "lyrics.html",
    "/requests": "requests.html", "/requests.html": "requests.html",
}
STATIC = re.compile(r"^/static/((?:fonts/)?[\w.-]+\.(js|css|woff2|txt))$")
STATIC_TYPES = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8",
                "woff2": "font/woff2", "txt": "text/plain; charset=utf-8"}
PRESET_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
CHAT_COMMAND = re.compile(r"^\S{1,30}$")
MAX_BODY = 1_000_000


def make_handler(app, port):
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def public_config():
        cfg = app.cfg
        secret = cfg.get("client_secret", "")
        return {
            "version": __version__,
            "client_id": cfg.get("client_id", ""),
            "has_secret": bool(secret),
            "secret_hint": ("•" * 8 + secret[-4:]) if secret else "",
            "logged_in": app.account.logged_in,
            "user": cfg.get("user", ""),
            "auth_type": cfg.get("auth_type", ""),
            "source": cfg.get("source", "auto"),
            "overlay": cfg.get("overlay", {}),
            "presets": cfg.get("presets", {}),
            "requests_overlay": cfg.get("requests_overlay", {}),
            "players": cfg.get("players", "spotify"),
            "lang": i18n.lang(cfg),
            "check_updates": bool(cfg.get("check_updates", False)),
            "update": app.updates.available,
            "update_status": app.updates.status,
            "startup": {"supported": startup.supported(), "enabled": startup.is_enabled()},
            "data_dir": str(DATA_DIR),
            "text": cfg.get("text", {}),
            "lyrics": cfg.get("lyrics", {}),
            "local_available": local_media.AVAILABLE,
            "redirect_uri": app.account.redirect_uri,
            "port": port,
            "output_dir": str(OUTPUT_DIR),
            "status": dict(app.status),
        }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _redirect(self, url):
            self._send(302, b"", "text/plain", {"Location": url})

        def _settings_error(self, msg):
            self._redirect("/settings?login=error&msg=" + urllib.parse.quote(msg))

        # ------------------------------------------------------------ GET --

        def do_GET(self):
            path, _, query = self.path.partition("?")
            q = urllib.parse.parse_qs(query)
            if path in PAGES:
                self._send(200, (WEB_DIR / PAGES[path]).read_bytes(), "text/html; charset=utf-8")
            elif STATIC.match(path):
                name, ext = STATIC.match(path).groups()
                f = WEB_DIR / name
                if f.is_file():
                    self._send(200, f.read_bytes(), STATIC_TYPES[ext],
                               {"Cache-Control": "max-age=86400"} if ext == "woff2" else None)
                else:
                    self._send(404, b"not found", "text/plain")
            elif path == "/favicon.ico":
                self._send(200, (WEB_DIR / "icon.ico").read_bytes(), "image/x-icon")
            elif path == "/api/now":
                self._send(200, json.dumps(app.snapshot()).encode(), "application/json",
                           {"Access-Control-Allow-Origin": "*"})
            elif path == "/api/now.txt":
                # untuk chatbot lokal (Streamer.bot, Mix It Up): perintah !song
                s = app.snapshot()
                fmt = (q.get("format") or [None])[0] or app.cfg.get("text", {}).get("format")
                if s["active"]:
                    text = format_line(fmt, s)
                else:
                    text = (q.get("empty") or [None])[0] or i18n.t(app.cfg, "nothing")
                self._send(200, text.encode("utf-8"), "text/plain; charset=utf-8",
                           {"Access-Control-Allow-Origin": "*"})
            elif path == "/api/history":
                dates = app.history.dates()
                date = (q.get("date") or [None])[0] or (dates[0] if dates else "")
                self._json({"dates": dates, "date": date, "entries": app.history.entries(date)})
            elif path == "/api/history.txt":
                date = (q.get("date") or [""])[0]
                date = date if re.match(r"^\d{4}-\d{2}-\d{2}$", date) else ""
                extra = {} if q.get("inline") else {
                    "Content-Disposition": f'attachment; filename="riwayat-lagu-{date}.txt"'}
                self._send(200, app.history.text(date).encode("utf-8"), "text/plain; charset=utf-8", extra)
            elif path == "/api/lyrics":
                self._send(200, json.dumps(app.lyrics.get()).encode(), "application/json",
                           {"Access-Control-Allow-Origin": "*"})
            elif path == "/cover":
                cover = app.cover
                if cover:
                    ctype = "image/png" if cover[:4] == b"\x89PNG" else "image/jpeg"
                    self._send(200, cover, ctype)
                else:
                    self._send(404, b"", "text/plain")
            elif path == "/api/config":
                self._json(public_config())
            elif path == "/api/requests":
                s = app.chat.settings()
                self._send(200, json.dumps({
                    "items": app.chat.requests.list(), "enabled": bool(s.get("request_enabled")),
                    "cmd": s.get("request_cmd", ""), "lang": i18n.lang(app.cfg),
                }).encode(), "application/json", {"Access-Control-Allow-Origin": "*"})
            elif path == "/api/chat":
                self._json(app.chat.status())
            elif path == "/youtube/login":
                try:
                    self._redirect(app.chat.youtube.login_url())
                except ValueError as e:
                    self._redirect("/settings?chat=error&msg=" + urllib.parse.quote(str(e)) + "#chat")
            elif path == "/youtube/callback":
                get = lambda k: (q.get(k) or [None])[0]
                try:
                    if not get("code"):
                        raise ValueError(get("error") or "dibatalkan")
                    app.chat.youtube.finish_login(get("state"), get("code"))
                    self._redirect("/settings?chat=ok#chat")
                except Exception as e:
                    self._redirect("/settings?chat=error&msg=" + urllib.parse.quote(str(e)) + "#chat")
            elif path == "/login":
                if not app.cfg.get("client_id"):
                    self._settings_error("Isi Client ID dulu")
                else:
                    self._redirect(app.account.login_url())
            elif path == "/callback":
                get = lambda k: (q.get(k) or [None])[0]
                if not get("code"):
                    self._settings_error(get("error") or "dibatalkan")
                    return
                try:
                    app.account.finish_login(get("state"), get("code"))
                    self._redirect("/settings?login=ok")
                except Exception as e:
                    self._settings_error(str(e))
            else:
                self._send(404, b"not found", "text/plain")

        # ----------------------------------------------------------- POST --

        def do_POST(self):
            # tolak request dari website lain (CSRF): hanya halaman settings sendiri
            origin = self.headers.get("Origin")
            if origin and origin not in allowed_origins:
                self._json({"error": "forbidden"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise ValueError
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                self._json({"error": "JSON tidak valid"}, 400)
                return

            if self.path.startswith("/api/lyrics/"):
                self._lyrics_action(self.path[len("/api/lyrics/"):], body)
                return
            if self.path.startswith("/api/requests/"):
                queue = app.chat.requests
                action = self.path[len("/api/requests/"):]
                try:
                    item_id = int(body.get("id") or 0)
                except (TypeError, ValueError):
                    item_id = 0
                if action == "remove":
                    queue.remove(item_id)
                elif action == "move":
                    delta = body.get("delta")
                    queue.move(item_id, -1 if isinstance(delta, (int, float)) and delta < 0 else 1)
                elif action == "clear":
                    queue.clear()
                else:
                    self._json({"error": "not found"}, 404)
                    return
                self._json({"items": queue.list()})
                return
            if self.path.startswith("/api/chat/"):
                self._chat_action(self.path[len("/api/chat/"):], body)
                return
            if self.path == "/api/config":
                err = self._save_config(body)
                if err:
                    self._json({"error": err}, 400)
                    return
            elif self.path == "/api/logout":
                app.account.logout()
            elif self.path == "/api/open-output":
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                os.startfile(OUTPUT_DIR)
            elif self.path == "/api/history/clear":
                app.history.clear(str(body.get("date") or ""))
            elif self.path == "/api/open-data":
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                os.startfile(DATA_DIR)
            elif self.path == "/api/startup":
                try:
                    startup.set_enabled(bool(body.get("enabled")))
                except OSError as e:
                    self._json({"error": str(e)}, 400)
                    return
            else:
                self._json({"error": "not found"}, 404)
                return
            self._json(public_config())

        def _lyrics_action(self, action, body):
            """Perbaikan lirik untuk lagu yang sedang diputar."""
            try:
                if action == "search":
                    title = str(body.get("title") or "").strip()
                    if not title:
                        raise ValueError("Isi judul lagu")
                    self._json({"results": lyrics.candidates(title, str(body.get("artist") or "").strip())})
                    return
                ckey = body.get("ckey")  # lagu yang dimaksud halaman pengaturan
                if action == "use":
                    result = app.lyrics.use_lrclib(body.get("id"), ckey)
                elif action == "lrc":
                    result = app.lyrics.use_lrc(str(body.get("text") or ""), ckey)
                elif action == "offset":
                    result = app.lyrics.set_offset(body.get("offset") or 0, ckey)
                elif action == "reset":
                    result = app.lyrics.reset(ckey)
                else:
                    self._json({"error": "not found"}, 404)
                    return
            except (TypeError, ValueError) as e:
                self._json({"error": str(e) or "Input tidak valid"}, 400)
                return
            except Exception as e:  # LRCLIB error / offline
                self._json({"error": f"Gagal menghubungi LRCLIB: {e}"}, 502)
                return
            self._json(result)

        def _chat_action(self, action, body):
            """Pengaturan listener chat (Twitch, YouTube, TikTok) dan request lagu."""
            chat = app.chat
            try:
                if action == "config":
                    err = self._save_chat(body)
                    if err:
                        raise ValueError(err)
                elif action == "youtube/logout":
                    chat.youtube.logout()
                else:
                    self._json({"error": "not found"}, 404)
                    return
            except ValueError as e:
                self._json({"error": str(e)}, 400)
                return
            self._json(chat.status())

        def _save_chat(self, body):
            cfg = app.cfg
            cur = dict(cfg.get("chat") or {})
            if "request_enabled" in body:
                cur["request_enabled"] = bool(body["request_enabled"])
            if "request_cmd" in body:
                cmd = str(body["request_cmd"] or "").strip()
                if cmd and not CHAT_COMMAND.match(cmd):
                    return "Perintah harus satu kata tanpa spasi, maksimal 30 karakter"
                cur["request_cmd"] = cmd
            for key, top in (("request_max_user", 20), ("request_max_total", 200)):
                if key in body:
                    try:
                        cur[key] = max(0, min(top, int(body[key])))
                    except (TypeError, ValueError):
                        return "Batas request harus angka"
            if isinstance(body.get("twitch"), dict):
                tw = {**(cur.get("twitch") or {})}
                b = body["twitch"]
                if "enabled" in b:
                    tw["enabled"] = bool(b["enabled"])
                if "channel" in b:
                    ch = str(b["channel"] or "").strip().lstrip("#").lower()
                    if ch and not re.match(r"^[a-z0-9_]{3,25}$", ch):
                        return "Nama channel Twitch tidak valid"
                    tw["channel"] = ch
                cur["twitch"] = tw
            if isinstance(body.get("youtube"), dict):
                yt = {**(cur.get("youtube") or {})}
                b = body["youtube"]
                if "enabled" in b:
                    yt["enabled"] = bool(b["enabled"])
                if "client_id" in b:
                    cid = str(b["client_id"] or "").strip()
                    if cid and not re.match(r"^[\w.-]{10,200}$", cid):
                        return "Client ID Google tidak valid"
                    if cid != yt.get("client_id", "") and cfg.get("youtube_auth"):
                        cfg.update(youtube_auth=None)
                    yt["client_id"] = cid
                if "client_secret" in b:
                    cfg.update(youtube_client_secret=str(b["client_secret"] or "").strip()[:200] or None)
                cur["youtube"] = yt
            if isinstance(body.get("tiktok"), dict):
                tt = {**(cur.get("tiktok") or {})}
                b = body["tiktok"]
                if "enabled" in b:
                    tt["enabled"] = bool(b["enabled"])
                if "username" in b:
                    name = str(b["username"] or "").strip().lstrip("@").lower()
                    if name and not re.match(r"^[a-z0-9_.]{2,24}$", name):
                        return "Username TikTok tidak valid"
                    tt["username"] = name
                if "api_key" in b:
                    cfg.update(tiktok_api_key=str(b["api_key"] or "").strip()[:300] or None)
                cur["tiktok"] = tt
            cfg.update(chat=cur)
            app.chat.twitch.restart()
            app.chat.youtube.restart()
            app.chat.tiktok.restart()
            return None

        def _save_config(self, body):
            cfg = app.cfg
            new_id = (body.get("client_id") or "").strip()
            if new_id and not (len(new_id) == 32 and new_id.isalnum()):
                return "Client ID harus 32 karakter huruf/angka"
            if new_id and new_id != cfg.get("client_id"):
                app.account.logout()  # app beda -> login lama tidak berlaku
                cfg.update(client_id=new_id)
            if "client_secret" in body:
                cfg.update(client_secret=(body["client_secret"] or "").strip() or None)
            if body.get("source") in ("auto", "account", "local"):
                cfg.update(source=body["source"])
            if isinstance(body.get("overlay"), dict):
                cfg.update(overlay=body["overlay"])
            if isinstance(body.get("requests_overlay"), dict):
                cfg.update(requests_overlay=body["requests_overlay"])
            if isinstance(body.get("presets"), dict):
                presets = body["presets"]
                if len(presets) > 20:
                    return "Maksimal 20 preset"
                for name, opts in presets.items():
                    if not PRESET_NAME.match(name) or not isinstance(opts, dict):
                        return "Nama preset hanya boleh huruf kecil, angka, dan tanda -"
                cfg.update(presets=presets)
            if body.get("lang") in i18n.TEXT:
                cfg.update(lang=body["lang"])
            if body.get("players") in ("spotify", "all"):
                cfg.update(players=body["players"])
            if "check_updates" in body:
                cfg.update(check_updates=bool(body["check_updates"]))
                app.updates.check_now()
            if isinstance(body.get("lyrics"), dict):
                lyr = body["lyrics"]
                try:
                    offset = max(-10.0, min(10.0, float(lyr.get("offset") or 0)))
                except (TypeError, ValueError):
                    return "Offset lirik harus angka"
                cfg.update(lyrics={**{k: lyr[k] for k in lyr if k != "offset"}, "offset": offset})
            if isinstance(body.get("text"), dict):
                cfg.update(text={"format": str(body["text"].get("format") or "")[:200],
                                 "hide_paused": bool(body["text"].get("hide_paused"))})
            return None

    return Handler


class Server(ThreadingHTTPServer):
    # HTTPServer bawaan memakai SO_REUSEADDR. Di Windows itu membuat dua aplikasi bisa
    # memakai port yang sama sekaligus, jadi instance kedua tidak pernah tahu port sudah dipakai.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def start_server(app, port):
    """Raise OSError kalau port sudah dipakai."""
    app.account.redirect_uri = f"http://127.0.0.1:{port}/callback"  # Spotify menolak "localhost"
    app.chat.youtube.redirect_uri = f"http://127.0.0.1:{port}/youtube/callback"
    server = Server(("127.0.0.1", port), make_handler(app, port))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
