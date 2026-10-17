"""Chat Twitch lewat IRC (irc.chat.twitch.tv), login dengan Device Code Flow.

Device Code Flow: aplikasi meminta kode, user membuka twitch.tv/activate dan memasukkan kodenya.
Tidak butuh client secret maupun redirect URL, cocok untuk aplikasi desktop open source.
"""

import json
import logging
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("snp")

AUTH = "https://id.twitch.tv/oauth2"
SCOPES = "chat:read chat:edit"
IRC_HOST, IRC_PORT = "irc.chat.twitch.tv", 6697
# Client ID aplikasi Twitch milik proyek (tipe "Public"). Kosong: user mengisi Client ID sendiri.
DEFAULT_CLIENT_ID = ""


class TwitchError(Exception):
    pass


class AuthFailed(Exception):
    pass


def _post(url, data):
    req = urllib.request.Request(url, urllib.parse.urlencode(data).encode(),
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except ValueError:
            body = {}
        raise TwitchError(body.get("message") or body.get("error") or f"HTTP {e.code}") from None


def validate(token):
    req = urllib.request.Request(f"{AUTH}/validate", headers={"Authorization": f"OAuth {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise AuthFailed(f"HTTP {e.code}") from None


def parse_irc(line):
    """'@a=1;b=2 :nick!nick@host PRIVMSG #ch :halo' -> {tags, prefix, command, params}."""
    tags, prefix = {}, ""
    if line.startswith("@"):
        raw, _, line = line[1:].partition(" ")
        for part in raw.split(";"):
            k, _, v = part.partition("=")
            tags[k] = v.replace("\\s", " ").replace("\\:", ";").replace("\\\\", "\\")
    if line.startswith(":"):
        prefix, _, line = line[1:].partition(" ")
    head, sep, trailing = line.partition(" :")
    parts = head.split()
    params = parts[1:] + ([trailing] if sep else [])
    return {"tags": tags, "prefix": prefix, "command": parts[0] if parts else "", "params": params}


class TwitchChat:
    def __init__(self, cfg, on_message):
        self.cfg = cfg
        self.on_message = on_message
        self.state = "off"      # off | login | connecting | connected | error
        self.error = ""
        self.device = None      # login yang sedang berjalan: {user_code, verification_uri, expires_at}
        self.wake = threading.Event()
        self._sock = None
        self._started = False

    # ------------------------------------------------------------ status --

    def conf(self):
        return (self.cfg.get("chat") or {}).get("twitch") or {}

    def auth(self):
        return self.cfg.get("twitch_auth") or {}

    def client_id(self):
        return self.conf().get("client_id") or DEFAULT_CLIENT_ID

    def status(self):
        d = self.device
        return {
            "enabled": bool(self.conf().get("enabled")), "client_id": self.conf().get("client_id", ""),
            "builtin_client": bool(DEFAULT_CLIENT_ID), "state": self.state, "error": self.error,
            "login": self.auth().get("login", ""),
            "device": {"user_code": d["user_code"], "verification_uri": d["verification_uri"]} if d else None,
        }

    # ------------------------------------------------------------- login --

    def begin_login(self):
        cid = self.client_id()
        if not cid:
            raise ValueError("Isi Client ID Twitch dulu")
        try:
            r = _post(f"{AUTH}/device", {"client_id": cid, "scopes": SCOPES})
        except TwitchError as e:
            raise ValueError(f"Twitch menolak Client ID ini ({e}). Pastikan Client ID benar dan "
                             f"Client Type-nya Public.") from None
        self.device = {"user_code": r["user_code"], "verification_uri": r["verification_uri"],
                       "expires_at": time.time() + r.get("expires_in", 1800)}
        self.error = ""
        threading.Thread(target=self._poll_device, args=(cid, r["device_code"], r.get("interval", 5),
                                                         r["user_code"]), daemon=True).start()
        return self.status()

    def _poll_device(self, cid, device_code, interval, user_code):
        while self.device and self.device["user_code"] == user_code:
            if time.time() > self.device["expires_at"]:
                self.device, self.error = None, "Kode login Twitch kedaluwarsa. Coba hubungkan lagi."
                return
            time.sleep(interval)
            try:
                tok = _post(f"{AUTH}/token", {"client_id": cid, "scopes": SCOPES, "device_code": device_code,
                                              "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
            except TwitchError as e:
                msg = str(e).lower()
                if "pending" in msg:
                    continue
                if "slow_down" in msg:
                    interval += 5
                    continue
                if self.device and self.device["user_code"] == user_code:
                    self.device, self.error = None, f"Login Twitch gagal: {e}"
                return
            except OSError:
                continue  # internet putus sesaat
            try:
                info = validate(tok["access_token"])
            except (AuthFailed, OSError) as e:
                self.device, self.error = None, f"Login Twitch gagal: {e}"
                return
            self.cfg.update(twitch_auth={"access_token": tok["access_token"],
                                         "refresh_token": tok.get("refresh_token", ""),
                                         "login": info["login"], "user_id": info.get("user_id", ""),
                                         "client_id": cid})
            self.device = None
            self.restart()
            return

    def cancel_login(self):
        self.device = None

    def logout(self):
        self.device = None
        self.cfg.update(twitch_auth=None)
        self.restart()

    def _refresh(self):
        auth = self.auth()
        if not auth.get("refresh_token"):
            raise AuthFailed("tanpa refresh token")
        try:
            tok = _post(f"{AUTH}/token", {"client_id": auth.get("client_id") or self.client_id(),
                                          "grant_type": "refresh_token", "refresh_token": auth["refresh_token"]})
        except TwitchError as e:
            raise AuthFailed(str(e)) from None
        self.cfg.update(twitch_auth={**auth, "access_token": tok["access_token"],
                                     "refresh_token": tok.get("refresh_token", auth["refresh_token"])})

    # --------------------------------------------------------------- IRC --

    def start(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, daemon=True).start()

    def restart(self):
        """Terapkan perubahan pengaturan/login: putuskan koneksi, loop akan menyambung ulang."""
        self.wake.set()
        sock = self._sock
        if sock:
            try:
                sock.close()
            except OSError:
                pass

    def _run(self):
        backoff = 2
        while True:
            self.wake.clear()
            if not self.conf().get("enabled"):
                self.state, self.error = "off", ""
                self.wake.wait()
                continue
            if not self.auth().get("access_token"):
                self.state = "login"
                self.wake.wait()
                continue
            try:
                self._session()
                backoff = 2
            except AuthFailed:
                try:
                    self._refresh()
                    continue
                except (AuthFailed, OSError):
                    self.cfg.update(twitch_auth=None)
                    self.state, self.error = "login", "Login Twitch kedaluwarsa. Hubungkan lagi."
                    continue
            except OSError as e:
                if self.wake.is_set():
                    continue  # diputus sengaja oleh restart()
                self.state, self.error = "error", f"Koneksi ke Twitch terputus: {e}"
                log.warning(self.error)
            self.wake.wait(backoff)
            backoff = min(backoff * 2, 60)
        # (tidak pernah keluar)

    def _session(self):
        auth = self.auth()
        login = auth["login"].lower()
        self.state, self.error = "connecting", ""
        raw = socket.create_connection((IRC_HOST, IRC_PORT), timeout=15)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=IRC_HOST)
        self._sock = sock
        try:
            sock.settimeout(400)  # Twitch mengirim PING sekitar tiap 5 menit
            self._send(f"CAP REQ :twitch.tv/tags twitch.tv/commands")
            self._send(f"PASS oauth:{auth['access_token']}")
            self._send(f"NICK {login}")
            self._send(f"JOIN #{login}")
            buf = b""
            while not self.wake.is_set():
                data = sock.recv(4096)
                if not data:
                    raise ConnectionError("server menutup koneksi")
                buf += data
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    self._handle(line.decode("utf-8", "replace"), login)
        finally:
            self._sock = None
            try:
                sock.close()
            except OSError:
                pass

    def _send(self, line):
        self._sock.sendall((line + "\r\n").encode("utf-8"))

    def _handle(self, line, login):
        msg = parse_irc(line)
        cmd, params = msg["command"], msg["params"]
        if cmd == "PING":
            self._send("PONG :" + (params[-1] if params else "tmi.twitch.tv"))
        elif cmd in ("001", "ROOMSTATE"):  # 001 = login diterima
            self.state, self.error = "connected", ""
        elif cmd == "NOTICE" and params and ("authentication failed" in params[-1].lower()
                                             or "improperly formatted auth" in params[-1].lower()):
            raise AuthFailed(params[-1])
        elif cmd == "RECONNECT":
            raise ConnectionError("Twitch meminta sambung ulang")
        elif cmd == "PRIVMSG" and len(params) >= 2:
            user = msg["tags"].get("display-name") or msg["prefix"].split("!")[0]
            reply = self.on_message("twitch", user, params[1])
            if reply:
                self._send(f"PRIVMSG {params[0]} :{reply}")
