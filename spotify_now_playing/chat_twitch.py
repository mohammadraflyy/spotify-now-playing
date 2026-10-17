"""Listener chat Twitch lewat IRC (irc.chat.twitch.tv), secara anonim.

Twitch mengizinkan siapa saja membaca chat channel publik dengan nama "justinfan<angka>"
tanpa login. Karena aplikasi hanya membaca (tidak mengirim pesan), tidak perlu akun maupun Client ID.
"""

import logging
import random
import re
import socket
import ssl
import threading

log = logging.getLogger("snp")

IRC_HOST, IRC_PORT = "irc.chat.twitch.tv", 6697
CHANNEL = re.compile(r"^[a-z0-9_]{3,25}$")


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
        self.state = "off"      # off | setup | connecting | connected | error
        self.error = ""
        self.wake = threading.Event()
        self._sock = None
        self._started = False

    def conf(self):
        return (self.cfg.get("chat") or {}).get("twitch") or {}

    def channel(self):
        return (self.conf().get("channel") or "").strip().lstrip("#").lower()

    def status(self):
        return {"enabled": bool(self.conf().get("enabled")), "channel": self.channel(),
                "state": self.state, "error": self.error}

    def start(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, daemon=True).start()

    def restart(self):
        """Terapkan perubahan pengaturan: putuskan koneksi, loop akan menyambung ulang."""
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
            if not CHANNEL.match(self.channel()):
                self.state, self.error = "setup", ""
                self.wake.wait()
                continue
            try:
                self._session()
                backoff = 2
            except OSError as e:
                if self.wake.is_set():
                    continue  # diputus sengaja oleh restart()
                self.state, self.error = "error", f"Koneksi ke Twitch terputus: {e}"
                log.warning(self.error)
            self.wake.wait(backoff)
            backoff = min(backoff * 2, 60)

    def _session(self):
        channel = self.channel()
        self.state, self.error = "connecting", ""
        raw = socket.create_connection((IRC_HOST, IRC_PORT), timeout=15)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=IRC_HOST)
        self._sock = sock
        try:
            sock.settimeout(400)  # Twitch mengirim PING sekitar tiap 5 menit
            self._send("CAP REQ :twitch.tv/tags twitch.tv/commands")
            self._send(f"NICK justinfan{random.randint(10000, 99999)}")  # login anonim, hanya baca
            self._send(f"JOIN #{channel}")
            buf = b""
            while not self.wake.is_set():
                data = sock.recv(4096)
                if not data:
                    raise ConnectionError("server menutup koneksi")
                buf += data
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    self._handle(line.decode("utf-8", "replace"))
        finally:
            self._sock = None
            try:
                sock.close()
            except OSError:
                pass

    def _send(self, line):
        self._sock.sendall((line + "\r\n").encode("utf-8"))

    def _handle(self, line):
        msg = parse_irc(line)
        cmd, params = msg["command"], msg["params"]
        if cmd == "PING":
            self._send("PONG :" + (params[-1] if params else "tmi.twitch.tv"))
        elif cmd in ("001", "ROOMSTATE"):  # 001 = tersambung
            self.state, self.error = "connected", ""
        elif cmd == "RECONNECT":
            raise ConnectionError("Twitch meminta sambung ulang")
        elif cmd == "PRIVMSG" and len(params) >= 2:
            user = msg["tags"].get("display-name") or msg["prefix"].split("!")[0]
            self.on_message("twitch", user, params[1])
