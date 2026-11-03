"""Second census pass: classify each hotspot as reflow (monotonic) or jitter
(oscillating). For every box, per frame, take the argmax of the horizontal
gradient inside the box; direction reversals of that argmax during a
monotonic grow-only drag are jitter, monotonic motion is legitimate reflow.
"""
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resize_jitter as rj

# Census-pass-1 hotspots (capture px) plus the sidebar add buttons.
BOXES = {
    "bar-cover": (372, 750, 440, 828),
    "row-cover-1": (372, 396, 440, 456),
    "row-cover-2": (820, 396, 880, 456),
    "row-cover-3": (1210, 396, 1276, 456),
    "row-cover-4": (372, 482, 440, 542),
    "row-cover-5": (820, 482, 880, 542),
    "row-cover-6": (1210, 482, 1276, 542),
    "side-cover-1": (96, 378, 140, 412),
    "side-cover-2": (96, 430, 140, 464),
    "side-cover-7": (96, 740, 140, 780),
    "chip-1": (418, 326, 502, 356),
    "chip-2": (514, 326, 598, 356),
    "tab-style": (1186, 258, 1280, 300),
    "add-dashed": (210, 75, 330, 132),
    "add-plus": (296, 321, 344, 365),
    "play-all": (1480, 172, 1600, 212),
}


def profile_argmax(frame, box):
    x0, y0, x1, y1 = box
    band = frame[y0:y1, x0:x1]
    grad = np.abs(np.diff(band.astype(int), axis=1)).sum(axis=0)
    if grad.max() == 0:
        return None, 0.0
    peak = int(np.argmax(grad))
    total = grad.sum()
    sharp = grad[peak] / total if total else 0.0
    return x0 + peak + 1, float(sharp)


def main(out_dir, seconds):
    os.makedirs(out_dir, exist_ok=True)
    rj.require_dpi_awareness()
    env = {k: v for k, v in os.environ.items() if k.startswith("ECHO_")}
    env["ECHO_RENDER_DIAGNOSTICS"] = "1"
    proc, log = rj.launch_app(env)
    try:
        hwnd = rj.find_app_window()
        rj.user32.ShowWindow(hwnd, 0x9)
        time.sleep(0.4)
        rj.user32.MoveWindow(hwnd, rj.WIN_X, rj.WIN_Y, rj.WIN_W, rj.WIN_H, True)
        time.sleep(0.8)
        with rj.Blackout() as blackout:
            blackout.place_below(hwnd)
            time.sleep(0.3)

            left, top, right, bottom = rj.window_rect(hwnd)
            done = threading.Event()

            def drag():
                time.sleep(1.0)
                rj.drag_bottom_right_corner(right - 4, bottom - 4)
                done.set()

            threading.Thread(target=drag, daemon=True).start()
            origin = time.monotonic()
            grabber = rj.GdiGrabber(origin, fps=45, duration=seconds)
            grabber.start()
            series = {name: [] for name in BOXES}
            sharp_series = {name: [] for name in BOXES}
            times = []
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
                times.append(now - origin)
                for name, box in BOXES.items():
                    col, sharp = profile_argmax(frame, box)
                    series[name].append(col if col is not None else np.nan)
                    sharp_series[name].append(sharp)
                # Crop at flip moments of the watched boxes: see WHAT moves.
                if len(times) >= 2:
                    for name in ("add-dashed", "add-plus", "row-cover-2"):
                        cols = series[name]
                        if None in (cols[-1], cols[-2]) or abs(cols[-1] - cols[-2]) < 0.8:
                            continue
                        box = BOXES[name]
                        pad = 14
                        crop = frame[max(0, box[1] - pad):box[3] + pad,
                                     max(0, box[0] - pad):box[2] + pad]
                        crops_dir = os.path.join(out_dir, f"crops-{name}")
                        os.makedirs(crops_dir, exist_ok=True)
                        from PIL import Image
                        Image.fromarray(crop).save(os.path.join(
                            crops_dir,
                            f"t{times[-1]:.3f}-c{cols[-2]:.0f}-{cols[-1]:.0f}.png"))
            np.savez_compressed(
                os.path.join(out_dir, "oscillation.npz"),
                times=np.array(times),
                **{f"col-{n}": np.array(v, dtype=float) for n, v in series.items()},
                **{f"sharp-{n}": np.array(v) for n, v in sharp_series.items()})
            print(f"{'box':14s} {'moves':>6s} {'flips':>6s} {'net':>5s}  positions")
            for name, cols in series.items():
                cols = np.array(cols, dtype=float)
                valid = cols[~np.isnan(cols)]
                if len(valid) < 10:
                    print(f"{name:14s}  (no feature)")
                    continue
                d = np.diff(valid)
                moves = np.abs(d) >= 0.8
                dirs = np.sign(d[moves])
                flips = int(np.sum(dirs[1:] * dirs[:-1] < 0)) if len(dirs) > 1 else 0
                uniq = sorted(set(valid.tolist()))
                span = f"{int(valid.min())}..{int(valid.max())}"
                print(f"{name:14s} {int(moves.sum()):6d} {flips:6d} {span:>7s}"
                      f"  uniq={uniq[:8]}{'...' if len(uniq) > 8 else ''}")
    finally:
        log.close()
        import subprocess
        subprocess.run(["taskkill", "/F", "/IM", "echomusicnext.exe"], capture_output=True)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        rj.DEFAULT_OUT, "census2")
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 7.0
    main(out, secs)
