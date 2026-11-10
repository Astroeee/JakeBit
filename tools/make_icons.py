"""Draws the app icons (the pixel chow chow on the accent colour) into public/static/icons.
Run from the project folder:  python tools/make_icons.py"""
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pixelart  # noqa: E402

FUR = {"f": "#fdd699", "d": "#f7c27a", "l": "#fae6c4"}
ACCENT = "#c32f0c"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "static", "icons")


def sprite():
    """The happy chow chow as a dict {(x, y): '#rrggbb'}."""
    colors = {**pixelart.PALETTE, **FUR}
    pixels = {}
    for x0, y0, rows in [pixelart.BODY] + list(pixelart.FACES["happy"]):
        for dy, row in enumerate(rows):
            for dx, letter in enumerate(row):
                if letter != ".":
                    pixels[(x0 + dx, y0 + dy)] = colors[letter]
    return pixels


def icon(size, scale, rounded, path):
    px = sprite()
    xs, ys = [p[0] for p in px], [p[1] for p in px]
    left, top = min(xs), min(ys)
    width, height = (max(xs) - left + 1) * scale, (max(ys) - top + 1) * scale
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if rounded:
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=ACCENT)
    else:
        draw.rectangle([0, 0, size - 1, size - 1], fill=ACCENT)        # full bleed: the phone rounds it
    ox, oy = (size - width) // 2, (size - height) // 2
    for (x, y), colour in px.items():
        px0, py0 = ox + (x - left) * scale, oy + (y - top) * scale
        draw.rectangle([px0, py0, px0 + scale - 1, py0 + scale - 1], fill=colour)
    image.save(os.path.join(OUT, path))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    icon(192, 3, True, "icon-192.png")
    icon(512, 8, True, "icon-512.png")
    icon(512, 7, False, "icon-maskable-512.png")       # sprite stays inside the safe zone
    icon(180, 3, False, "apple-touch-icon.png")
    icon(48, 1, True, "favicon-48.png")
    print("icons written to", OUT)
