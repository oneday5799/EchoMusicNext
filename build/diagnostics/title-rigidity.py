# Rigid-shift residual test for the strongest bottom-area text band across
# stepped-resize captures. Parked text keeps its anti-aliasing pattern and can
# only move in whole rows: some integer shift aligns a frame to frame 0 with a
# near-zero residual. Phase cycling (or DWM-stretched captures) redistributes
# gray levels between rows, which no integer shift can align.
import os
import sys

from PIL import Image

d = sys.argv[1]
X0, X1 = int(sys.argv[2]) if len(sys.argv) > 2 else 610, int(sys.argv[3]) if len(sys.argv) > 3 else 860

files = sorted(f for f in os.listdir(d) if f.startswith("step-"))
prof = []
heights = []
for f in files:
    img = Image.open(os.path.join(d, f)).convert("L")
    w, h = img.size
    px = img.load()
    rows = [sum(max(0, 240 - px[x, y]) for x in range(X0, X1)) / (X1 - X0) for y in range(h)]
    prof.append(rows)
    heights.append(h)

# locate the strongest single-line text band in the lower half of frame 0
h0 = heights[0]
best = None
y = int(h0 * 0.6)
while y < h0:
    if prof[0][y] > 10:
        y0 = y
        total = 0.0
        while y < h0 and prof[0][y] > 5:
            total += prof[0][y]
            y += 1
        height = y - y0
        if 8 <= height <= 110 and (best is None or total > best[2]):
            best = (y0, y, total)
    else:
        y += 1
y0, y1, _ = best
pad = 4
W0, W1 = y0 - pad, y1 + pad
print(f"band rows {y0}-{y1} (window {W0}-{W1}), {len(files)} frames")

ref = prof[0][W0:W1]


def com(rows):
    num = den = 0.0
    for i, v in enumerate(rows):
        w = max(0.0, v - 4)
        num += i * w
        den += w
    return num / den if den else float("nan")


print("step  h  shift  residual  com")
for idx in range(len(files)):
    h = heights[idx]
    bestshift, bestres = None, None
    for off in range(W0 - 16, W0 + 17):
        if off < 0 or off + len(ref) > h:
            continue
        cur = prof[idx][off:off + len(ref)]
        r = sum(abs(a - b) for a, b in zip(ref, cur))
        if bestres is None or r < bestres:
            bestshift, bestres = off, r
    cur = prof[idx][bestshift:bestshift + len(ref)]
    c = com(cur) + bestshift
    print(f"{idx:4d} {h:4d}  {bestshift - W0:+3d}  {bestres:8.1f}  {c:8.3f}")
