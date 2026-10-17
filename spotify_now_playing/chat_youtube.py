"""Chat live YouTube lewat YouTube Data API v3, login Google OAuth (aplikasi desktop + PKCE).

Bot mengecek apakah channel sedang live. Kalau iya, pesan chat dibaca secara berkala
(YouTube tidak punya koneksi realtime gratis) dan jawaban dikirim lewat API yang sama.
Kuota gratis API terbatas, jadi jeda baca minimal POLL_MIN detik.
"""

import base64
import hashlib
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("snp")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
POLL_MIN = 10       # detik antar baca chat (hemat kuota)
IDLE_CHECK = 60     # detik antar cek "sudah live belum?"
CHAT_ENDED = {"liveChatEnded", "liveChatNotFound", "liveChatDisabled", "forbidden"}


class YouTubeError(Exception):
    def __init__(self, message, reason=""):
        super().__init__(message)
        self.reason = reason


class AuthFailed(Exception):
    pass


def _request(method, url, data=None, headers=None, form=False):
    body = None
    headers = dict(headers or {})
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, body, headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e)
        except ValueError:
            err = {}
        if isinstance(err.get("error"), dict):  # format YouTube API
            reason = ((err["error"].get("errors") or [{}])[0]).get("reason", "")
            raise YouTubeError(err["error"].get("message") or f"HTTP {e.code}", reason) from None
        raise YouTubeError(err.get("error_description") or err.get("error") or f"HTTP {e.code}",
                           err.get("error", "")) from None


