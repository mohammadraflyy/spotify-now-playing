"""Listener chat TikTok LIVE (hanya membaca, tidak mengirim) lewat WebSocket Euler Stream.

TikTok tidak punya API resmi untuk chat LIVE. Euler Stream (https://www.eulerstream.com) menjembatani
koneksinya; setiap user memakai API key gratis miliknya sendiri. Pesan datang sebagai protobuf,
jadi di sini ada pembaca WebSocket dan protobuf kecil (tanpa library tambahan).
"""

import base64
import gzip
import logging
import os
import socket
import ssl
import struct
import threading
import urllib.parse
import zlib

log = logging.getLogger("snp")

WS_HOST = "ws.eulerstream.com"
NOT_LIVE_RETRY = 180   # detik: cek ulang apakah sudah live (hemat kuota gratis)

# kode penutupan dari Euler Stream
CLOSE_NOT_LIVE, CLOSE_STREAM_END = 4404, 4005
CLOSE_INVALID_AUTH, CLOSE_INVALID_OPTIONS, CLOSE_TOO_MANY = 4401, 4400, 4429


# ------------------------------------------------------------------ protobuf --

def _varint(buf, i):
    shift = result = 0
    while True:
        if i >= len(buf):
            raise ValueError("varint terpotong")
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7
        if shift > 63:
            raise ValueError("varint terlalu panjang")


def pb_fields(buf):
    """Protobuf mentah -> {nomor_field: [nilai, ...]}. Nilai bertipe bytes (length-delimited) atau int."""
    out, i = {}, 0
    while i < len(buf):
        key, i = _varint(buf, i)
        num, wire = key >> 3, key & 7
        if wire == 0:
            val, i = _varint(buf, i)
        elif wire == 1:
            val, i = buf[i:i + 8], i + 8
        elif wire == 2:
            ln, i = _varint(buf, i)
            if i + ln > len(buf):
                raise ValueError("field terpotong")
            val, i = bytes(buf[i:i + ln]), i + ln
        elif wire == 5:
            val, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"wire type {wire} tidak didukung")
        out.setdefault(num, []).append(val)
    return out


def _str(fields, num):
    vals = fields.get(num) or []
    try:
        return vals[0].decode("utf-8") if vals and isinstance(vals[0], bytes) else ""
    except UnicodeDecodeError:
        return ""


def _maybe_unzip(data):
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    if data[:1] == b"\x78":  # zlib
        try:
            return zlib.decompress(data)
        except zlib.error:
            pass
    return data


def _messages(fetch_result):
    """ProtoMessageFetchResult: field 1 = BaseProtoMessage { 1: type, 2: payload }."""
    out = []
    for raw in pb_fields(fetch_result).get(1, []):
        if not isinstance(raw, bytes):
            continue
        m = pb_fields(raw)
        kind = _str(m, 1)
        if kind.startswith("Webcast") and m.get(2):
            out.append((kind, m[2][0]))
    return out


def decode_frame(data):
    """Satu frame WebSocket biner -> daftar (tipe_pesan, payload).

    Frame bisa berupa WebcastPushFrame (payload di field 8, kadang gzip) atau langsung
    ProtoMessageFetchResult. Keduanya dicoba, yang menghasilkan pesan "Webcast*" dipakai."""
    data = _maybe_unzip(data)
    try:
        msgs = _messages(data)
        if msgs:
            return msgs
    except ValueError:
        pass
    try:
        frame = pb_fields(data)
    except ValueError:
        return []
    payload = (frame.get(8) or [b""])[0]
    if isinstance(payload, bytes) and payload:
        try:
            return _messages(_maybe_unzip(payload))
        except (ValueError, OSError, EOFError):
            return []
    return []


def decode_chat(payload):
    """WebcastChatMessage { 2: User { 3: nickname, 38: uniqueId }, 3: comment } -> (nama, teks)."""
    m = pb_fields(payload)
    user = pb_fields(m[2][0]) if m.get(2) and isinstance(m[2][0], bytes) else {}
    return (_str(user, 3) or _str(user, 38)), _str(m, 3)


# ----------------------------------------------------------------- websocket --

class WebSocketClosed(Exception):
    def __init__(self, code, reason=""):
        super().__init__(f"{code} {reason}".strip())
        self.code = code
        self.reason = reason


