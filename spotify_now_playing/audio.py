"""Suara Spotify selama iklan: bisukan atau kecilkan sesi audio spotify.exe di Windows (Core Audio)."""

import ctypes
import logging
import os
import time
import uuid
from ctypes import POINTER, byref, c_float, c_int, c_uint, c_ulong, c_void_p, wintypes

log = logging.getLogger("snp")

AVAILABLE = os.name == "nt"
MODES = ("mute", "quiet", "off")
DEFAULT_VOLUME = 10   # persen, untuk mode "quiet"
PAUSE_WINDOW = 4      # detik: iklan berhenti sesaat setelah dibisukan = Spotify menjedanya
RETRY = 5            # detik antar percobaan memulihkan suara kalau Spotify sedang tidak berbunyi
PROCESS = "spotify.exe"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        u = uuid.UUID(text)
        super().__init__(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


CLSID_MMDeviceEnumerator = GUID("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = GUID("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioSessionManager2 = GUID("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")
IID_IAudioSessionControl2 = GUID("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D")
IID_ISimpleAudioVolume = GUID("87CE5498-68D6-44E5-9215-6DA47EF883D8")
CLSCTX_ALL = 0x17
E_RENDER, DEVICE_STATE_ACTIVE = 0, 1


def _com(obj, index, argtypes, *args):
    """Panggil method ke-`index` di vtable objek COM. HRESULT gagal -> OSError."""
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(vtbl[index])(obj, *args)


def _release(obj):
    if obj and obj.value:
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
        ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtbl[2])(obj)


def _exe(pid):
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, byref(size)):
            return ""
        return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(handle)


def _spotify_volumes():
    """ISimpleAudioVolume untuk setiap sesi audio Spotify, di semua perangkat output aktif."""
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx(None, 0)  # sudah diinisialisasi (mis. oleh winrt) juga tidak apa-apa
    ole32.CoCreateInstance.restype = ctypes.HRESULT
    enum, coll, out = c_void_p(), c_void_p(), []
    try:
        ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                               byref(IID_IMMDeviceEnumerator), byref(enum))
        _com(enum, 3, (c_uint, wintypes.DWORD, POINTER(c_void_p)), E_RENDER, DEVICE_STATE_ACTIVE, byref(coll))
        count = c_uint()
        _com(coll, 3, (POINTER(c_uint),), byref(count))
        for i in range(count.value):
            dev, mgr, sessions = c_void_p(), c_void_p(), c_void_p()
            try:
                _com(coll, 4, (c_uint, POINTER(c_void_p)), i, byref(dev))
                _com(dev, 3, (POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p)),
                     byref(IID_IAudioSessionManager2), CLSCTX_ALL, None, byref(mgr))
                _com(mgr, 5, (POINTER(c_void_p),), byref(sessions))
                n = c_int()
                _com(sessions, 3, (POINTER(c_int),), byref(n))
                for j in range(n.value):
                    ctl, ctl2 = c_void_p(), c_void_p()
                    try:
                        _com(sessions, 4, (c_int, POINTER(c_void_p)), j, byref(ctl))
                        _com(ctl, 0, (POINTER(GUID), POINTER(c_void_p)), byref(IID_IAudioSessionControl2), byref(ctl2))
                        pid = wintypes.DWORD()
                        _com(ctl2, 14, (POINTER(wintypes.DWORD),), byref(pid))
                        if pid.value and _exe(pid.value) == PROCESS:
                            vol = c_void_p()
                            _com(ctl, 0, (POINTER(GUID), POINTER(c_void_p)), byref(IID_ISimpleAudioVolume), byref(vol))
                            out.append(vol)
                    except OSError:
                        pass
                    finally:
                        _release(ctl2)
                        _release(ctl)
            except OSError:
                pass
            finally:
                _release(sessions)
                _release(mgr)
                _release(dev)
    finally:
        _release(coll)
        _release(enum)
    return out


def _each(fn):
    vols = _spotify_volumes()
    try:
        return [fn(v) for v in vols]
    finally:
        for v in vols:
            _release(v)


