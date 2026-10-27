"""README banner: a cairn of page-stones at dusk, plus the wordmark. Hand-built pixel art.

Regenerate: python docs/assets/banner.py docs/assets/banner.svg
"""
import math
import sys

W, H = 160, 40
px = [[None] * W for _ in range(H)]


def put(x, y, c):
    if 0 <= x < W and 0 <= y < H:
        px[y][x] = c


# --- sky: dusk bands, dithered at each boundary
bands = [(0, "#1b1a36"), (7, "#2a2350"), (13, "#45305f"), (19, "#6e3f68"),
         (24, "#a3546a"), (28, "#d47a5e"), (31, "#eda66a")]
for y in range(H):
    for x in range(W):
        c = bands[0][1]
        for i, (start, col) in enumerate(bands):
            if y >= start:
                c = col
                # one dithered row just above each boundary
            if i + 1 < len(bands) and y == bands[i + 1][0] - 1 and (x + y) % 2 == 0:
                c = bands[i + 1][1] if y >= start else c
        px[y][x] = c

# stars
for x, y in [(8, 2), (23, 5), (41, 1), (57, 4), (72, 2), (96, 1), (118, 3), (137, 2),
             (151, 6), (128, 9), (12, 10), (104, 7)]:
    if 60 <= x <= 156 and 4 <= y <= 26:
        continue  # keep the wordmark clear of stray dots
    put(x, y, "#f4e9d0" if (x * 7 + y) % 3 else "#9d93c2")

# --- far mountains, near hills
for x in range(W):
    far = int(27 + 3 * math.sin(x / 11.0) + 2 * math.sin(x / 4.3 + 1.0))
    for y in range(far, H):
        put(x, y, "#4a3560")
    near = int(31 + 2 * math.sin(x / 17.0 + 2.0) + math.sin(x / 6.1))
    for y in range(near, H):
        put(x, y, "#2c2443")

# --- ground
GROUND = 34
for x in range(W):
    for y in range(GROUND, H):
        put(x, y, "#1d2a2c" if y > GROUND else "#2b4038")
for x in range(0, W, 5):
    if (x * 13) % 7 < 3:
        put(x, GROUND - 1, "#2b4038")
        put(x + 1, GROUND - 1, "#3d5a48")

# --- cairn: stacked stones that are also pages (folded top-right corner)
OUT = "#221d2e"
WARM = "#eab184"  # rim light from the setting sun (right side)
# palettes per stone: (highlight, mid, shadow, writing) -- cool and warm greys alternate
COOL = ("#c9c6d2", "#9894a6", "#64607a", "#7c788f")
WARMG = ("#d2c7bd", "#a2968c", "#6d6262", "#867a74")
# (width, height, x offset, superellipse exponent, palette, lines of "writing")
stones = [(31, 9, 0, 3.4, COOL, 2), (25, 7, 2, 3.2, WARMG, 2), (20, 6, -1, 2.4, COOL, 1),
          (15, 5, 1, 2.8, WARMG, 1), (10, 4, -1, 2.2, COOL, 1), (6, 3, 0, 2.0, WARMG, 0)]
