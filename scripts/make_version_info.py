"""Tulis build/version_info.txt untuk PyInstaller (--version-file).

Exe dengan info versi lengkap (perusahaan, deskripsi, versi) lebih jarang
dicurigai antivirus dibanding exe tanpa identitas.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from spotify_now_playing import APP_NAME, __version__  # noqa: E402

PUBLISHER = "mohammadrafly"
parts = [int(p) for p in __version__.split(".")] + [0] * 4
v = tuple(parts[:4])

TEMPLATE = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{PUBLISHER}'),
      StringStruct('FileDescription', '{APP_NAME} untuk OBS'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'SpotifyNowPlaying'),
      StringStruct('LegalCopyright', 'Copyright (c) {PUBLISHER}'),
      StringStruct('OriginalFilename', 'SpotifyNowPlaying.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

out = ROOT / "build" / "version_info.txt"
out.parent.mkdir(exist_ok=True)
out.write_text(TEMPLATE, encoding="utf-8")
print(f"version info -> {out}")
