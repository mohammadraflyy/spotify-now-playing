import gzip
import struct
import tempfile
import time
import unittest

from spotify_now_playing import chat_tiktok
from spotify_now_playing.song_requests import RequestQueue, normalize


# ------------------------------------------------------ encoder protobuf kecil --

def varint(n):
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out += bytes([b | 0x80])
        else:
            return out + bytes([b])


def field(num, value):
    if isinstance(value, int):
        return varint(num << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    return varint(num << 3 | 2) + varint(len(value)) + value


def chat_payload(nickname, comment, unique_id="budi01"):
    user = field(1, 123) + field(3, nickname) + field(38, unique_id)
    return field(1, b"common") + field(2, user) + field(3, comment)


def fetch_result(*messages):
    return b"".join(field(1, field(1, kind) + field(2, payload) + field(3, 99)) for kind, payload in messages) \
        + field(2, "cursor")


def push_frame(payload, gzipped=False):
    if gzipped:
        payload = gzip.compress(payload)
    return field(1, 7) + field(2, 8) + field(6, "pb") + field(7, "msg") + field(8, payload)


class FakeConfig(dict):
    def update(self, **values):
        for k, v in values.items():
            if v is None:
                self.pop(k, None)
            else:
                self[k] = v


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = f"{self.tmp.name}/requests.json"
        self.q = RequestQueue(self.path)

    def test_add_and_persist(self):
        self.assertEqual(self.q.add("Tulus - Pamit", "budi", "tiktok")[0], "added")
        status, info = self.q.add("  Hindia   - Evaluasi ", "ani", "twitch")
        self.assertEqual((status, info["position"], info["text"]), ("added", 2, "Hindia - Evaluasi"))
        again = RequestQueue(self.path)
        self.assertEqual([i["text"] for i in again.list()], ["Tulus - Pamit", "Hindia - Evaluasi"])
        self.assertEqual(again.add("x", "c", "youtube")[1]["id"], 3)  # id lanjut, tidak bentrok

    def test_duplicate_and_limits(self):
        self.q.add("Tulus - Pamit", "budi", "tiktok")
        self.assertEqual(self.q.add("tulus PAMIT!!", "ani", "twitch")[0], "duplicate")
        self.q.add("Lagu 2", "budi", "tiktok")
        self.assertEqual(self.q.add("Lagu 3", "budi", "tiktok"), ("user_limit", {"max": 2}))
        self.assertEqual(self.q.add("Lagu 3", "budi", "twitch")[0], "added")  # orang lain di platform lain
        self.assertEqual(self.q.add("Lagu 4", "x", "tiktok", max_total=3)[0], "full")
        self.assertEqual(self.q.add("   ", "x", "tiktok")[0], "empty")
        self.assertEqual(self.q.add("Lagu 5", "budi", "tiktok", max_per_user=0, max_total=0)[0], "added")

    def test_remove_move_clear(self):
        ids = [self.q.add(t, "u" + t, "tiktok")[1]["id"] for t in ("a1", "b2", "c3")]
        self.q.move(ids[2], -1)
        self.assertEqual([i["text"] for i in self.q.list()], ["a1", "c3", "b2"])
        self.q.remove(ids[0])
        self.assertEqual(len(self.q.list()), 2)
        self.q.clear()
        self.assertEqual(RequestQueue(self.path).list(), [])

    def test_auto_remove_when_played(self):
        self.q.add("Tulus - Hati-Hati di Jalan", "budi", "tiktok")
        self.q.add("pamit", "ani", "tiktok")
        self.q.add("Pamitan - Band Lain", "c", "tiktok")
        self.assertIsNone(self.q.match_playing("Hati", "Tulus"))  # judul tidak boleh cocok sebagian kata
        self.assertEqual(self.q.match_playing("Hati-Hati di Jalan", "Tulus")["user"], "budi")
        self.assertEqual(self.q.match_playing("Pamit", "Tulus")["user"], "ani")  # request cuma judul
        self.assertEqual([i["text"] for i in self.q.list()], ["Pamitan - Band Lain"])

    def test_auto_remove_allows_filler_words(self):
        self.q.add("tolong putar Evaluasi dong", "a", "tiktok")
        self.q.add("evaluasi hindia please", "b", "tiktok")
        self.assertEqual(self.q.match_playing("Evaluasi", "Hindia")["user"], "b")  # sisa 1 kata
        self.assertIsNone(self.q.match_playing("Evaluasi", "Hindia"))  # "tolong putar ... dong" = 3 kata lain

    def test_normalize(self):
        self.assertEqual(normalize("Tulus — Hati-Hati di Jalan!"), "tulus hati hati di jalan")


class ProtobufTest(unittest.TestCase):
    def test_push_frame_with_gzip(self):
        frame = push_frame(fetch_result(("WebcastChatMessage", chat_payload("Budi", "!request Pamit")),
                                        ("WebcastLikeMessage", b"x")), gzipped=True)
        msgs = chat_tiktok.decode_frame(frame)
        self.assertEqual([k for k, _ in msgs], ["WebcastChatMessage", "WebcastLikeMessage"])
        self.assertEqual(chat_tiktok.decode_chat(msgs[0][1]), ("Budi", "!request Pamit"))

    def test_bare_fetch_result(self):
        msgs = chat_tiktok.decode_frame(fetch_result(("WebcastChatMessage", chat_payload("Ani", "halo"))))
        self.assertEqual(chat_tiktok.decode_chat(msgs[0][1]), ("Ani", "halo"))

    def test_nickname_fallback_and_unicode(self):
        payload = field(2, field(38, "budi01")) + field(3, "!request Évaluasi ✓")
        self.assertEqual(chat_tiktok.decode_chat(payload), ("budi01", "!request Évaluasi ✓"))

    def test_garbage_is_ignored(self):
        for junk in (b"", b"\xff\xff\xff", b"hello world", push_frame(b"\x0a\xff")):
            self.assertEqual(chat_tiktok.decode_frame(junk), [], junk)


class FakeSocket:
    """Menyuapkan byte dari server ke klien WebSocket dan mencatat yang dikirim klien."""

    def __init__(self, data):
        self.data, self.sent = data, b""

    def recv(self, n):
        chunk, self.data = self.data[:n], self.data[n:]
        return chunk

    def sendall(self, b):
        self.sent += b

    def close(self):
        pass


def server_frame(opcode, payload, fin=True):
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    return head + payload


class WebSocketTest(unittest.TestCase):
    def make(self, data):
        ws = chat_tiktok.WebSocket.__new__(chat_tiktok.WebSocket)
        ws.sock, ws.buf = FakeSocket(data), b""
        return ws

    def test_messages_ping_fragments_and_close(self):
        big = b"x" * 70000
        data = (server_frame(0x2, b"abc") + server_frame(0x9, b"hi") + server_frame(0x1, "he".encode(), fin=False)
                + server_frame(0x0, "llo".encode()) + server_frame(0x2, big)
                + server_frame(0x8, struct.pack(">H", 4404) + b"not live"))
        ws = self.make(data)
        self.assertEqual(ws.recv(), b"abc")
        self.assertEqual(ws.recv(), "hello")
        self.assertEqual(ws.recv(), big)
        with self.assertRaises(chat_tiktok.WebSocketClosed) as ctx:
            ws.recv()
        self.assertEqual((ctx.exception.code, ctx.exception.reason), (4404, "not live"))
        sent = ws.sock.sent
        self.assertEqual(sent[0], 0x8A)  # pong untuk ping
        self.assertTrue(sent[1] & 0x80)  # frame dari klien wajib di-mask


class TikTokListenerTest(unittest.TestCase):
    def test_json_text_frames(self):
        # format Euler Stream yang sebenarnya: frame teks JSON (schema v2), bisa berisi beberapa pesan
        import json
        now = int(time.time() * 1000)

        def chat(nick, uid, comment, created):
            return {"type": "WebcastChatMessage", "data": {"common": {"createTime": str(created)},
                    "user": {"nickname": nick, "uniqueId": uid}, "comment": comment}}

        frame = json.dumps({"messages": [
            chat("Lama", "lama01", "!request Lagu Lama", now - 5 * 60_000),  # riwayat sebelum tersambung
            {"type": "WebcastLikeMessage", "data": {}},
            chat("Budi", "budi01", "!request Tulus - Pamit", now),
            chat("", "ani02", "halo", now),
        ], "timestamp": now})
        got = []
        t = chat_tiktok.TikTokChat(FakeConfig(), lambda p, u, c: got.append((p, u, c)))
        t.since = now - 10_000
        t.handle_text(frame)
        self.assertEqual(got, [("tiktok", "Budi", "!request Tulus - Pamit"), ("tiktok", "ani02", "halo")])
        t.handle_text("bukan json")
        t.handle_text(json.dumps({"messages": [{"type": "workerInfo", "data": {}}]}))
        self.assertEqual(len(got), 2)

    def test_close_codes(self):
        cfg = FakeConfig(chat={"tiktok": {"enabled": True, "username": "tulus"}}, tiktok_api_key="k")
        got = []
        chat = chat_tiktok.TikTokChat(cfg, lambda p, u, t: got.append((p, u, t)))
        frames = [push_frame(fetch_result(("WebcastChatMessage", chat_payload("Budi", "!request Pamit"))))]

        class FakeWS:
            def __init__(self, host, path):
                self.path = path

            def recv(self):
                if frames:
                    return frames.pop(0)
                raise chat_tiktok.WebSocketClosed(chat_tiktok.CLOSE_NOT_LIVE)

            def close(self):
                pass

        chat.connect = FakeWS
        with self.assertRaises(chat_tiktok.WebSocketClosed):
            chat._session()
        self.assertEqual(got, [("tiktok", "Budi", "!request Pamit")])

    def test_run_states(self):
        cfg = FakeConfig(chat={"tiktok": {"enabled": True, "username": "@Tulus"}}, tiktok_api_key="k")
        chat = chat_tiktok.TikTokChat(cfg, lambda *a: None)
        paths = []

        def fake_connect(host, path):
            paths.append(path)
            raise chat_tiktok.WebSocketClosed(chat_tiktok.CLOSE_INVALID_AUTH)

        chat.connect = fake_connect
        chat.start()
        deadline = time.time() + 2
        while chat.state != "error" and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(chat.state, "error")
        self.assertIn("API key", chat.error)
        self.assertIn("uniqueId=tulus", paths[0])
        cfg["chat"] = {"tiktok": {"enabled": False}}
        chat.restart()
        deadline = time.time() + 2
        while chat.state != "off" and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(chat.state, "off")


if __name__ == "__main__":
    unittest.main()
