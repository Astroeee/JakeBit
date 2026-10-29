"""Small pixel-art nature scenes for the dashboard (drawn as SVG rectangles, no image files).

Each scene reacts to one number from the user's habits:
  mountain(streak)       a flag climbs the mountain as the best streak grows
  park(percent)          more flowers bloom as today's progress goes up
  forest(completions)    a new tree grows for every 8 habit check-ins
Anything unexpected falls back to a sensible default, so a bad value can never break a page.
"""
import math

from markupsafe import Markup

W, H = 48, 24
C = {
    "sky": "#8fd3ff", "sky2": "#bde8ff", "sun": "#ffe066", "cloud": "#ffffff",
    "far": "#8ea4c9", "near": "#6479a6", "shade": "#566a96", "snow": "#ffffff",
    "grass": "#6cc24a", "grass2": "#4fa83d", "trunk": "#8b5a2b", "leaf": "#3c9d4e", "leaf2": "#2f8744",
    "path": "#e8cf9a", "stem": "#3f8f3a", "flag": "#e5484d", "pole": "#5b3a29",
    "dusk": "#3a3f7a", "dusk2": "#5a5fa3", "moon": "#fff3c4", "hill": "#2c3568",
    "ground": "#2e6b3e", "ground2": "#255a33", "water": "#3d6fb5", "wave": "#6fa0e0",
    "pine": "#2f8f4e", "pine2": "#237a3f", "star": "#ffffff",
}
PETALS = ["#ff6b8b", "#ffd23f", "#b388ff", "#ff9f43", "#ff6b8b", "#5ec8ff"]
LABELS = {"mountain": "Pixel mountain with a flag", "park": "Pixel park with flowers",
          "forest": "Pixel forest by a lake"}


