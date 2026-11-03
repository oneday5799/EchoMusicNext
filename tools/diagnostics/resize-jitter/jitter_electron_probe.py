"""Move/hold probe against the OLD EchoMusic (Electron) app, D:\\Code\\EchoMusic.

Same method as jitter_fm_probe but attaches to the already-running Electron
window instead of launching the Qt app, and every box sits fully inside the
window at the start rect so growth only ever reveals pixels OUTSIDE the boxes
(no edge-sliver artifact). If the Electron present path never lets DWM stretch
stale frames, all boxes must stay bit-stable through every drag step.
"""
import hashlib
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resize_jitter as rj

# Window starts at (400,150) 1600x1000 -> capture x = screen-340, y = screen-300.
# Window right edge at capture 1660, bottom edge at capture 850; +45px growth.
BOXES = {
    "blue-circle-edge": (1530, 240, 1600, 420),
    "milk-circle-edge": (1020, 240, 1090, 420),
    "girl-circle-edge": (1290, 240, 1335, 420),
    "big-text": (695, 625, 860, 672),
    "label-text": (405, 560, 530, 600),
    "radio-card-text": (405, 270, 585, 322),
    "red-square-cover": (418, 615, 640, 710),
    "sidebar-text": (100, 145, 250, 182),
}
CYCLES = 3
MOVE_PX = 45
HOLD = 1.4


def find_electron_window():
    import ctypes
    import ctypes.wintypes as wintypes
    hwnds = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def on_window(hwnd, _):
        if rj.user32.IsWindowVisible(hwnd):
            n = rj.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            rj.user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value == "EchoMusic":
                hwnds.append(hwnd)
        return True

    rj.user32.EnumWindows(on_window, 0)
    if not hwnds:
        raise RuntimeError("EchoMusic (Electron) window not found")
    return hwnds[0]


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rj.require_dpi_awareness()
    hwnd = find_electron_window()
    rj.user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    rj.user32.MoveWindow(hwnd, rj.WIN_X, rj.WIN_Y, rj.WIN_W, rj.WIN_H, True)
    time.sleep(1.2)
    left, top, right, bottom = rj.window_rect(hwnd)
    print(f"attached hwnd={hwnd} rect=({left},{top},{right},{bottom})")

    origin = time.monotonic()

    def drag_thread():
        time.sleep(1.2)
        for cycle in range(CYCLES):
            l, t, r, b = rj.window_rect(hwnd)
            phases.append((time.monotonic(), "move", cycle))
            rj.drag_bottom_right_corner(r - 4, b - 4, total=MOVE_PX, steps=MOVE_PX)
            phases.append((time.monotonic(), "hold", cycle))
            time.sleep(HOLD)

    threading.Thread(target=drag_thread, daemon=True).start()
    grabber = rj.GdiGrabber(origin, fps=45, duration=16)
    grabber.start()

    rows = []
    prev_hash = {}
    saved = 0
    first_mono = None
    crop_dir = os.path.join(out_dir, "changes")
    while True:
        try:
            item = grabber.frames.get(timeout=0.5)
        except Exception:
            item = None
        if item is None:
            if not grabber.is_alive() and grabber.frames.empty():
                break
            continue
        now, frame = item
        if first_mono is None:
            first_mono = now
            import PIL.Image
            PIL.Image.fromarray(frame).save(os.path.join(out_dir, "reference.png"))
        diffs = {}
        for name, box in BOXES.items():
            x0, y0, x1, y1 = box
            crop = frame[y0:y1, x0:x1]
            digest = hashlib.blake2b(crop.tobytes(), digest_size=8).hexdigest()
            prev = prev_hash.get(name)
            diffs[name] = 0 if prev is None else int(np.abs(
                crop.astype(int) - prev[1].astype(int)).max())
            if prev is None or prev[0] != digest:
                prev_hash[name] = (digest, crop)
                saved += 1
                if saved <= 500:
                    import PIL.Image
                    d = os.path.join(crop_dir, name)
                    os.makedirs(d, exist_ok=True)
                    PIL.Image.fromarray(crop).save(os.path.join(
                        d, f"t{now - first_mono:.3f}-d{diffs[name]}.png"))
        rect = rj.window_rect(hwnd)
        rows.append((now - first_mono, rect, diffs))
    np.savez_compressed(
        os.path.join(out_dir, "probe.npz"),
        times=np.array([r[0] for r in rows]),
        rects=np.array([r[1] for r in rows]),
        **{f"diff-{n}": np.array([r[2][n] for r in rows]) for n in BOXES})
    print(f"frames={len(rows)} saved-crops={saved}")

    rects = np.array([r[1] for r in rows])
    grew = np.diff(rects[:, 2], prepend=rects[0, 2]) > 0
    phase = np.array(["rest"] * len(rows), dtype=object)
    i, n = 0, len(grew)
    while i < n:
        if grew[i]:
            j = i
            while j + 1 < n and (grew[j + 1] or (j + 2 < n and grew[j + 2])):
                j += 1
            phase[max(0, i - 1):j + 3] = "move"
            i = j + 1
        else:
            i += 1
    phase[:8] = "settle"
    print(f"{'box':17s} {'move-chg':>9s} {'move-maxd':>10s} {'rest-chg':>9s} {'rest-maxd':>10s}")
    for name in BOXES:
        d = np.array([r[2][name] for r in rows])
        mv = d[phase == "move"]
        rs = d[phase == "rest"]
        print(f"{name:17s} {int((mv > 0).sum()):9d} {int(mv.max()) if mv.size else 0:10d}"
              f" {int((rs > 0).sum()):9d} {int(rs.max()) if rs.size else 0:10d}")
    width_total = rects[-1, 2] - rects[0, 2]
    print(f"window width grew {width_total}px over the session")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "build/diagnostics/resize-jitter/electron-probe"
    main(out)