class WebSocket:
    """Klien WebSocket (RFC 6455) minimal: cukup untuk menerima pesan dan membalas ping."""

    def __init__(self, host, path, timeout=60):
        raw = socket.create_connection((host, 443), timeout=15)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                           f"User-Agent: SpotifyNowPlaying\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("koneksi ditutup saat handshake")
            head += chunk
        head, self.buf = head.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101 " not in status + " ":
            raise ConnectionError(f"handshake ditolak: {status}")
        self.sock.settimeout(timeout)

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("koneksi terputus")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send(self, opcode, payload=b""):
        mask = os.urandom(4)
        n = len(payload)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def recv(self):
        """Pesan berikutnya (bytes untuk biner, str untuk teks). Raise WebSocketClosed saat ditutup."""
        parts, kind = [], None
        while True:
            b1, b2 = self._read(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:  # close
                code = struct.unpack(">H", data[:2])[0] if len(data) >= 2 else 1005
                try:
                    self._send(0x8, data[:2])
                except OSError:
                    pass
                raise WebSocketClosed(code, data[2:].decode("utf-8", "replace"))
            if opcode == 0x9:  # ping
                self._send(0xA, data)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode in (0x1, 0x2):
                kind, parts = opcode, [data]
            elif opcode == 0x0:
                parts.append(data)
            if fin and kind:
                msg = b"".join(parts)
                return msg.decode("utf-8", "replace") if kind == 0x1 else msg

    def close(self):
        try:
            self._send(0x8, struct.pack(">H", 1000))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# -------------------------------------------------------------------- listener --

class TikTokChat:
    def __init__(self, cfg, on_message):
        self.cfg = cfg
        self.on_message = on_message
        self.state = "off"      # off | setup | waiting | connected | error
        self.error = ""
        self.wake = threading.Event()
        self._ws = None
        self._started = False
        self.connect = WebSocket  # bisa diganti saat test

    def conf(self):
        return (self.cfg.get("chat") or {}).get("tiktok") or {}

    def username(self):
        return (self.conf().get("username") or "").strip().lstrip("@").lower()

    def status(self):
        key = self.cfg.get("tiktok_api_key", "")
        return {"enabled": bool(self.conf().get("enabled")), "username": self.username(),
                "has_key": bool(key), "key_hint": ("•" * 8 + key[-4:]) if key else "",
                "state": self.state, "error": self.error}

    def start(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, daemon=True).start()

    def restart(self):
        self.wake.set()
        ws = self._ws
        if ws:
            ws.close()

    def _run(self):
        backoff = 5
        while True:
            self.wake.clear()
            if not self.conf().get("enabled"):
                self.state, self.error = "off", ""
                self.wake.wait()
                continue
            if not self.username() or not self.cfg.get("tiktok_api_key"):
                self.state, self.error = "setup", ""
                self.wake.wait()
                continue
            delay = backoff
            try:
                self._session()
                backoff = 5
            except WebSocketClosed as e:
                if self.wake.is_set():
                    continue
                if e.code in (CLOSE_NOT_LIVE, CLOSE_STREAM_END):
                    self.state, self.error = "waiting", ""
                    delay = NOT_LIVE_RETRY
                elif e.code in (CLOSE_INVALID_AUTH, CLOSE_INVALID_OPTIONS):
                    self.state = "error"
                    self.error = ("API key Euler Stream tidak valid" if e.code == CLOSE_INVALID_AUTH
                                  else "Username TikTok tidak ditemukan")
                    self.wake.wait()  # tunggu pengaturan diperbaiki
                    continue
                elif e.code == CLOSE_TOO_MANY:
                    self.state, self.error = "error", "Batas koneksi Euler Stream tercapai, dicoba lagi nanti"
                    delay = 300
                else:
                    self.state, self.error = "error", f"Koneksi TikTok ditutup ({e})"
                    backoff = min(backoff * 2, 120)
            except (OSError, ValueError) as e:
                if self.wake.is_set():
                    continue
                self.state, self.error = "error", f"Koneksi ke TikTok terputus: {e}"
                log.warning(self.error)
                backoff = min(backoff * 2, 120)
            self.wake.wait(delay)

    def _session(self):
        query = urllib.parse.urlencode({"uniqueId": self.username(), "apiKey": self.cfg.get("tiktok_api_key")})
        ws = self.connect(WS_HOST, "/?" + query)
        self._ws = ws
        try:
            self.state, self.error = "connected", ""
            while not self.wake.is_set():
                msg = ws.recv()
                if isinstance(msg, bytes):
                    self.handle_frame(msg)
        finally:
            self._ws = None
            ws.close()

    def handle_frame(self, data):
        for kind, payload in decode_frame(data):
            if kind == "WebcastChatMessage":
                try:
                    user, text = decode_chat(payload)
                except (ValueError, IndexError):
                    continue
                if text:
                    self.on_message("tiktok", user, text)  # listener: balasan tidak dikirim ke TikTok