class Grid:
    def __init__(self):
        self.px = [[None] * W for _ in range(H)]

    def set(self, x, y, color):
        x, y = int(x), int(y)
        if 0 <= x < W and 0 <= y < H:
            self.px[y][x] = color

    def rect(self, x, y, w, h, color):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, color)

    def disc(self, cx, cy, r, color):
        for yy in range(cy - r, cy + r + 1):
            for xx in range(cx - r, cx + r + 1):
                if (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r + 1:
                    self.set(xx, yy, color)

    def svg(self, kind, extra=""):
        out = []
        for y, row in enumerate(self.px):
            x = 0
            while x < W:
                color = row[x]
                if color is None:
                    x += 1
                    continue
                end = x
                while end + 1 < W and row[end + 1] == color:
                    end += 1
                out.append(f'<rect x="{x}" y="{y}" width="{end - x + 1}" height="1" fill="{color}"/>')
                x = end + 1
        return Markup(
            f'<svg class="pixel scene" viewBox="0 0 {W} {H}" shape-rendering="crispEdges" role="img" '
            f'aria-label="{LABELS[kind]}">{"".join(out)}{extra}</svg>'
        )


def _sky(g, top, bottom, split=12):
    for y in range(H):
        g.rect(0, y, W, 1, top if y < split else bottom)


def _pine(g, x, base, height, colors=("pine", "pine2")):
    """A little pine tree: a trunk and a triangle of leaves, `base` is the ground row."""
    top = base - 1 - height
    for i in range(height):
        g.rect(x - i, top + i, 2 * i + 1, 1, C[colors[i % 2]])
    g.rect(x, base - 1, 1, 2, C["trunk"])


def _mountain(value):
    g = Grid()
    _sky(g, C["sky"], C["sky2"])
    g.disc(6, 5, 2, C["sun"])

    def ridge(peak_x, peak_y, slope, color, snow=0):
        for x in range(W):
            top = int(peak_y + abs(x - peak_x) * slope)
            for y in range(top, 20):
                shade = x > peak_x and color == C["near"]
                g.set(x, y, C["shade"] if shade else color)
                if snow and y < peak_y + snow:
                    g.set(x, y, C["snow"])
    ridge(12, 9, 1.0, C["far"], snow=2)
    ridge(38, 7, 1.0, C["far"], snow=2)
    ridge(28, 4, 0.9, C["near"], snow=3)
    g.rect(0, 19, W, 5, C["grass"])
    g.rect(0, 19, W, 1, C["grass2"])
    for x, h in ((3, 4), (8, 3), (42, 4), (46, 3)):
        _pine(g, x, 21 if h == 3 else 22, h)

    level = sum(1 for t in (1, 3, 7, 14, 30) if value >= t)        # 0..5
    fx = (13, 16, 19, 22, 25, 28)[level]
    surface = int(4 + abs(fx - 28) * 0.9)
    g.rect(fx, surface - 5, 1, 5, C["pole"])
    g.rect(fx + 1, surface - 5, 2, 2, C["flag"])
    return g.svg("mountain")


def _park(value):
    g = Grid()
    _sky(g, C["sky"], C["sky2"], 10)
    g.disc(43, 4, 2, C["sun"])
    g.rect(6, 4, 7, 2, C["cloud"]); g.rect(8, 3, 3, 1, C["cloud"])
    g.rect(24, 6, 6, 2, C["cloud"]); g.rect(26, 5, 3, 1, C["cloud"])
    for x in range(W):
        top = 14 + int(2 * abs(math.sin(x / 7)))
        g.rect(x, top, 1, H - top, C["grass"])
        g.set(x, top, C["grass2"])
    for y in range(15, H):                                         # a winding path
        half = 1 + (y - 15) // 2
        g.rect(24 - half + int(2 * math.sin(y / 2)), y, 2 * half, 1, C["path"])
    for tx, ty in ((9, 10), (37, 11)):                             # round trees
        g.rect(tx, ty + 2, 2, 5, C["trunk"])
        g.disc(tx, ty, 3, C["leaf"]); g.disc(tx + 1, ty - 1, 2, C["leaf2"])
    spots = [(4, 20), (13, 21), (18, 19), (31, 19), (37, 21), (45, 20)]
    bloom = min(len(spots), max(0, round(value / 100 * len(spots))))
    for i, (x, y) in enumerate(spots):
        if i < bloom:
            g.set(x, y + 1, C["stem"]); g.set(x, y + 2, C["stem"])
            for dx, dy in ((-1, 0), (1, 0), (0, -1)):
                g.set(x + dx, y + dy, PETALS[i])
            g.set(x, y, C["sun"])
        else:
            g.set(x, y, C["stem"])
    return g.svg("park")


def _forest(value):
    g = Grid()
    _sky(g, C["dusk"], C["dusk2"], 9)
    g.disc(39, 5, 2, C["moon"])
    for x in range(W):
        g.rect(x, 12 + int(2 * abs(math.sin(x / 6))), 1, 6, C["hill"])
    g.rect(0, 18, W, 6, C["ground"])
    g.rect(0, 18, W, 1, C["ground2"])
    g.rect(16, 19, 17, 5, C["water"])
    for x, y in ((18, 20), (19, 20), (24, 22), (25, 22), (29, 20), (30, 20), (21, 23), (27, 23)):
        g.set(x, y, C["wave"])
    g.rect(39, 20, 2, 1, C["moon"])                                # moon glitter on the water edge
    slots = [(4, 6), (9, 4), (13, 5), (36, 5), (40, 4), (44, 6)]
    trees = min(len(slots), value // 8)
    for i, (x, h) in enumerate(slots):
        if i < trees:
            _pine(g, x, 21, h)
        else:
            g.set(x, 20, C["pine"])                                # a sapling waiting to grow
    stars = lambda pts: "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{C["star"]}"/>' for x, y in pts)
    extra = (f'<g class="px-sparkle">{stars([(5, 2), (20, 3), (31, 1), (44, 8)])}</g>'
             f'<g class="px-sparkle px-late">{stars([(12, 5), (26, 2), (35, 6), (2, 8)])}</g>')
    return g.svg("forest", extra)


_SCENES = {"mountain": _mountain, "park": _park, "forest": _forest}


def render_scene(kind="mountain", value=0):
    """Return the scene as an inline SVG. `value` is the number that scene reacts to (see top)."""
    try:
        value = max(0, int(value))
    except (TypeError, ValueError):
        value = 0
    return _SCENES.get(kind, _mountain)(value)
