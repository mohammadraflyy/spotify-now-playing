"""Generate assets/icon.ico (lingkaran hijau + not musik). Butuh Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
S = 1024

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.ellipse((24, 24, S - 24, S - 24), fill=(29, 185, 84, 255))
white = (255, 255, 255, 255)
# dua not musik yang tersambung
d.ellipse((250, 600, 450, 760), fill=white)
d.ellipse((580, 540, 780, 700), fill=white)
d.rectangle((410, 280, 450, 690), fill=white)
d.rectangle((740, 220, 780, 630), fill=white)
d.polygon([(410, 280), (780, 220), (780, 320), (410, 380)], fill=white)

OUT.parent.mkdir(exist_ok=True)
img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(f"icon -> {OUT}")