cx, base = 29, GROUND
for si, (w, h, off, p, (HI, MID, LO, INK), lines) in enumerate(stones):
    x0 = cx - w // 2 + off
    y0 = base - h + 1 if si else base - h  # stones settle into each other by a pixel
    rx, ry = w / 2, h / 2
    mask = set()
    for yy in range(h):
        for xx in range(w):
            nx = abs((xx + 0.5 - rx) / rx)
            ny = abs((yy + 0.5 - ry) / ry)
            if nx ** p + ny ** p <= 1.0:
                mask.add((xx, yy))
    for xx, yy in mask:
        n_out = [(xx + dx, yy + dy) not in mask for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        if any(n_out):
            c = OUT
        elif (xx, yy - 2) not in mask:
            c = HI  # top face catches the sky
        elif (xx, yy + 2) not in mask:
            c = LO
        elif (xx + 2, yy) not in mask:
            c = WARM
        else:
            c = MID
        put(x0 + xx, y0 + yy, c)
    # faint "writing" on the face: dashes like lines of a markdown page
    face = [y for y in range(h) if all((x, y) in mask and (x, y - 2) in mask and (x, y + 2) in mask
                                       for x in range(int(rx) - 1, int(rx) + 1))]
    for k, y in enumerate(face[:lines]):
        xs = [x for x in range(w) if (x - 3, y) in mask and (x + 4, y) in mask]
        if not xs:
            continue
        x = xs[0]
        run = 0
        while x <= xs[-1]:
            # word lengths vary deterministically; short gap between words; 2nd line shorter
            wl = 2 + (x * 7 + y * 3 + si) % 4
            for i in range(wl):
                if x + i <= xs[-1] - (4 if k else 0):
                    put(x0 + x + i, y0 + y, INK)
            x += wl + 1
    base = y0

# fill any holes the fold pass cleared with the sky colour beneath (redo sky lookup)
def sky_at(y):
    c = bands[0][1]
    for start, col in bands:
        if y >= start:
            c = col
    return c


for y in range(H):
    for x in range(W):
        if px[y][x] is None:
            px[y][x] = sky_at(y)

# --- wordmark: 5x9 lowercase glyphs at 2x
GLYPHS = {
    "r": [".....", ".....", "#.##.", "##..#", "#....", "#....", "#....", ".....", "....."],
    "e": [".....", ".....", ".###.", "#...#", "#####", "#....", ".###.", ".....", "....."],
    "q": [".....", ".....", ".####", "#...#", "#...#", "#...#", ".####", "....#", "....#"],
    "l": [".##..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###.", ".....", "....."],
    "i": ["..#..", ".....", ".##..", "..#..", "..#..", "..#..", ".###.", ".....", "....."],
    "t": [".#...", ".#...", "####.", ".#...", ".#...", ".#..#", "..##.", ".....", "....."],
}
TX, TY, S = 64, 5, 2
for n, ch in enumerate("reqlite"):
    for gy, row in enumerate(GLYPHS[ch]):
        for gx, bit in enumerate(row):
            if bit == "#":
                for sy in range(S):
                    for sx in range(S):
                        x, y = TX + n * 12 + gx * S + sx, TY + gy * S + sy
                        put(x + 1, y + 1, "#16132a")  # drop shadow
            if bit == "#":
                for sy in range(S):
                    for sx in range(S):
                        put(TX + n * 12 + gx * S + sx, TY + gy * S + sy, "#f6e7c6")

# --- tagline: 3x5 glyphs at 1x
SMALL = {
    "t": ["###", ".#.", ".#.", ".#.", ".#."], "h": ["#.#", "#.#", "###", "#.#", "#.#"],
    "e": ["###", "#..", "##.", "#..", "###"], "f": ["###", "#..", "##.", "#..", "#.."],
    "i": ["###", ".#.", ".#.", ".#.", "###"], "l": ["#..", "#..", "#..", "#..", "###"],
    "s": [".##", "#..", ".#.", "..#", "##."], "a": [".#.", "#.#", "###", "#.#", "#.#"],
    "r": ["##.", "#.#", "##.", "#.#", "#.#"], "y": ["#.#", "#.#", ".#.", ".#.", ".#."],
    "m": ["#...#", "##.##", "#.#.#", "#...#", "#...#"], " ": ["..", "..", "..", "..", ".."],
    ".": ["#", ".", ".", ".", "."][::-1],
}
tag = "the files are the system."
tw = sum(len(SMALL[ch][0]) + 1 for ch in tag) - 1
sx = TX + (7 * 12 - 2 - tw) // 2
for ch in tag:
    for gy, row in enumerate(SMALL[ch]):
        for gx, bit in enumerate(row):
            if bit == "#":
                put(sx + gx + 1, 28 + gy + 1, "#2c2443")
                put(sx + gx, 28 + gy, "#f2c9a0")
    sx += len(SMALL[ch][0]) + 1

# --- emit SVG, merging horizontal runs
out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
       f'width="{W * 5}" height="{H * 5}" shape-rendering="crispEdges" '
       f'role="img" aria-label="reqlite: a cairn of stacked page-stones at dusk">']
for y in range(H):
    x = 0
    while x < W:
        c = px[y][x]
        x1 = x
        while x1 < W and px[y][x1] == c:
            x1 += 1
        out.append(f'<rect x="{x}" y="{y}" width="{x1 - x}" height="1" fill="{c}"/>')
        x = x1
out.append("</svg>")
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(out) + "\n")
