"""The pixel-art chow chow mascot, drawn as crisp SVG rectangles (no image files needed).

Each sprite is a small grid of letters on a 36 x 32 canvas. "." is transparent. The letters
f, d and l are the three fur shades: they get CSS classes, so the fur colour chosen in Settings
(and its live preview) just works. Every other letter is a fixed colour from PALETTE.
A layer is (x, y, rows): where its top-left corner sits on the canvas.
"""
from markupsafe import Markup

WIDTH, HEIGHT = 36, 32
FUR_LETTERS = {"f": "px-f", "d": "px-d", "l": "px-l"}
PALETTE = {"o": "#3b2314", "c": "#fdf0dc", "n": "#2b2233", "t": "#4a4a8c", "w": "#ffffff",
           "p": "#ff8fa3", "Y": "#ffeb3b", "z": "#8ea0ff"}

# ---------------------------------------------------------------- the art
BODY = (0, 1, [
    "...........oo.......................",
    "...ooooo..ollo.ooo.oooo.............",
    "..offffloollloollloffffo............",
    ".offffffllllllllllffffffo...........",
    ".offddffllllllllllffddffo...........",
    ".ofddddfllllllllllfddddfo...........",
    ".offddffllllllllllffddffo...........",
    "..offffllllllllllllfffflo...........",
    ".oollllllllllllllllllllllo.....oo...",
    "ollllllllllllllllllllllllo....offo..",
    "olllllllllllllllllllllllo....ollffo.",
    "ollllllllllllllllllllllloo..ollllffo",
    ".ollllllllllllllllllllllllo.ollllffo",
    ".ollllllllllllllllllllllllooffllffff",
    "olllllllllllllllllllllllooffffffffff",
    "ollllllllllllllllllllllloffffffffffo",
    "olllllllllcnnncclllllllllofffffffffo",
    ".oolfllllccnnncccllllfllloffffffffo.",
    "..olffllccccncccccllffllofffffffffo.",
    ".olfffflcccccccccclffffoffffffffffo.",
    "..olfffffccccccccfffffofffffffffffo.",
    "...offffffccccccffffffofffffffffffo.",
    "....ooffffffffffffffoodddddfffffffo.",
    ".....ooloffffffffloodddfffffffdfffo.",
    "....offofoollooooodddddfffffffddfo..",
    "....offffffooodddddddddfffffffddo...",
    "....offfffffo.oofddddddfffffffoo....",
    "....olllllllo...ooffffflllllllo.....",
    "....olllllllo.....ooooolllllllo.....",
    ".....ooooooo...........ooooooo......",
])

FACES = {
    "happy": (3, 12, [
        "....wn........wn...",
        "....nn........nn...",
        "....nn........nn...",
        "...................",
        "...................",
        "pp...............pp",
        "pp...............pp",
        "...................",
        "........nnn........",
        "........ttt........",
        "........ttt........",
        "........ttt........",
    ]),
    "cheer": (3, 13, [
        ".....nn........nn..",
        "....n..n......n..n.",
        "...................",
        "...................",
        "pp...............pp",
        "pp...............pp",
        "...................",
        "........nnnn.......",
        "........nttn.......",
        "........nttn.......",
    ]),
    "sleepy": (3, 12, [
        ".......n.........n.",
        "....nnn.......nnn..",
        "...................",
        "...................",
        "...................",
        "pp...............pp",
        "pp...............pp",
        "...................",
        "........n.n........",
        ".........n.........",
    ]),
}

LIDS = (7, 12, [
    "ll........ll",
    "nn........nn",
    "ll........ll",
])   # shown for a moment to make the happy chow chow blink

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

    parts = [_group("px-body", BODY), _group("px-face", FACES[mood])]
    if mood == "happy":
        parts.append(_group("px-lids", LIDS))

    extras = []
    if mood == "cheer":
        extras.append(_group("px-sparkle", (1, 3, SPARKLE)))
        extras.append(_group("px-sparkle px-late", (32, 5, SPARKLE)))
    elif mood == "sleepy":
        extras.append(_group("px-z", (31, 3, Z_BIG)))
        extras.append(_group("px-z px-late", (33, 0, Z_SMALL)))

    width = round(size * WIDTH / HEIGHT)
    return Markup(
        f'<svg class="pixel px-{mood}" viewBox="0 0 {WIDTH} {HEIGHT}" width="{width}" height="{size}" '
        f'shape-rendering="crispEdges" role="img" aria-label="Pixel chow chow mascot">'
        f'<g class="px-bob">{"".join(parts)}</g>{"".join(extras)}</svg>'
    )