"""Pastikan setiap teks di halaman pengaturan punya terjemahan bahasa Inggris."""

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "spotify_now_playing" / "web"

# nama produk / istilah OBS & Spotify yang memang tidak diterjemahkan
SAME = {
    "Spotify Now Playing", "Spotify Now Playing v", "ID", "EN", "Bahasa / Language", "Download", "GitHub",
    "Sources → + → Browser", "Sources", "Browser", "OK", "URL", "Ctrl+V", "Width", "Height", "Properties",
    "Refresh cache of current page", "px", "LRCLIB", "Spotify App", "Spotify Developer Dashboard",
    "Create app", "Premium", "Web API", "Redirect URIs", "Add", "Save", "Settings → User Management",
    "Client ID", "Redirect URI", "Client Secret", "Text (GDI+)", "Read from file", "Image",
    "{artist} - {title}", "Streamer.bot", "Core → Network → Fetch URL", "Twitch/YouTube → Send Message",
}


def en_keys():
    js = (WEB / "i18n.js").read_text(encoding="utf-8")
    body = js[js.index("const EN = {"):js.index("};", js.index("const EN = {"))]
    return {json.loads(m) for m in re.findall(r'^\s*("(?:[^"\\]|\\.)*"):', body, re.M)}


class TextCollector(HTMLParser):
    SKIP = {"script", "style", "svg", "code"}

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.found = set()
        self.has_own = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        attrs = dict(attrs)
        self.has_own = "data-en" in attrs
        for name in ("placeholder", "title"):
            if attrs.get(name):
                self.found.add(attrs[name])

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.depth -= 1

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data).strip()
        if not self.depth and not self.has_own and re.search(r"[A-Za-z]", text):
            self.found.add(text)
        self.has_own = False


class I18nTest(unittest.TestCase):
    def setUp(self):
        self.html = (WEB / "settings.html").read_text(encoding="utf-8")
        self.keys = en_keys()

    def test_static_text_translated(self):
        start = self.html.index("<body>")
        p = TextCollector()
        p.feed(self.html[start:self.html.index("<script>", start)])
        missing = sorted(p.found - self.keys - SAME)
        self.assertEqual(missing, [], "teks tanpa terjemahan di i18n.js")

    def test_script_text_translated(self):
        script = self.html[self.html.rindex("<script>"):]
        literals = set()
        for call in ("t", "toast", "confirm", "prompt"):
            for m in re.finditer(rf'\b{call}\(\s*(["\'`])((?:(?!\1)[^\\]|\\.)*)\1', script):
                if "${" not in m.group(2):
                    literals.add(m.group(2).replace('\\"', '"').replace("\\'", "'"))
        missing = sorted(lit for lit in literals - self.keys if re.search(r"[a-z]{3}", lit))
        self.assertEqual(missing, [], "string di script tanpa terjemahan di i18n.js")


if __name__ == "__main__":
    unittest.main()
