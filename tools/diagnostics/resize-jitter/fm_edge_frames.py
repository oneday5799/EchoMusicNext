"""Capture the FM cover right-edge neighborhood during odd-step drags.

Writes the per-frame column band (capture cols 470-690, rows 20-260) plus the
sampled window rect, so the crisp cover edge and the soft shadow slope can be
inspected separately at flip and stable moments.
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resize_jitter as rj


def main(seconds, out_path):
    rj.require_dpi_awareness()
    env = {"ECHO_RENDER_DIAGNOSTICS": "1"}
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
            origin = time.monotonic()
            # Whole sessions must not overlap: a 231-step drag runs ~3.3 s.
            offsets = [2.5 + i * rj.DRAG_SPACING for i in range(3)]
            grabber = rj.GdiGrabber(origin, duration=seconds)
            grabber.start()
            dragger = rj.CursorDragger(hwnd, offsets, origin)
            dragger.start()
            bands, rects, times = [], [], []
            import ctypes
            import ctypes.wintypes
            while True:
                try:
                    item = grabber.frames.get(timeout=0.5)
                except Exception:
                    item = None
                if item is None:
                    if not grabber.is_alive() and grabber.frames.empty():
                        break
                    continue
                t, frame = item
                times.append(t)
                bands.append(frame[20:260, 400:760].copy())
                rc = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rc))
                rects.append((rc.left, rc.top, rc.right, rc.bottom))
            np.savez_compressed(
                out_path,
                bands=np.stack(bands), rects=np.array(rects),
                times=np.array(times))
            print("frames:", len(bands))
    finally:
        log.close()
        import subprocess
        subprocess.run(["taskkill", "/F", "/IM", "echomusicnext.exe"], capture_output=True)


if __name__ == "__main__":
    import ctypes
    import ctypes.wintypes
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else rj.CAPTURE_SECONDS
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        rj.DEFAULT_OUT, "fm-edge-frames.npz")
    main(seconds, out)
