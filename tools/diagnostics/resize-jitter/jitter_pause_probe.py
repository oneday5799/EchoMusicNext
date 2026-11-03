"""Decisive probe for the residual jitter on static sidebar content.

Alternates short 1px-step drags with long holds while hashing fixed crops and
sampling the window rect per frame. Classifies every crop change by phase:
changes only during moves with a silent geometry trace mean the compositor
displays stretched stale frames (present timing), not QML geometry.
"""
import hashlib
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resize_jitter as rj

BOXES = {
    "add-dashed": (210, 75, 330, 132),
    "add-plus": (296, 321, 344, 365),
    "chip-1": (418, 326, 502, 356),
    "chip-2": (514, 326, 598, 356),
    "side-cover-2": (96, 430, 140, 464),
}
CYCLES = 3
MOVE_PX = 45
MOVE_SLEEP = 0.013
HOLD = 1.4


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rj.require_dpi_awareness()
    env = {k: v for k, v in os.environ.items() if k.startswith("ECHO_")}
    env["ECHO_RENDER_DIAGNOSTICS"] = "1"
    env["ECHO_PIXEL_SNAP"] = "1"
    env["ECHO_PIXEL_SNAP_TRACE"] = "sidebar"
    proc, log = rj.launch_app(env)
    phases = []  # (t_rel, "move"|"hold", cycle)
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

            def drag_thread():
                time.sleep(1.2)
                for cycle in range(CYCLES):
                    left, top, right, bottom = rj.window_rect(hwnd)
                    phases.append((time.monotonic() - origin, "move", cycle))
                    rj.drag_bottom_right_corner(right - 4, bottom - 4,
                                                total=MOVE_PX, steps=MOVE_PX)
                    phases.append((time.monotonic() - origin, "hold", cycle))
                    time.sleep(HOLD)

            threading.Thread(target=drag_thread, daemon=True).start()
            sampler = rj.RectSampler(hwnd, origin, duration=30)
            sampler.start()

            grabber = rj.GdiGrabber(origin, fps=45, duration=16)
            grabber.start()
            rows = []  # (t_rel, phase, rect, hashes, maxdiffs)
            prev_crops = {}
            prev_crops_hash = {}
            crop_dir = os.path.join(out_dir, "changes")
            seen = 0
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
                t_rel = now - origin
                phase = "pre"
                for t0, name, _ in phases:
                    if t_rel >= t0:
                        phase = name
                left, top, right, bottom = rj.window_rect(hwnd)
                hashes, diffs = {}, {}
                for name, box in BOXES.items():
                    x0, y0, x1, y1 = box
                    crop = frame[y0:y1, x0:x1]
                    digest = hashlib.blake2b(crop.tobytes(), digest_size=8).hexdigest()
                    hashes[name] = digest
                    prev = prev_crops.get(name)
                    diffs[name] = 0 if prev is None else int(np.abs(
                        crop.astype(int) - prev.astype(int)).max())
                    if prev is None or digest != prev_crops_hash[name]:
                        prev_crops[name] = crop
                        prev_crops_hash[name] = digest
                        seen += 1
                        if seen <= 400:
                            import PIL.Image
                            d = os.path.join(crop_dir, name)
                            os.makedirs(d, exist_ok=True)
                            PIL.Image.fromarray(crop).save(os.path.join(
                                d, f"{phase}-t{t_rel:.3f}-d{diffs[name]}.png"))
                rows.append((t_rel, phase, (left, top, right, bottom), hashes, diffs))
            sampler.done.set()
            np.savez_compressed(
                os.path.join(out_dir, "probe.npz"),
                times=np.array([r[0] for r in rows]),
                phase=np.array([r[1] for r in rows]),
                rects=np.array([r[2] for r in rows]),
                **{f"diff-{n}": np.array([r[4][n] for r in rows]) for n in BOXES})

            print(f"\nframes={len(rows)}  saved-crops={seen}")
            print(f"{'box':14s} {'move-chg':>9s} {'hold-chg':>9s} {'move-maxd':>10s} {'hold-maxd':>10s}")
            for name in BOXES:
                move_chg = hold_chg = 0
                move_max = hold_max = 0
                for i in range(1, len(rows)):
                    d = rows[i][4][name]
                    if rows[i][1] == "move":
                        move_chg += d > 0
                        move_max = max(move_max, d)
                    elif rows[i][1] == "hold":
                        hold_chg += d > 0
                        hold_max = max(hold_max, d)
                print(f"{name:14s} {move_chg:9d} {hold_chg:9d} {move_max:10d} {hold_max:10d}")
            rects = np.array([r[2] for r in rows])
            print("window rect left-range:", rects[:, 0].min(), rects[:, 0].max(),
                  " top-range:", rects[:, 1].min(), rects[:, 1].max(),
                  " right-range:", rects[:, 2].min(), rects[:, 2].max())
    finally:
        log.flush()
        time.sleep(0.3)
        import subprocess
        subprocess.run(["taskkill", "/F", "/IM", "echomusicnext.exe"], capture_output=True)
        log.close()
        # Surface the app-side evidence: geometry trace + resize protocol stats.
        app_log = os.path.join(rj.OUT_DIR, "app.log")
        if os.path.exists(app_log):
            with open(app_log, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if "pixel-snap" in line or "Resize completed" in line:
                        print(line.rstrip())


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        rj.DEFAULT_OUT, "pause-probe")
    main(out)
