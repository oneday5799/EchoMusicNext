# Subpixel phase analysis for stepped-resize captures: per text band, the
# ink-weighted center of mass per frame. Parked rendering (whole-device-pixel
# positions) keeps the fractional part of a tracked band's COM constant across
# steps; unparked relayout cycles it through the DPR phase lattice.
import os
import sys

from PIL import Image

d = sys.argv[1] if len(sys.argv) > 1 else r"D:\Code\EchoMusicNext\build\diagnostics\resize-frames"
X0, X1 = int(sys.argv[2]) if len(sys.argv) > 2 else 420, int(sys.argv[3]) if len(sys.argv) > 3 else 660
BG = 240.0          # light theme background level
INK = 60.0          # ink level
THRESH = 6.0        # per-row mean ink to count as a text row

files = sorted(f for f in os.listdir(d) if f.startswith("step-"))
frames = []
for f in files:
    img = Image.open(os.path.join(d, f)).convert("L")
    px = img.load()
    w, h = img.size
    ink = [0.0] * h
    for y in range(h):
        s = 0.0
        for x in range(X0, X1):
            v = BG - px[x, y]
            s += v if v > 0 else 0.0
        ink[y] = s / (X1 - X0)
    frames.append((f, w, h, ink))


def bands(ink, h):
    out = []
    y = 0
    while y < h:
        if ink[y] > THRESH:
            y0 = y
            while y < h and ink[y] > THRESH * 0.5:
                y += 1
            out.append((y0, y))
        else:
            y += 1
    return out


def com(ink, y0, y1, margin=3):
    # ink-weighted center of mass with a small guard band against neighbors
    a, b = max(0, y0 - margin), min(len(ink), y1 + margin)
    num = den = 0.0
    for y in range(a, b):
        w = max(0.0, ink[y] - THRESH * 0.25)
        num += y * w
        den += w
    return num / den if den > 0 else float("nan")


# reference bands from the first frame; track nearest band in later frames
ref = bands(frames[0][3], frames[0][2])
ref = [b for b in ref if b[1] - b[0] >= 4][:14]
print(f"{len(frames)} frames, {len(ref)} tracked bands, region x {X0}-{X1}")
header = "step h  " + "  ".join(f"band{i}@{ref[i][0]}" for i in range(len(ref)))
print(header)
for idx, (f, w, h, ink) in enumerate(frames):
    cur = bands(ink, h)
    cells = []
    for (r0, r1) in ref:
        # band center drifts with relayout; pick the current band whose center
        # is nearest to the reference band's original center
        target = (r0 + r1) / 2
        best, bestd = None, 1e9
        for (c0, c1) in cur:
            dist = abs((c0 + c1) / 2 - target)
            if dist < bestd:
                best, bestd = (c0, c1), dist
        if best is None or bestd > 24:
            cells.append("  ----  ")
            continue
        c = com(ink, best[0], best[1])
        cells.append(f"{c:7.2f}")
    print(f"{idx:2d} {h:4d}  " + "  ".join(cells))
