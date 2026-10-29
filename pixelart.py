"""The pixel-art chow chow mascot, drawn as crisp SVG rectangles (no image files needed).

A fluffy side-view chow chow: big round light head, golden body, curled tail.
Each sprite is a grid of letters on a 42 x 36 canvas. "." is transparent. The letters
f, d and l are the three fur shades: they get CSS classes, so the fur colour chosen in Settings
(and its live preview) just works. Every other letter is a fixed colour from PALETTE.
A layer is (x, y, rows): where its top-left corner sits on the canvas.
"""
from markupsafe import Markup

WIDTH, HEIGHT = 42, 36
FUR_LETTERS = {"f": "px-f", "d": "px-d", "l": "px-l"}
PALETTE = {"o": "#3b2314", "c": "#fdf0dc", "n": "#2b2233", "t": "#4a4a8c", "w": "#ffffff",
           "p": "#ff8fa3", "Y": "#ffeb3b", "z": "#8ea0ff"}

# ---------------------------------------------------------------- the art
BODY = (2, 3, [
    "....oooooooooooooo....................",
    "...ollllllllllllllo...................",
    "..ollllllllllllllllo..................",
    ".ollllllllllllllllllo.................",
    "olldddddllllllldddddlo................",
    "oldlllllllllllllllldllooooo...........",
    "oldlllllllllllllllldllfffffooooooo....",
    "oldlllllllllllllllldllffffffllllllo...",
    "oldlllllllllllllllldllfffffffllllllo..",
    "olldllllldllldlllldlllffffffflllllllo.",
    "olllllllldllldllllllllfffffffflllllllo",
    "olllllllllllllllllllllfffffffffllllllo",
    "olllllddlllllllddlllllffdffffffllllllo",
    "olllllllllllllllllllllfffdfdfffflllllo",
    "ollllllllfffffllllllllffffdffffffllllo",
    "olllllllffffffflllllllffffffffffffllo.",
    "olllllllffffffflllllllfffffffffffffo..",
    "olllllllfffffffllllllffffffffffffffo..",
    "ollllllllffffflllllllffffffffffffffo..",
    ".ollllllllllllllllllfffffffffffffffo..",
    "..ollllllllllllllllffffffffffffffdfo..",
    "...ollllllllllllllfffffffffffffffdfo..",
    "....ooffffffffffffffffffffdfffdffffo..",
    "......offffffffffffffffffffdfffdfffo..",
    ".......offfffffffffffffffdfffffffffo..",
    "........offffffffffffffffffffffffffo..",
    ".........offfffffffffffffffffffffffo..",
    "..........offfffffffoodffffffffffffo..",
    ".........olllllllllo...olllllfffffo...",
    "........olllllllllo....olllllffffo....",
    "........ollllllllo......ollllffffo....",
    "........oooooooooo......ooooooooo.....",
])

# A face is a list of layers drawn on top of the big round head.
_NOSE = (12, 17, ["nnn", ".n."])
_BLUSH = [(7, 17, ["pp"]), (18, 17, ["pp"])]
FACES = {
    "happy": [
        (10, 14, ["wn...wn", "nn...nn", "nn...nn"]),      # eyes
        (12, 17, ["nnn", ".n.", ".n.", "n.n"]),           # nose and a little smile
    ] + _BLUSH,
    "cheer": [
        (9, 14, [".n.....n.", "n.n...n.n"]),             # happy ^ ^ eyes
        _NOSE,
        (11, 19, ["nnnnn", "npppn", ".nnn."]),            # open mouth with tongue
    ] + _BLUSH,
    "sleepy": [
        (10, 15, ["nn...nn"]),                            # closed eyes
        _NOSE,
        (12, 19, [".n."]),
    ],
}

LIDS = (10, 14, ["ll...ll", "ll...ll", "nn...nn"])   # shown for a moment so the happy dog blinks

SPARKLE = [".Y.", "YYY", ".Y."]
Z_BIG = ["zzzz", "..z.", ".z..", "zzzz"]
Z_SMALL = ["zzz", ".z.", "zzz"]


# ---------------------------------------------------------------- drawing
def _rects(layer):
    """Turn a layer into SVG <rect>s, merging each horizontal run of one colour into one rect."""
    x0, y0, rows = layer
    out = []
    for dy, row in enumerate(rows):
        x = 0
        while x < len(row):
            ch = row[x]
            if ch == ".":
                x += 1
                continue
            end = x
            while end + 1 < len(row) and row[end + 1] == ch:
                end += 1
            paint = f'class="{FUR_LETTERS[ch]}"' if ch in FUR_LETTERS else f'fill="{PALETTE[ch]}"'
            out.append(f'<rect x="{x0 + x}" y="{y0 + dy}" width="{end - x + 1}" height="1" {paint}/>')
            x = end + 1
    return "".join(out)


def _group(cls, layer):
    return f'<g class="{cls}">{_rects(layer)}</g>'


def render_mascot(mood="happy", size=240):
    """Return the chow chow as an inline SVG. mood: 'happy', 'cheer' or 'sleepy'; size = height in px.
    Anything unexpected falls back to a sensible default, so a bad value can never break a page.
    The CSS in style.css makes the parts move (bobbing, blinking, sparkles, floating zzz)."""
    if mood not in FACES:
        mood = "happy"
    try:
        size = min(max(int(size), 32), 1024)
    except (TypeError, ValueError):
        size = 240

    face = "".join(_rects(layer) for layer in FACES[mood])
    parts = [_group("px-body", BODY), f'<g class="px-face">{face}</g>']
    if mood == "happy":
        parts.append(_group("px-lids", LIDS))

    extras = []
    if mood == "cheer":
        extras.append(_group("px-sparkle", (0, 0, SPARKLE)))
        extras.append(_group("px-sparkle px-late", (37, 2, SPARKLE)))
    elif mood == "sleepy":
        extras.append(_group("px-z", (35, 2, Z_BIG)))
        extras.append(_group("px-z px-late", (39, 0, Z_SMALL)))

    width = round(size * WIDTH / HEIGHT)
    return Markup(
        f'<svg class="pixel px-{mood}" viewBox="0 0 {WIDTH} {HEIGHT}" width="{width}" height="{size}" '
        f'shape-rendering="crispEdges" role="img" aria-label="Pixel chow chow mascot">'
        f'<g class="px-bob">{"".join(parts)}</g>{"".join(extras)}</svg>'
    )