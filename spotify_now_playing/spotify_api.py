"""Login (OAuth) dan pembacaan lagu lewat Spotify Web API.

Kalau Client Secret diisi -> Authorization Code biasa, kalau tidak -> PKCE.
"""

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
SCOPES = "user-read-currently-playing user-read-playback-state"
TOKEN_KEYS = ("access_token", "refresh_token", "expires_at", "auth_type", "user")


class ApiError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__(f"API error {code}: {msg}")
        self.code = code


def _error_text(e):
    body = e.read().decode(errors="replace")
    try:
        data = json.loads(body)
        err = data.get("error")
        if isinstance(err, dict):
            return err.get("message") or body
        return data.get("error_description") or err or body
    except ValueError:
        return body


def download(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.read()
    except Exception:
        return b""


class SpotifyAccount:
    def __init__(self, config):
        self.cfg = config
        self._pending = {"state": None, "verifier": None}
        self.redirect_uri = ""

    # ------------------------------------------------------------ status --

    @property
    def logged_in(self):
        return bool(self.cfg.get("client_id") and self.cfg.get("refresh_token"))

    def logout(self):
        self.cfg.update(**{k: None for k in TOKEN_KEYS})

    # ------------------------------------------------------------- login --

    def login_url(self):
        self._pending["state"] = secrets.token_urlsafe(16)
        params = {
            "client_id": self.cfg["client_id"],
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "state": self._pending["state"],
            "show_dialog": "true",
        }
        if self.cfg.get("client_secret"):
            self._pending["verifier"] = None
        else:
            verifier = secrets.token_urlsafe(64)[:96]
            self._pending["verifier"] = verifier
            params["code_challenge_method"] = "S256"
            params["code_challenge"] = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        return AUTH_URL + "?" + urllib.parse.urlencode(params)

    def finish_login(self, state, code):
        if not self._pending["state"] or state != self._pending["state"]:
            raise RuntimeError("Sesi login tidak valid, coba lagi")
        self._pending["state"] = None
        verifier = self._pending["verifier"]
        data = {"grant_type": "authorization_code", "code": code,
                "redirect_uri": self.redirect_uri}
        if verifier:
            data["code_verifier"] = verifier
        tok = self._token_request(data, use_secret=not verifier)
        self.cfg.update(auth_type="pkce" if verifier else "secret")
        self._store(tok)
        try:
            _, me = self.get("/me")
            self.cfg.update(user=(me or {}).get("display_name") or (me or {}).get("id") or "")
        except Exception:
            pass  # nama user cuma kosmetik

    # ------------------------------------------------------------- token --

    def _token_request(self, data, use_secret):
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if use_secret:
            pair = f"{self.cfg['client_id']}:{self.cfg['client_secret']}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(pair).decode()
        else:
            data["client_id"] = self.cfg["client_id"]
        req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(data).encode(),
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"token error {e.code}: {_error_text(e)}") from None

    def _store(self, tok):
        self.cfg.update(access_token=tok["access_token"],
                        expires_at=time.time() + tok.get("expires_in", 3600) - 60)
        if tok.get("refresh_token"):
            self.cfg.update(refresh_token=tok["refresh_token"])

    def _access_token(self):
        if time.time() >= self.cfg.get("expires_at", 0):
            self._store(self._token_request(
                {"grant_type": "refresh_token", "refresh_token": self.cfg["refresh_token"]},
                use_secret=self.cfg.get("auth_type") == "secret"))
        return self.cfg["access_token"]

    # --------------------------------------------------------------- api --

    def get(self, path):
        """Return (status, json|None). 401 -> refresh token lalu coba sekali lagi."""
        for attempt in range(2):
            req = urllib.request.Request(API_URL + path, headers={
                "Authorization": f"Bearer {self._access_token()}"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    raw = r.read()
                    return r.status, (json.loads(raw) if raw else None)
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self.cfg.update(expires_at=0)
                    continue
                if e.code == 429:
                    raise ApiError(429, f"rate limit, tunggu {e.headers.get('Retry-After', '?')} detik")
                raise ApiError(e.code, _error_text(e)) from None
        raise ApiError(401, "token tidak valid, silakan login ulang")

    def now_playing(self):
        """Info lagu yang sedang diputar, atau None."""
        code, data = self.get("/me/player?additional_types=episode")
        if code == 204 or not data or not data.get("item"):
            return None
        item = data["item"]
        if item.get("type") == "episode":
            show = item.get("show") or {}
            artist = album = show.get("name", "")
            images = item.get("images") or show.get("images") or []
        else:
            artist = ", ".join(a["name"] for a in item.get("artists", []))
            album = (item.get("album") or {}).get("name", "")
            images = (item.get("album") or {}).get("images") or []
        cover_url = images[0]["url"] if images else ""
        return {
            "id": item.get("id") or item.get("uri") or item.get("name"),
            "title": item.get("name", ""),
            "artist": artist,
            "album": album,
            "cover": lambda: download(cover_url) if cover_url else b"",
            "duration": (item.get("duration_ms") or 0) / 1000,
            "position": (data.get("progress_ms") or 0) / 1000,
            "playing": bool(data.get("is_playing")),
            "device": (data.get("device") or {}).get("name", ""),
        }
