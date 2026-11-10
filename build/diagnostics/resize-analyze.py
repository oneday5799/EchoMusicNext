# Analyze the stepped-resize captures: the player bar is bottom-anchored, so
# align each frame's crop to the bar origin and test whether the title's ink
# pattern is a rigid whole-row translation (healthy) or redistributes its
# anti-aliasing between rows (phase cycling = the shimmer).
from PIL import Image
import os

d = r"D:\Code\EchoMusicNext\build\diagnostics\resize-frames"
steps = sorted(int(f.split("-")[1].split(".")[0]) for f in os.listdir(d) if f.startswith("step-"))

BAR_H = 110          # 88 logical * 1.25
CROP_X0, CROP_X1 = 80, 360
CROP_DY0, CROP_DY1 = 8, 60   # inside the bar

crops = []
for s in steps:
    img = Image.open(os.path.join(d, f"step-{s:03d}.png")).convert("L")
    w, h = img.size
    bar_top = h - BAR_H
    crop = img.crop((CROP_X0, bar_top + CROP_DY0, CROP_X1, bar_top + CROP_DY1))
    crops.append((s, crop))

# numeric: per-row ink sums, rigid-shift residual between consecutive frames
def profile(crop):
    px = crop.load()
    w, h = crop.size
    rows = []
    for y in range(h):
        rows.append(sum(max(0, 200 - px[x, y]) for x in range(w)))  # ink on light text
    return rows

prev = None
print("step  pair  best-shift  residual(after align)  raw-diff")
for i in range(1, len(crops)):
    s0, c0 = crops[i - 1]
    s1, c1 = crops[i]
    p0, p1 = profile(c0), profile(c1)
    best, bestd = 0, None
    for sh in range(-4, 5):
        a = p0[max(0, sh):len(p0) + min(0, sh)]
        b = p1[max(0, -sh):len(p1) + min(0, -sh)]
        n = min(len(a), len(b))
        diff = sum(abs(a[j] - b[j]) for j in range(n))
        if bestd is None or diff < bestd:
            bestd, best = diff, sh
    raw = sum(abs(p0[j] - p1[j]) for j in range(min(len(p0), len(p1))))
    print(f"{s1:3d}  {s0}->{s1}  shift={best:+d}  residual={bestd:8d}  raw={raw:8d}")

# montage of first 8 crops, 3x upscale for visual inspection
mont = Image.new("L", ((CROP_X1 - CROP_X0) * 3, (CROP_DY1 - CROP_DY0) * 3 * min(8, len(crops)) + 4 * min(8, len(crops))))
y = 0
for s, c in crops[:8]:
    big = c.resize((c.width * 3, c.height * 3), Image.NEAREST)
    mont.paste(big, (0, y))
    y += big.height + 4
mont.save(os.path.join(d, "montage-title.png"))
print("montage saved")