def set_mute(on):
    """Jumlah sesi Spotify yang diubah (0 = Spotify belum mengeluarkan suara)."""
    return len(_each(lambda v: _com(v, 5, (wintypes.BOOL, c_void_p), bool(on), None)))


def get_volume():
    def read(v):
        level = c_float()
        _com(v, 4, (POINTER(c_float),), byref(level))
        return level.value
    levels = _each(read)
    return max(levels) if levels else None


def set_volume(level):
    return len(_each(lambda v: _com(v, 3, (c_float, c_void_p), float(level), None)))


class AdAudio:
    """Mengatur suara Spotify selama iklan dan mengembalikannya setelah iklan selesai.

    Mode "mute" membisukan Spotify. Kalau Spotify ternyata menjeda iklan yang dibisukan, aplikasi
    beralih ke mode "quiet" (volume kecil) dan mengingatnya untuk iklan berikutnya. Yang perlu
    dikembalikan disimpan di config ("ad_restore"), supaya tetap dipulihkan kalau aplikasi
    tertutup di tengah iklan."""

    def __init__(self, cfg, backend=None):
        self.cfg = cfg
        self.backend = backend or _Backend()
        self.applied = None      # mode yang sedang berjalan untuk iklan ini
        self.applied_at = 0.0
        self.was_playing = False
        self.retry_at = 0.0
        self.restore()           # sisa dari sesi sebelumnya yang tertutup di tengah iklan

    def settings(self):
        return self.cfg.get("ads") or {}

    def mode(self):
        a = self.settings()
        mode = a.get("mode") if a.get("mode") in MODES else "mute"
        return "quiet" if mode == "mute" and a.get("mute_pauses") else mode

    def level(self):
        try:
            return max(0, min(50, int(self.settings().get("volume", DEFAULT_VOLUME)))) / 100
        except (TypeError, ValueError):
            return DEFAULT_VOLUME / 100

    def update(self, ad, playing, now=None):
        now = time.time() if now is None else now
        if not ad:
            self.applied = None
            if self.cfg.get("ad_restore") and now >= self.retry_at:
                if not self.restore():
                    self.retry_at = now + RETRY
            return
        if self.applied is None:
            self._apply(self.mode(), playing, now)
        elif (self.applied == "mute" and self.was_playing and not playing
              and now - self.applied_at < PAUSE_WINDOW):
            log.info("Spotify menjeda iklan yang dibisukan, beralih ke volume kecil")
            self.cfg.update(ads={**self.settings(), "mute_pauses": True})
            self.restore()
            self._apply("quiet", True, now)

    def shutdown(self):
        self.restore()

    def _apply(self, mode, playing, now):
        restore = {}
        try:
            if mode == "mute":
                if not self.backend.set_mute(True):
                    return  # sesi audio Spotify belum ada: coba lagi tick berikutnya
                restore["mute"] = True
            elif mode == "quiet":
                volume = self.backend.get_volume()
                if volume is None:
                    return
                if volume > self.level():
                    self.backend.set_volume(self.level())
                    restore["volume"] = volume
        except OSError as e:
            log.warning("gagal mengatur suara Spotify: %s", e)
            mode = "error"  # jangan dicoba terus selama iklan ini
        if restore:
            self.cfg.update(ad_restore=restore)
        self.applied, self.applied_at, self.was_playing = mode, now, playing

    def restore(self):
        """False kalau belum bisa dipulihkan (Spotify sedang tidak punya sesi audio); dicoba lagi nanti.
        Windows mengingat volume per aplikasi, jadi jangan sampai Spotify tertinggal bisu atau pelan."""
        r = self.cfg.get("ad_restore")
        if not r:
            return True
        try:
            changed = 0
            if r.get("mute"):
                changed += self.backend.set_mute(False)
            if r.get("volume") is not None:
                changed += self.backend.set_volume(r["volume"])
        except OSError as e:
            log.warning("gagal mengembalikan suara Spotify: %s", e)
            changed = 1  # jangan diulang terus
        if not changed:
            return False
        self.cfg.update(ad_restore=None)
        return True


class _Backend:
    set_mute = staticmethod(set_mute)
    get_volume = staticmethod(get_volume)
    set_volume = staticmethod(set_volume)
