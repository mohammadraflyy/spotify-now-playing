"""Web server lokal: overlay OBS, halaman pengaturan, dan API JSON."""

import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, local_media
from .config import OUTPUT_DIR, WEB_DIR

PAGES = {
    "/": "overlay.html", "/overlay": "overlay.html", "/overlay.html": "overlay.html",
    "/settings": "settings.html", "/settings.html": "settings.html",
    "/lyrics": "lyrics.html", "/lyrics.html": "lyrics.html",
}


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
            elif path.startswith("/static/") and path.endswith(".js") and "/" not in path[8:]:
                f = WEB_DIR / path[8:]
                if f.is_file():
                    self._send(200, f.read_bytes(), "text/javascript; charset=utf-8")
                else:
                    self._send(404, b"not found", "text/plain")
            elif path == "/api/now":
                self._send(200, json.dumps(app.snapshot()).encode(), "application/json",
                           {"Access-Control-Allow-Origin": "*"})
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
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._json({"error": "JSON tidak valid"}, 400)
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
            else:
                self._json({"error": "not found"}, 404)
                return
            self._json(public_config())

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


def start_server(app, port):
    """Raise OSError kalau port sudah dipakai."""
    app.account.redirect_uri = f"http://127.0.0.1:{port}/callback"  # Spotify menolak "localhost"
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