class YouTubeChat:
    def __init__(self, cfg, on_message):
        self.cfg = cfg
        self.on_message = on_message
        self.redirect_uri = ""      # diisi server: http://127.0.0.1:<port>/youtube/callback
        self.state = "off"          # off | login | waiting | connected | error
        self.error = ""
        self.live_title = ""
        self.wake = threading.Event()
        self._pending = {}          # state OAuth -> code_verifier
        self._started = False

    # ------------------------------------------------------------ status --

    def conf(self):
        return (self.cfg.get("chat") or {}).get("youtube") or {}

    def auth(self):
        return self.cfg.get("youtube_auth") or {}

    def status(self):
        secret = self.cfg.get("youtube_client_secret", "")
        return {
            "enabled": bool(self.conf().get("enabled")), "client_id": self.conf().get("client_id", ""),
            "has_secret": bool(secret), "secret_hint": ("•" * 8 + secret[-4:]) if secret else "",
            "state": self.state, "error": self.error, "channel": self.auth().get("channel", ""),
            "live_title": self.live_title, "redirect_uri": self.redirect_uri,
        }

    # ------------------------------------------------------------- login --

    def login_url(self):
        cid = self.conf().get("client_id")
        if not cid or not self.cfg.get("youtube_client_secret"):
            raise ValueError("Isi Client ID dan Client Secret Google dulu")
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(16)
        self._pending = {state: verifier}  # hanya login terakhir yang berlaku
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        return AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": cid, "redirect_uri": self.redirect_uri, "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })

    def finish_login(self, state, code):
        verifier = self._pending.pop(state, None)
        if not verifier:
            raise ValueError("Sesi login kedaluwarsa, coba login lagi")
        tok = _request("POST", TOKEN_URL, {
            "client_id": self.conf().get("client_id"), "client_secret": self.cfg.get("youtube_client_secret"),
            "code": code, "code_verifier": verifier, "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }, form=True)
        auth = {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token", ""),
                "expires_at": time.time() + tok.get("expires_in", 3600)}
        self.cfg.update(youtube_auth=auth)
        try:
            items = self._api("GET", "channels", {"part": "snippet", "mine": "true"}).get("items") or []
            channel = items[0]["snippet"]["title"] if items else ""
        except (YouTubeError, AuthFailed, OSError):
            channel = ""
        self.cfg.update(youtube_auth={**auth, "channel": channel})
        self.error = ""
        self.restart()

    def logout(self):
        self.cfg.update(youtube_auth=None)
        self.restart()

    def _token(self):
        auth = self.auth()
        if not auth.get("access_token"):
            raise AuthFailed("belum login")
        if auth.get("expires_at", 0) - 60 > time.time():
            return auth["access_token"]
        if not auth.get("refresh_token"):
            raise AuthFailed("tanpa refresh token")
        try:
            tok = _request("POST", TOKEN_URL, {
                "client_id": self.conf().get("client_id"), "client_secret": self.cfg.get("youtube_client_secret"),
                "refresh_token": auth["refresh_token"], "grant_type": "refresh_token",
            }, form=True)
        except YouTubeError as e:
            if e.reason in ("invalid_grant", "invalid_client", "unauthorized_client"):
                raise AuthFailed(str(e)) from None
            raise
        self.cfg.update(youtube_auth={**auth, "access_token": tok["access_token"],
                                      "expires_at": time.time() + tok.get("expires_in", 3600)})
        return tok["access_token"]

    def _api(self, method, path, params, body=None):
        url = f"{API}/{path}?" + urllib.parse.urlencode(params)
        return _request(method, url, body, {"Authorization": f"Bearer {self._token()}"})

    # -------------------------------------------------------------- loop --

    def start(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, daemon=True).start()

    def restart(self):
        self.wake.set()

    def _run(self):
        while True:
            self.wake.clear()
            self.live_title = ""
            if not self.conf().get("enabled"):
                self.state, self.error = "off", ""
                self.wake.wait()
                continue
            if not self.auth().get("access_token"):
                self.state = "login"
                self.wake.wait()
                continue
            try:
                chat_id, title = self._active_chat()
                if not chat_id:
                    self.state, self.error = "waiting", ""
                    self.wake.wait(IDLE_CHECK)
                    continue
                self.state, self.error, self.live_title = "connected", "", title
                self._poll(chat_id)
            except AuthFailed:
                self.cfg.update(youtube_auth=None)
                self.state, self.error = "login", "Login YouTube kedaluwarsa. Login lagi."
            except (YouTubeError, OSError, ValueError, KeyError) as e:
                self.state, self.error = "error", f"YouTube: {e}"
                log.warning(self.error)
                self.wake.wait(IDLE_CHECK)

    def _active_chat(self):
        r = self._api("GET", "liveBroadcasts", {"part": "snippet", "broadcastStatus": "active",
                                                "broadcastType": "all", "maxResults": 5})
        for item in r.get("items") or []:
            sn = item.get("snippet") or {}
            if sn.get("liveChatId"):
                return sn["liveChatId"], sn.get("title", "")
        return None, ""

    def _poll(self, chat_id):
        page, first = None, True
        while not self.wake.is_set():
            params = {"liveChatId": chat_id, "part": "snippet,authorDetails", "maxResults": 200}
            if page:
                params["pageToken"] = page
            try:
                r = self._api("GET", "liveChat/messages", params)
            except YouTubeError as e:
                if e.reason in CHAT_ENDED:
                    return  # live selesai: kembali menunggu live berikutnya
                raise
            if not first:  # pesan lama sebelum bot tersambung tidak dijawab
                for item in r.get("items") or []:
                    sn, author = item.get("snippet") or {}, item.get("authorDetails") or {}
                    text = sn.get("displayMessage") or (sn.get("textMessageDetails") or {}).get("messageText", "")
                    reply = self.on_message("youtube", author.get("displayName", ""), text)
                    if reply:
                        self._send(chat_id, reply)
            first = False
            page = r.get("nextPageToken")
            if r.get("offlineAt"):
                return
            self.wake.wait(max(POLL_MIN, (r.get("pollingIntervalMillis") or 0) / 1000))

    def _send(self, chat_id, text):
        try:
            self._api("POST", "liveChat/messages", {"part": "snippet"}, {"snippet": {
                "liveChatId": chat_id, "type": "textMessageEvent",
                "textMessageDetails": {"messageText": text}}})
        except YouTubeError as e:
            self.error = f"Gagal mengirim jawaban ke YouTube: {e}"
            log.warning(self.error)
