"""Jitter census: find every on-screen element whose pixels really move.

Captures full frames while the window is idle and while a 1 px-step drag
grows it, then accumulates an absolute frame-to-frame difference map. Idle
animation shows up in both maps; a hotspot that exists only in the drag map
is resize-coupled jitter. Clusters in the drag-only map are the elements to
inspect (crop PNGs are saved for each cluster).
"""
import ctypes
import ctypes.wintypes
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resize_jitter as rj


def accumulate(grabber, stop_at):
    """Consume frames until stop_at; return (change-count map, last frame)."""
    counts = None
    prev = None
    last = None
    while True:
        try:
            item = grabber.frames.get(timeout=0.5)
        except Exception:
            item = None
        if item is None:
            if not grabber.is_alive() and grabber.frames.empty():
                break
            continue
        _, frame = item
        last = frame
        if prev is not None:
            diff = np.abs(frame.astype(int) - prev.astype(int)) > 6
            if counts is None:
                counts = diff.astype(np.uint32)
            else:
                counts += diff
        prev = frame
        if time.monotonic() >= stop_at:
            break
    return counts, last


def clusters(counts, threshold):
    """Crude connected components on the boolean activity map."""
    mask = counts >= threshold
    labels = np.zeros(mask.shape, np.int32)
    current = 0
    stack = []
    # downsample by 4 to keep labeling cheap
    small = mask[::4, ::4]
    lab = np.zeros(small.shape, np.int32)
    for y in range(small.shape[0]):
        for x in range(small.shape[1]):
            if small[y, x] and lab[y, x] == 0:
                current += 1
                stack.append((y, x))
                lab[y, x] = current
                while stack:
                    cy, cx = stack.pop()
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if (0 <= ny < small.shape[0] and 0 <= nx < small.shape[1]
                                    and small[ny, nx] and lab[ny, nx] == 0):
                                lab[ny, nx] = current
                                stack.append((ny, nx))
    out = []
    for value in range(1, current + 1):
        ys, xs = np.nonzero(lab == value)
        if len(ys) < 8:  # ignore specks
            continue
        out.append((int(xs.min() * 4), int(ys.min() * 4),
                    int(xs.max() * 4) + 4, int(ys.max() * 4) + 4,
                    int(counts[ys.min() * 4:ys.max() * 4 + 4,
                               xs.min() * 4:xs.max() * 4 + 4].sum())))
    out.sort(key=lambda c: -c[4])
    return out


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rj.require_dpi_awareness()
    proc, log = rj.launch_app({"ECHO_RENDER_DIAGNOSTICS": "1"})
    try:
        hwnd = rj.find_app_window()
        rj.user32.ShowWindow(hwnd, 0x9)
        time.sleep(0.4)
        rj.user32.MoveWindow(hwnd, rj.WIN_X, rj.WIN_Y, rj.WIN_W, rj.WIN_H, True)
        time.sleep(0.8)
        with rj.Blackout() as blackout:
            blackout.place_below(hwnd)
            time.sleep(0.3)

            origin = time.monotonic()
            idle_grab = rj.GdiGrabber(origin, fps=45, duration=4.5)
            idle_grab.start()
            idle_counts, frame = accumulate(idle_grab, origin + 4.5)
            from PIL import Image
            Image.fromarray(frame).save(os.path.join(out_dir, "idle-frame.png"))

            # one 231-step grow drag, 1 px per step — run it while the
            # grabber is consuming, otherwise only the aftermath is captured
            import threading
            left, top, right, bottom = rj.window_rect(hwnd)
            drag_done = threading.Event()

            def drag():
                rj.drag_bottom_right_corner(right - 4, bottom - 4)
                drag_done.set()

            threading.Thread(target=drag, daemon=True).start()
            drag_origin = time.monotonic()
            drag_grab = rj.GdiGrabber(drag_origin, fps=45, duration=5.5)
            drag_grab.start()
            drag_counts, frame = accumulate(drag_grab, drag_origin + 5.5)
            Image.fromarray(frame).save(os.path.join(out_dir, "drag-end-frame.png"))

            only_drag = drag_counts.astype(np.int64) - (
                idle_counts.astype(np.int64) if idle_counts is not None else 0)
            np.savez_compressed(os.path.join(out_dir, "census.npz"),
                                drag=drag_counts, idle=idle_counts)
            print("idle active px:", int((idle_counts > 0).sum()) if idle_counts is not None else "n/a")
            print("drag active px:", int((drag_counts > 0).sum()))
            print("drag-only active px:", int((only_drag > 0).sum()))
            hot = clusters(np.maximum(only_drag, 0), threshold=12)
            print("drag-only clusters (x0,y0,x1,y1,activity):")
            for c in hot[:14]:
                print("  ", c)
                pad = 24
                x0, y0, x1, y1 = max(0, c[0] - pad), max(0, c[1] - pad), \
                    min(frame.shape[1], c[2] + pad), min(frame.shape[0], c[3] + pad)
                Image.fromarray(frame[y0:y1, x0:x1]).save(
                    os.path.join(out_dir, f"cluster-{c[0]}-{c[1]}.png"))
    finally:
        log.close()
        import subprocess
        subprocess.run(["taskkill", "/F", "/IM", "echomusicnext.exe"], capture_output=True)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        rj.DEFAULT_OUT, "census")
    main(out)
