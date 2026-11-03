"""Pause probe on the Personal FM page: are the circle-cover edges and text
crops changing only during window growth (DWM stretch class) or also at rest
(real geometry)? Same method as jitter_pause_probe, boxes picked on the FM
page (app restores its last route, so it opens there).
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
    "circle-2-edge": (1120, 290, 1210, 440),
    "circle-4-edge": (1630, 290, 1720, 440),
    "title-text": (760, 645, 860, 700),
    "tag-row-text": (763, 828, 1040, 865),
    "square-cover": (510, 655, 725, 875),
    "add-dashed": (183, 105, 425, 150),
    "side-cover": (196, 440, 240, 476),
}
CYCLES = 3
MOVE_PX = 45
HOLD = 1.4


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rj.require_dpi_awareness()
    env = {k: v for k, v in os.environ.items() if k.startswith("ECHO_")}
    env["ECHO_RENDER_DIAGNOSTICS"] = "1"
    proc, log = rj.launch_app(env)
    phases = []
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
                    rj.drag_bottom_right_corner(right - 4, bottom - 4,
                                                total=MOVE_PX, steps=MOVE_PX)
                    time.sleep(HOLD)

            threading.Thread(target=drag_thread, daemon=True).start()
            grabber = rj.GdiGrabber(origin, fps=45, duration=16)
            grabber.start()
            rows = []
            prev_hash = {}
            crop_dir = os.path.join(out_dir, "changes")
            saved = 0
            first_mono = None
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
                left, top, right, bottom = rj.window_rect(hwnd)
                rows.append((now - first_mono, (left, top, right, bottom), diffs))
            np.savez_compressed(
                os.path.join(out_dir, "probe.npz"),
                times=np.array([r[0] for r in rows]),
                rects=np.array([r[1] for r in rows]),
                **{f"diff-{n}": np.array([r[2][n] for r in rows]) for n in BOXES})
            print(f"frames={len(rows)} saved-crops={saved}")

            # Classify by actual rect growth (robust, no clock assumptions).
            rects = np.array([r[1] for r in rows])
            width = np.diff(rects[:, 2], prepend=rects[0, 2])
            grew = width > 0
            phase = np.array(["rest"] * len(rows), dtype=object)
            i = 0
            n = len(grew)
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
            print(f"{'box':15s} {'move-chg':>9s} {'move-maxd':>10s} {'rest-chg':>9s} {'rest-maxd':>10s}")
            for name in BOXES:
                d = np.array([r[2][name] for r in rows])
                mv = d[phase == "move"]
                rs = d[phase == "rest"]
                print(f"{name:15s} {int((mv > 0).sum()):9d} {int(mv.max()) if mv.size else 0:10d}"
                      f" {int((rs > 0).sum()):9d} {int(rs.max()) if rs.size else 0:10d}")
    finally:
        log.flush()
        time.sleep(0.3)
        import subprocess
        subprocess.run(["taskkill", "/F", "/IM", "echomusicnext.exe"], capture_output=True)
        log.close()
        app_log = os.path.join(rj.OUT_DIR, "app.log")
        if os.path.exists(app_log):
            with open(app_log, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if "Resize completed" in line:
                        print(line.strip())


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        rj.DEFAULT_OUT, "fm-probe")
    main(out)
