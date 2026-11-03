"""Automated reproduction and quantification of issue #4.

Drives a real mouse drag on the frameless window's bottom-right resize handle
(startSystemResize -> WM_SIZING modal loop), captures the composed desktop
region with a GDI BitBlt grabber at ~150 fps, and tracks edges per frame.
Every frame carries a monotonic timestamp from the same clock the drag threads
use, so session alignment holds by construction. (An ffmpeg gdigrab variant
was tried first: its -framerate pacing does not hold on this machine — it
delivered all 1500 frames before a drag even started — so the capturer was
replaced with an in-process BitBlt loop.)

What is tracked, per frame:

  right / bottom   the composed window content boundary against a solid black
                   backdrop, anchored to the true rect from GetWindowRect
                   (which follows the WM_SIZING loop synchronously).
  cover-top        the TOP edge of the rectangular now-playing cover in the
                   player bar. The bar is bottom-anchored, so in a fresh frame
                   the cover follows the live bottom border 1:1; in a stale
                   frame it stays behind — the gap between cover edge and
                   window border pulsing is exactly the content-edge jitter
                   users report (the border itself follows the mouse smoothly,
                   so the artifact is only visible on content edges).
  fm-bottom/right  the bottom and right edges of the Private FM gradient
                   cover. This cover is layout-static (identical bbox at base
                   and grown window sizes), so ANY excursion of its edges is
                   a presentation artifact, e.g. DWM stretching the last
                   surface over the grown rect between fresh frames.
  circle-x         the left tangent structure of the hero circle-cover row,
                   whose layout position responds to window width.
  edge0/edge1      strong static interior layout edges, for completeness.

Metrics per drag session (detector bias = median idle lag, subtracted first;
even a perfect pipeline trails by one composition beat):

  stale       edge >= 18 px (about two size steps) behind truth while the
              window grew — a presented old frame.
  bounce      edge jumped backward while the window did not shrink — the
              visible flicker the issue is about.
  freeze /    growth frames in which the cover edge stood still, and the
  freeze-jump catch-up jump that ends such a stall within a few frames —
              the freeze-then-jump beat users perceive as jitter. A smooth
              pipeline with constant transport delay freezes never.
  max-lag     worst composed shortfall in px.
  cover-*     the same three measures taken at the rectangular cover edge.
  clean       window grew and the composition kept up.

The software render backend (QT_QUICK_BACKEND=software) presents synchronously
and defines the pipeline floor; excess over it is the artifact.

Usage:
  python resize_jitter.py run <config> [--drags N] [--out DIR]
    <config>: baseline | software | basic | preview | sync
  python resize_jitter.py probe
    capture-only calibration against an already running instance.

Results land in <out>/<config>/ (default build/diagnostics/resize-jitter):
summary.json, trace.csv, evidence PNGs and the app diagnostics log.
"""

import bisect
import ctypes
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
APP = os.path.join(REPO, "build", "release", "app", "echomusicnext.exe")
QT_BIN = os.path.join(REPO, "build", "qt-official", "6.12.0", "msvc2022_64", "bin")
DEFAULT_OUT = os.path.join(REPO, "build", "diagnostics", "resize-jitter")

# Fixed window rect (physical pixels) and the capture region around it. The
# window top sits high enough that a full-height drag never hits the work-area
# bottom (taskbar), which would silently clamp the bottom-edge growth.
WIN_X, WIN_Y, WIN_W, WIN_H = 400, 150, 1600, 1000
CAP_X, CAP_Y = WIN_X - 60, WIN_Y + 150
CAP_W, CAP_H = WIN_W + 320, 1440 - CAP_Y
# Rows (within the capture band) used for the right-edge and interior-edge
# tracking, and columns used for the bottom-edge tracking; the drag cursor
# hovers at the bottom-right corner, outside all of them.
TRACK_ROWS = (30, 260)
TRACK_COLS = (80, 240)
LEFT_IN_CAP = WIN_X - CAP_X  # fixed window left edge, stretch origin
# Content-edge tracker windows (absolute capture coordinates). The now-playing
# bar cover starts ~58 px above the base window bottom (row 850) and follows
# it down; the hero circle row keeps a fixed height near the top. The Private
# FM gradient cover is layout-static (verified: identical bbox at base and
# grown sizes), so any motion of its edges is a presentation artifact — e.g.
# DWM stretching the last surface over the grown rect between fresh frames.
BARCOVER_ROWS = (730, 1080)
BARCOVER_COLS = (375, 435)
CIRCLE_ROWS = (290, 450)
CIRCLE_COLS = (860, 1040)
FM_BOTTOM_ROWS = (160, 290)   # rows scanned for the FM cover's bottom edge
FM_RIGHT_COLS = (480, 660)    # columns scanned for its right edge
FM_RIGHT_ROWBAND = (30, 200)  # vertical span of the FM cover used for it
FM_BOTTOM_COLBAND = (392, 550)
FPS = 150
# A 231-step drag runs ~3.3 s (press, steps, release); three sessions plus
# settles must fit inside one capture.
CAPTURE_SECONDS = 17.0
DRAG_TOTAL = 231  # physical px per drag session, both axes
DRAG_STEPS = 231  # 1 px per step mirrors real mouse drag granularity; the FM
                  # cover edge quantization flips as the width walks every
                  # integer, which coarser steps skip over.
# Session i re-centers at offset-0.5 s and releases at offset+3.3 s, so
# offsets must leave the whole session inside its own gap.
DRAG_SPACING = 4.8
DRAG_PX_TOLERANCE = 0.8

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
OUT_DIR = DEFAULT_OUT

SRCCOPY, CAPTUREBLT = 0x00CC0020, 0x40000000


def require_dpi_awareness():
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:
        user32.SetProcessDPIAware()
    ctypes.windll.winmm.timeBeginPeriod(1)


def find_app_window(timeout=20.0):
    """Return the main top-level HWND of echomusicnext.exe."""
    deadline = time.monotonic() + timeout
    hwnds = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def on_window(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value == "EchoMusicNext":
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                hwnds.append((hwnd, pid.value))
        return True

    while time.monotonic() < deadline:
        hwnds.clear()
        user32.EnumWindows(on_window, 0)
        for hwnd, pid in hwnds:
            process = kernel32.OpenProcess(0x1000, False, pid)
            if not process:
                continue
            name = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            ok = ctypes.windll.psapi.GetModuleFileNameExW(process, None, name, ctypes.byref(size))
            kernel32.CloseHandle(process)
            if ok and name.value.lower().endswith("echomusicnext.exe"):
                return hwnd
        time.sleep(0.2)
    raise RuntimeError("EchoMusicNext window not found")


def launch_app(env_extra):
    subprocess.run(["taskkill", "/F", "/IM", "echomusicnext.exe"], capture_output=True)
    time.sleep(1.0)
    env = dict(os.environ)
    env["PATH"] = QT_BIN + os.pathsep + env.get("PATH", "")
    env.update(env_extra)
    log = open(os.path.join(OUT_DIR, "app.log"), "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([APP], env=env, cwd=os.path.dirname(APP),
                            stdout=log, stderr=subprocess.STDOUT)
    find_app_window()
    time.sleep(2.5)  # shell polish and first frames
    return proc, log


def window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def drag_bottom_right_corner(handle_x, handle_y, total=DRAG_TOTAL, steps=DRAG_STEPS):
    """Press the corner resize handle and drag diagonally with real input."""
    user32.SetCursorPos(handle_x, handle_y)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.05)
    step = total / steps
    marks = [(time.monotonic(), handle_x, handle_y)]
    for i in range(1, steps + 1):
        user32.SetCursorPos(int(handle_x + step * i), int(handle_y + step * i))
        time.sleep(0.013)
    marks.append((time.monotonic(), int(handle_x + total), int(handle_y + total)))
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    return marks


class CursorDragger(threading.Thread):
    """Runs the drag sessions at fixed offsets from the shared capture origin.

    Each session re-centers the window to the base rect first, so every drag
    covers the same growth; the recenter happens ~0.5 s before the press and
    stays outside the classification window.
    """

    def __init__(self, hwnd, sessions, origin, total=DRAG_TOTAL):
        super().__init__(daemon=True)
        self.hwnd = hwnd
        self.sessions = sessions
        self.origin = origin
        self.total = total
        self.marks = []  # [(session start t, end t)] in capture-clock seconds

    def run(self):
        for offset in self.sessions:
            wait = self.origin + offset - 0.5 - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            user32.MoveWindow(self.hwnd, WIN_X, WIN_Y, WIN_W, WIN_H, True)
            time.sleep(0.35)
            wait = self.origin + offset - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            left, top, right, bottom = window_rect(self.hwnd)
            marks = drag_bottom_right_corner(right - 4, bottom - 4, self.total)
            self.marks.append((marks[0][0] - self.origin, marks[-1][0] - self.origin))
            time.sleep(0.25)  # settle between sessions


class RectSampler(threading.Thread):
    """Samples the true window rect every ~2 ms.

    GetWindowRect follows the WM_SIZING modal loop synchronously, so it is the
    ground truth for how far the window has grown; the composed pixels are
    what may lag behind it.
    """

    def __init__(self, hwnd, origin, duration=CAPTURE_SECONDS):
        super().__init__(daemon=True)
        self.hwnd = hwnd
        self.origin = origin
        self.duration = duration
        self.times = []    # monotonic seconds relative to origin
        self.rights = []   # window right edge in capture coordinates
        self.bottoms = []  # window bottom edge in capture coordinates
        self.done = threading.Event()

    def run(self):
        deadline = self.origin + self.duration
        while time.monotonic() < deadline:
            _, _, right, bottom = window_rect(self.hwnd)
            self.times.append(time.monotonic() - self.origin)
            self.rights.append(right - CAP_X)
            self.bottoms.append(bottom - CAP_Y)
            time.sleep(0.002)
        self.done.set()

    def edge_at(self, t, which="right"):
        """Step-interpolated true window edge at capture time t."""
        series = self.rights if which == "right" else self.bottoms
        index = bisect.bisect_right(self.times, t) - 1
        if index < 0:
            return series[0]
        return float(series[index])


class Blackout:
    """Solid black borderless window placed directly beneath the app.

    The wallpaper behind the drag range has bright regions (within a few gray
    levels of the app background), which blinds the edge detector exactly
    where the window grows. A black backdrop guarantees maximum contrast for
    every newly covered column and hides neighbouring windows.
    """

    def __init__(self):
        self.hwnd = None

    def __enter__(self):
        wndproc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", wndproc),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        instance = kernel32.GetModuleHandleW(None)
        brush = gdi32.CreateSolidBrush(0x00000000)
        cls = WNDCLASSW()
        cls.style = 0
        cls.lpfnWndProc = ctypes.cast(user32.DefWindowProcW, wndproc)
        cls.hInstance = instance
        cls.hbrBackground = brush
        cls.lpszClassName = "EchoResizeJitterBlackout"
        user32.RegisterClassW(ctypes.byref(cls))
        # Covers the whole capture region, so every direction the window can
        # grow in meets maximum contrast (and neighbouring windows vanish).
        self.hwnd = user32.CreateWindowExW(
            0x08000000 | 0x00000080,  # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            cls.lpszClassName, "EchoResizeJitterBlackout", 0x80000000,  # WS_POPUP
            CAP_X, CAP_Y - 20, 2600 - CAP_X, CAP_H + 40,
            None, None, instance, None)
        user32.ShowWindow(self.hwnd, 1)
        return self

    def place_below(self, app_hwnd):
        # hWndInsertAfter precedes the positioned window, so inserting the
        # backdrop "after" the app puts it directly beneath the app.
        user32.SetWindowPos(self.hwnd, app_hwnd, 0, 0, 0, 0, 0x0013)

    def __exit__(self, *exc):
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None


class GdiGrabber(threading.Thread):
    """BitBlt the fixed desktop region into a DIB section as fast as paced.

    Each queued item is (timestamp, gray frame). BitBlt from the screen DC
    returns the DWM-composed desktop and excludes the mouse cursor sprite.
    """

    def __init__(self, origin, fps=FPS, duration=CAPTURE_SECONDS):
        super().__init__(daemon=True)
        self.origin = origin
        self.interval = 1.0 / fps
        self.duration = duration
        self.frames = queue.Queue(maxsize=16)

    def run(self):
        hdc = user32.GetDC(None)
        memdc = gdi32.CreateCompatibleDC(hdc)
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = CAP_W
        bmi.bmiHeader.biHeight = -CAP_H  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bits = ctypes.c_void_p()
        dib = gdi32.CreateDIBSection(memdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        gdi32.SelectObject(memdc, dib)
        stride = CAP_W * 4
        buffer = (ctypes.c_char * (stride * CAP_H)).from_address(bits.value)
        deadline = self.origin + self.duration
        next_tick = self.origin
        try:
            while time.monotonic() < deadline:
                gdi32.BitBlt(memdc, 0, 0, CAP_W, CAP_H, hdc, CAP_X, CAP_Y, SRCCOPY | CAPTUREBLT)
                stamp = time.monotonic() - self.origin
                rgba = np.frombuffer(buffer, np.uint8).reshape(CAP_H, stride)
                gray = rgba[:, 1::4].copy()  # green channel as luminance
                self.frames.put((stamp, gray))
                next_tick += self.interval
                pause = next_tick - time.monotonic()
                if pause > 0:
                    time.sleep(pause)
                else:
                    next_tick = time.monotonic()
        finally:
            gdi32.DeleteObject(dib)
            gdi32.DeleteDC(memdc)
            user32.ReleaseDC(None, hdc)
            self.frames.put(None)


def gradient_columns(frame, row_range):
    band = frame[row_range[0]:row_range[1]].astype(np.int16)
    return np.abs(np.diff(band, axis=1)).sum(axis=0)


def reference_edges(reference, right_edge, count=2):
    """Pick strong static vertical edges inside the window, left of its edge."""
    grad = gradient_columns(reference, TRACK_ROWS)
    inner = grad[100:max(101, int(right_edge) - 60)]
    order = np.argsort(inner)[::-1]
    chosen = []
    for idx in order:
        column = int(idx) + 100
        if all(abs(column - c) > 300 for c in chosen):
            chosen.append(column)
        if len(chosen) == count:
            break
    return sorted(chosen)


def light_edge(band, gt, previous, limit, axis):
    """Composed window edge = last light column/row against the black backdrop.

    The blackout turns everything behind the app black, so the composed window
    content is the only bright region: scanning from just past the true edge
    toward it, the first mostly-light line is the composed edge. Holding the
    previous value when nothing is found keeps a fully stale frame visible as
    growing lag instead of masking it as "caught up".
    """
    fraction = (band > 150).mean(axis=axis)
    hi = min(limit - 1, int(gt) + 2)
    lo = max(1, int(gt) - 140)
    for line in range(hi, lo, -1):
        if fraction[line] > 0.7:
            return float(line)
    return previous


def row_profile(frame, rows, cols):
    band = frame[rows[0]:rows[1], cols[0]:cols[1]].astype(np.float32)
    return np.abs(np.diff(band, axis=0)).mean(axis=1)


def col_profile(frame, rows, cols):
    band = frame[rows[0]:rows[1], cols[0]:cols[1]].astype(np.float32)
    return np.abs(np.diff(band, axis=1)).mean(axis=0)


def profile_shift(profile, reference, lo, hi):
    """Shift s in [lo, hi] best aligning the reference profile onto the frame.

    Positive s means the structure moved down/right. Subpixel refinement is a
    parabola over the correlation scores around the integer peak.
    """
    p = profile - profile.mean()
    pn = np.linalg.norm(p)
    if pn < 1e-6 or len(p) != len(reference):
        return 0.0
    length = len(reference)
    scores = {}
    for s in range(lo, hi + 1):
        if s >= 0:
            a, b = p[s:], reference[:length - s]
        else:
            a, b = p[:length + s], reference[-s:]
        if len(a) < 12:
            continue
        bm = b - b.mean()
        nb = np.linalg.norm(bm)
        if nb < 1e-6:
            continue
        scores[s] = float(np.dot(a, bm)) / (pn * nb)
    if not scores:
        return 0.0
    best = max(scores, key=scores.get)
    a, b, c = (scores.get(best - 1), scores[best], scores.get(best + 1))
    if a is not None and c is not None and (a - 2 * b + c) != 0:
        shift = 0.5 * (a - c) / (a - 2 * b + c)
        return best + float(np.clip(shift, -1.0, 1.0))
    return float(best)


def init_features(reference):
    """Locate the tracked content structures in the idle reference frame."""
    cover_prof = row_profile(reference, BARCOVER_ROWS, BARCOVER_COLS)
    # Init on the cover's own edges (top ~740, bottom ~819 at base size); the
    # window-bottom boundary ~848 is excluded so the tracker follows the cover
    # structure, not a duplicate of the bottom-border detector.
    cover_base = int(np.argmax(cover_prof[:105]))
    circle_prof = col_profile(reference, CIRCLE_ROWS, CIRCLE_COLS)
    circle_base = int(np.argmax(circle_prof[20:150])) + 20
    fm_bottom_prof = col_profile(reference, FM_BOTTOM_ROWS, FM_BOTTOM_COLBAND)
    # The FM cover's bottom edge sits at row ~223 at base size; keep the init
    # zone tight so it locks onto the boundary, not the interior gradient.
    fm_bottom_base = int(np.argmax(fm_bottom_prof[30:100])) + 30
    fm_right_prof = row_profile(reference, FM_RIGHT_ROWBAND, FM_RIGHT_COLS)
    fm_right_base = int(np.argmax(fm_right_prof[40:140])) + 40
    return {
        "cover-prof": cover_prof, "cover-base": cover_base,
        "circle-prof": circle_prof, "circle-base": circle_base,
        "fmb-prof": fm_bottom_prof, "fmb-base": fm_bottom_base,
        "fmr-prof": fm_right_prof, "fmr-base": fm_right_base,
    }


def track_features(frame, feats):
    """Content-edge positions (absolute capture coordinates) for this frame."""
    cover_shift = profile_shift(row_profile(frame, BARCOVER_ROWS, BARCOVER_COLS),
                                feats["cover-prof"], -45, 205)
    circle_shift = profile_shift(col_profile(frame, CIRCLE_ROWS, CIRCLE_COLS),
                                 feats["circle-prof"], -45, 90)
    # Layout-static cover: motion beyond ~1 px is a presentation artifact, so
    # the search stays tight and cannot wander onto the interior gradient.
    fmb_shift = profile_shift(col_profile(frame, FM_BOTTOM_ROWS, FM_BOTTOM_COLBAND),
                              feats["fmb-prof"], -14, 14)
    fmr_shift = profile_shift(row_profile(frame, FM_RIGHT_ROWBAND, FM_RIGHT_COLS),
                              feats["fmr-prof"], -14, 14)
    cover_top = BARCOVER_ROWS[0] + feats["cover-base"] + cover_shift
    circle_x = CIRCLE_COLS[0] + feats["circle-base"] + circle_shift
    fm_bottom = FM_BOTTOM_ROWS[0] + feats["fmb-base"] + fmb_shift
    fm_right = FM_RIGHT_COLS[0] + feats["fmr-base"] + fmr_shift
    return cover_top, circle_x, fm_bottom, fm_right


def track_edges(frame, edges, gt_right, gt_bottom, previous_right, previous_bottom):
    """Track interior edges plus the composed right and bottom window edges."""
    grad = gradient_columns(frame, TRACK_ROWS)
    tracked = []
    for edge in edges:
        lo, hi = max(1, edge - 40), min(len(grad) - 1, edge + 40)
        window = grad[lo:hi]
        if not len(window):
            tracked.append(float(edge))
            continue
        best = int(np.argmax(window)) + lo
        if lo < best < len(grad) - 1:
            a, b, c = grad[best - 1], grad[best], grad[best + 1]
            denom = a - 2 * b + c
            shift = 0.5 * (a - c) / denom if abs(denom) > 1e-6 else 0.0
            tracked.append(best + float(np.clip(shift, -1.0, 1.0)))
        else:
            tracked.append(float(best))
    right = light_edge(frame[TRACK_ROWS[0]:TRACK_ROWS[1]], gt_right,
                       previous_right, CAP_W, axis=0)
    bottom = light_edge(frame[:, TRACK_COLS[0]:TRACK_COLS[1]], gt_bottom,
                        previous_bottom, CAP_H, axis=1)
    return tracked, right, bottom


def warmup_edge_stable(warmup):
    """True when the FM cover's right edge argmax is constant late in warmup.

    The app keeps laying out after its window first appears; a reference
    frozen too early anchors every later reading to a stale position (a
    constant offset plus phantom +-1 tracker flips during drags).
    """
    cols = []
    for _, frame in warmup[-30:]:
        band = frame[FM_RIGHT_ROWBAND[0]:FM_RIGHT_ROWBAND[1]]
        grad = np.abs(np.diff(
            band[:, FM_RIGHT_COLS[0]:FM_RIGHT_COLS[1]].astype(int), axis=1)).sum(axis=0)
        cols.append(int(np.argmax(grad[40:140])))
    return len(set(cols)) == 1


def fm_edge_boundary(frame, expected):
    """Raw FM cover right-edge boundary column (capture px), NCC-free.

    profile_shift's parabolic NCC quantizes the edge's subpixel excursions
    into +-1 readings whenever the faint secondary gradient beside the edge
    appears or disappears, so its flip count tracks tracker wobble, not the
    edge (the wobble frames are bit-identical at the boundary). The argmax of
    the raw horizontal gradient in a narrow window around the rest position
    moves only when the edge genuinely relocates by a whole pixel.
    """
    band = frame[FM_RIGHT_ROWBAND[0]:FM_RIGHT_ROWBAND[1]]
    grad = np.abs(np.diff(
        band[:, FM_RIGHT_COLS[0]:FM_RIGHT_COLS[1]].astype(int), axis=1)).sum(axis=0)
    rel = int(round(expected)) - FM_RIGHT_COLS[0]
    lo, hi = max(0, rel - 8), min(len(grad), rel + 9)
    if hi <= lo:
        return float(expected)
    return float(FM_RIGHT_COLS[0] + lo + int(np.argmax(grad[lo:hi])) + 1)


def consume(grabber, run_dir, hwnd, sampler, windows):
    """Track edges online from the grabber stream; collect evidence frames."""
    reference = None
    edges = []
    feats = None
    trace = []
    warmup = []
    stale_samples, cover_samples, circle_samples, fm_samples = [], [], [], []
    maxlag = [(0, None, 0.0)] * len(windows)  # per window: (lag, frame, t)
    maxcover = [(0, None, 0.0)] * len(windows)
    maxfm = [(0, None, 0.0)] * len(windows)
    previous_right, previous_bottom = float(WIN_W - 1), float(WIN_H - 151)
    previous_inner = None
    previous_cover, previous_circle = None, None
    fm_rest = (None, None)  # layout positions of the FM edges from the reference
    while True:
        item = grabber.frames.get()
        if item is None:
            break
        now, frame = item
        if reference is None:
            warmup.append((now, frame))
            span = warmup[-1][0] - warmup[0][0]
            # Median suppresses transient sprites and animated shader noise;
            # what survives is static structure fit for edges. Freeze only
            # once the layout has stopped moving (see warmup_edge_stable).
            if (span >= 0.8 and len(warmup) >= 60 and warmup_edge_stable(warmup)) \
                    or len(warmup) >= 400:
                reference = np.median(
                    np.stack([f for _, f in warmup[-25:]]), axis=0).astype(np.uint8)
                warmup.clear()
                edges = reference_edges(reference, sampler.edge_at(now))
                feats = init_features(reference)
                fm_rest = (FM_BOTTOM_ROWS[0] + feats["fmb-base"],
                           FM_RIGHT_COLS[0] + feats["fmr-base"])
            continue
        gt_right = sampler.edge_at(now, "right")
        gt_bottom = sampler.edge_at(now, "bottom")
        tracked, right, bottom = track_edges(frame, edges, gt_right, gt_bottom,
                                             previous_right, previous_bottom)
        cover_top, circle_x, fm_bottom, fm_right = track_features(frame, feats)
        fm_col = fm_edge_boundary(frame, fm_rest[1]) if fm_rest[1] else 0.0
        trace.append((now, right, bottom, cover_top, circle_x,
                      fm_bottom, fm_right, fm_col, *tracked))
        # Keep raw frames as evidence, inside the drag windows only.
        if previous_inner is not None and any(a <= now <= b for a, b in windows):
            lag = max(gt_right - right, gt_bottom - bottom)
            cover_dev = gt_bottom - cover_top
            fm_dev = max(abs(fm_bottom - fm_rest[0]), abs(fm_right - fm_rest[1]))
            if lag > 24 and len(stale_samples) < 4:
                stale_samples.append((frame, now, lag))
            for index, (a, b) in enumerate(windows):
                if not a <= now <= b:
                    continue
                if lag > maxlag[index][0]:
                    maxlag[index] = (lag, frame, now)
                if cover_dev > maxcover[index][0]:
                    maxcover[index] = (cover_dev, frame, now)
                if fm_dev > maxfm[index][0]:
                    maxfm[index] = (fm_dev, frame, now)
            if previous_cover is not None and previous_circle is not None:
                if (cover_top - previous_cover < -3 and len(cover_samples) < 3):
                    cover_samples.append((frame, now, previous_cover - cover_top))
                if (circle_x - previous_circle < -3 and len(circle_samples) < 3):
                    circle_samples.append((frame, now, previous_circle - circle_x))
            if fm_dev > 2.0 and len(fm_samples) < 4:
                fm_samples.append((frame, now, fm_dev))
        previous_right, previous_bottom = right, bottom
        previous_inner = tracked
        previous_cover, previous_circle = cover_top, circle_x
    from PIL import Image
    for name, bucket in (("stale", stale_samples), ("coverback", cover_samples),
                         ("circleback", circle_samples), ("fmwobble", fm_samples)):
        for frame, now, metric in bucket:
            path = os.path.join(run_dir, f"sample-{name}-{now:.3f}-m{metric:.1f}.png")
            Image.fromarray(frame).save(path)
    for prefix, bucket in (("maxlag", maxlag), ("maxcover", maxcover),
                           ("maxfm", maxfm)):
        for index, (lag, frame, now) in enumerate(bucket):
            if frame is not None:
                path = os.path.join(run_dir, f"sample-{prefix}-w{index}-{now:.3f}-m{lag:.1f}.png")
                Image.fromarray(frame).save(path)
    return trace, edges


def analyze(trace, edges, marks, sampler, config):
    """Quantify presentation lag during drag sessions against the true rect.

    Ground truth for how far the window has grown comes from the rect sampler
    (GetWindowRect follows the WM_SIZING loop synchronously); composed edges
    are measured from pixels, each anchored to its true edge. Even a perfect
    pipeline trails by up to one composition beat, so each detector's bias
    (median idle lag / idle cover-to-border distance) is subtracted first.
    What remains is the artifact:

    stale      composed edge >= 18 px (about two size steps) behind truth in
               a frame where the window grew — a presented old frame.
    bounce     edge jumped backward while the window did not shrink — the
               visible flicker the issue is about.
    cover-*    the same three measures taken at the now-playing cover's top
               edge, i.e. what a user actually sees at content edges.
    circle-*   backward jumps of the width-responsive circle-row edge.
    clean      window grew and the composition kept up.
    """
    rows = [(t, pixel_r, pixel_b, cover, circle, fmb, fmr,
             sampler.edge_at(t, "right"), sampler.edge_at(t, "bottom"), *inner)
            for t, pixel_r, pixel_b, cover, circle, fmb, fmr, *inner in trace]
    idle_lags = {"right": [], "bottom": []}
    idle_cover, idle_fmb, idle_fmr, idle_fmc = [], [], [], []
    for previous, current in zip(rows, rows[1:]):
        still = (abs(current[7] - previous[7]) <= 0.7
                 and abs(current[8] - previous[8]) <= 0.7
                 and abs(current[1] - previous[1]) <= 0.7
                 and abs(current[2] - previous[2]) <= 0.7
                 and abs(current[3] - previous[3]) <= 1.0)
        if still:
            idle_lags["right"].append(current[7] - current[1])
            idle_lags["bottom"].append(current[8] - current[2])
            idle_cover.append(current[8] - current[3])
            idle_fmb.append(current[5])
            idle_fmr.append(current[6])
            idle_fmc.append(current[9])
    bias = {edge: float(np.median(values)) if values else 0.0
            for edge, values in idle_lags.items()}
    cover_offset = float(np.median(idle_cover)) if idle_cover else 0.0
    # The FM cover is layout-static, so its idle position IS the rest position;
    # excursions from it during the drag are presentation artifacts.
    fm_rest = (float(np.median(idle_fmb)) if idle_fmb else 0.0,
               float(np.median(idle_fmr)) if idle_fmr else 0.0)
    fm_col_rest = float(np.median(idle_fmc)) if idle_fmc else 0.0

    sessions = [{"start": start, "end": end} for start, end in marks]
    per_session = []
    for session in sessions:
        counts = {"stale": 0, "bounce": 0, "clean": 0, "edge-steps": 0,
                  "cover-stale": 0, "cover-bounce": 0, "circle-bounce": 0,
                  "growth-frames": 0, "freeze": 0, "freeze-jump": 0,
                  "max-jump": 0.0,
                  "fm-wobble": 0, "fm-flips": 0, "fm-max-dev": 0.0,
                  "fm-edge-moves": 0,
                  "max-lag-right": 0.0, "max-lag-bottom": 0.0, "max-back": 0.0,
                  "max-cover-dev": 0.0, "max-back-cover": 0.0,
                  "max-back-circle": 0.0}
        session_lags, cover_devs = [], []
        previous = None
        freezes_since_jump = -10  # frames since the last freeze, -10 = none
        fm_dir = None
        for current in rows:
            t, pixel_r, pixel_b, cover, circle, fmb, fmr, gt_r, gt_b, *inner = current
            if not (session["start"] - 0.05 <= t <= session["end"] + 0.25):
                previous = current
                continue
            if previous is None:
                previous = current
                continue
            lag_r = (gt_r - pixel_r) - bias["right"]
            lag_b = (gt_b - pixel_b) - bias["bottom"]
            cover_dev = (gt_b - cover) - cover_offset
            fm_dev_b, fm_dev_r = fmb - fm_rest[0], fmr - fm_rest[1]
            fm_dev = max(abs(fm_dev_b), abs(fm_dev_r))
            session_lags.append(max(lag_r, lag_b))
            dgt_r, dgt_b = gt_r - previous[7], gt_b - previous[8]
            dpixel_r, dpixel_b = pixel_r - previous[1], pixel_b - previous[2]
            dcover, dcircle = cover - previous[3], circle - previous[4]
            dgt = max(dgt_r, dgt_b)
            if dgt > 0.7:
                counts["edge-steps"] += 1
                if max(lag_r, lag_b) > 18:
                    counts["stale"] += 1
                else:
                    counts["clean"] += 1
                if dgt_b > 0.7 and cover_dev > 18:
                    counts["cover-stale"] += 1
            if dgt > 2.0:
                counts["growth-frames"] += 1
                if abs(dcover) < 1.0:
                    counts["freeze"] += 1
                    freezes_since_jump = 0
                else:
                    if 0 <= freezes_since_jump <= 3 and dcover > 8:
                        counts["freeze-jump"] += 1
                        freezes_since_jump = -10
                    else:
                        freezes_since_jump += 1
                if dcover > counts["max-jump"]:
                    counts["max-jump"] = dcover
            # fm-wobble/fm-flips read the NCC tracker: subpixel excursions
            # quantize into +-1 readings and flip direction whenever the
            # faint secondary gradient beside the edge appears or disappears,
            # so both fire on invisible wobble (the flip frames are
            # bit-identical at the boundary). fm-edge-moves reads the raw
            # gradient argmax instead and counts only genuine whole-pixel
            # edge relocations — the visible jitter the issue is about.
            if abs(fm_dev_b) > 0.5 or abs(fm_dev_r) > 0.5:
                counts["fm-wobble"] += 1
            dfmr = fmr - previous[6]
            if abs(dfmr) > 0.3:
                if fm_dir is not None and dfmr * fm_dir < 0:
                    counts["fm-flips"] += 1
                fm_dir = 1.0 if dfmr > 0 else -1.0
            if abs(inner[0] - fm_col_rest) >= 0.8:
                counts["fm-edge-moves"] += 1
            if (dpixel_r < -3 or dpixel_b < -3) and dgt > -0.7:
                counts["bounce"] += 1
                counts["max-back"] = max(counts["max-back"],
                                         -min(dpixel_r, dpixel_b))
            if dcover < -3 and dgt_b > -0.7:
                counts["cover-bounce"] += 1
                counts["max-back-cover"] = max(counts["max-back-cover"], -dcover)
            if dcircle < -3 and dgt_r > -0.7:
                counts["circle-bounce"] += 1
                counts["max-back-circle"] = max(counts["max-back-circle"], -dcircle)
            if dgt_b > 0.7:
                cover_devs.append(cover_dev)
            counts["max-lag-right"] = max(counts["max-lag-right"], lag_r)
            counts["max-lag-bottom"] = max(counts["max-lag-bottom"], lag_b)
            counts["max-cover-dev"] = max(counts["max-cover-dev"], cover_dev)
            counts["fm-max-dev"] = max(counts["fm-max-dev"], fm_dev)
            previous = current
        if session_lags:
            counts["lag-p50"] = round(float(np.percentile(session_lags, 50)), 1)
            counts["lag-p95"] = round(float(np.percentile(session_lags, 95)), 1)
        if cover_devs:
            counts["cover-dev-p95"] = round(float(np.percentile(cover_devs, 95)), 1)
        if counts["growth-frames"]:
            counts["freeze-ratio"] = round(counts["freeze"] / counts["growth-frames"], 2)
        per_session.append(counts)
    keys = ("stale", "bounce", "clean", "edge-steps", "cover-stale",
            "cover-bounce", "circle-bounce", "growth-frames", "freeze",
            "freeze-jump", "fm-wobble", "fm-flips", "fm-edge-moves")
    total = {key: sum(s[key] for s in per_session) for key in keys}
    for key in ("max-lag-right", "max-lag-bottom", "max-back", "max-cover-dev",
                "max-back-cover", "max-back-circle", "lag-p95", "cover-dev-p95",
                "max-jump", "fm-max-dev"):
        total[key] = round(max((s.get(key, 0) for s in per_session), default=0), 1)
    total["freeze-ratio"] = round(total["freeze"] / max(1, total["growth-frames"]), 2)
    return {"config": config, "edges": edges, "left-in-capture": LEFT_IN_CAP,
            "detector-bias-px": {k: round(v, 2) for k, v in bias.items()},
            "cover-offset-px": round(cover_offset, 2),
            "fm-rest-px": [round(v, 2) for v in fm_rest],
            "fm-col-rest-px": round(fm_col_rest, 2),
            "sessions": per_session, "total": total}


def derive_sessions(sampler):
    """Drag sessions from the ground-truth rect itself (for manual runs)."""
    ts, rs, bs = sampler.times, sampler.rights, sampler.bottoms
    back = max(1, int(0.025 / 0.002))  # compare ~25 ms apart: catches slow drags
    moved = [False] * len(ts)
    for i in range(back, len(ts)):
        if abs(rs[i] - rs[i - back]) > 0.5 or abs(bs[i] - bs[i - back]) > 0.5:
            moved[i] = True
            moved[i - back] = True
    marks, start, last_t = [], None, None
    for t, m in zip(ts, moved):
        if m:
            if start is None:
                start = t
            last_t = t
        elif start is not None and t - last_t > 0.3:
            marks.append((start - 0.15, last_t + 0.15))
            start = None
    if start is not None:
        marks.append((start - 0.15, last_t + 0.15))
    return marks


def write_outputs(run_dir, summary, trace, edges, sampler):
    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    with open(os.path.join(run_dir, "trace.csv"), "w", encoding="utf-8") as handle:
        handle.write("t,pixel_right,gt_right,pixel_bottom,gt_bottom,"
                     "cover_top,circle_x,fm_bottom,fm_right,fm_col,"
                     + ",".join(f"edge{i}" for i in range(len(edges))) + "\n")
        for row in trace:
            values = (row[0], row[1], sampler.edge_at(row[0], "right"),
                      row[2], sampler.edge_at(row[0], "bottom"),
                      row[3], row[4], row[5], row[6], *row[7:])
            handle.write(",".join(f"{v:.2f}" for v in values) + "\n")


def manual(seconds, out_dir):
    """Capture while the USER drags; sessions derived from the true rect."""
    global OUT_DIR
    OUT_DIR = out_dir
    run_dir = os.path.join(out_dir, "manual")
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir, exist_ok=True)
    require_dpi_awareness()
    log = None
    try:
        hwnd = find_app_window(timeout=3.0)
    except RuntimeError:
        proc, log = launch_app({})
        hwnd = find_app_window()
    user32.ShowWindow(hwnd, 0x9)  # SW_RESTORE
    time.sleep(0.4)
    user32.MoveWindow(hwnd, WIN_X, WIN_Y, WIN_W, WIN_H, True)
    time.sleep(0.8)
    with Blackout() as blackout:
        blackout.place_below(hwnd)
        time.sleep(0.3)
        origin = time.monotonic()
        sampler = RectSampler(hwnd, origin, duration=seconds)
        sampler.start()
        grabber = GdiGrabber(origin, duration=seconds)
        grabber.start()
        trace, edges = consume(grabber, run_dir, hwnd, sampler,
                               [(-1.0, seconds + 1.0)])
        while not sampler.done.is_set():
            time.sleep(0.05)
    marks = derive_sessions(sampler)
    summary = analyze(trace, edges, marks, sampler, "manual")
    summary["drags"] = len(marks)
    summary["trace-frames"] = len(trace)
    summary["sessions-marked"] = [[round(a, 2), round(b, 2)] for a, b in marks]
    write_outputs(run_dir, summary, trace, edges, sampler)
    print(json.dumps(summary["total"], indent=2))
    print("sessions:", summary["sessions-marked"])
    return summary


def run(config, drags, out_dir):
    global OUT_DIR
    OUT_DIR = out_dir
    run_dir = os.path.join(out_dir, config)
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir, exist_ok=True)
    require_dpi_awareness()
    env_extra = {"ECHO_RENDER_DIAGNOSTICS": "1"}
    if config == "software":
        env_extra["QT_QUICK_BACKEND"] = "software"
    elif config == "basic":
        env_extra["QSG_RENDER_LOOP"] = "basic"
    elif config == "preview":
        env_extra["ECHO_RESIZE_PREVIEW"] = "1"
    elif config == "sync":
        env_extra["ECHO_RESIZE_SYNC"] = "1"
    elif config != "baseline":
        raise SystemExit(f"unknown config {config}")

    proc, log = launch_app(env_extra)
    try:
        hwnd = find_app_window()
        if user32.IsZoomed(hwnd):
            raise RuntimeError("window is maximized; resize handles are hidden")
        user32.ShowWindow(hwnd, 0x9)  # SW_RESTORE
        time.sleep(0.4)
        user32.MoveWindow(hwnd, WIN_X, WIN_Y, WIN_W, WIN_H, True)
        time.sleep(0.8)
        with Blackout() as blackout:
            blackout.place_below(hwnd)
            time.sleep(0.3)

            origin = time.monotonic()
            # First drag starts only after the reference warmup has frozen on
            # a settled layout (see consume). Offsets keep whole sessions
            # (recenter at -0.5 s, release at +3.3 s) inside their own gap.
            offsets = [2.5 + i * DRAG_SPACING for i in range(drags)]
            windows = [(off - 0.1, off + 3.3) for off in offsets]
            sampler = RectSampler(hwnd, origin)
            sampler.start()
            grabber = GdiGrabber(origin)
            grabber.start()
            dragger = CursorDragger(hwnd, offsets, origin)
            dragger.start()
            trace, edges = consume(grabber, run_dir, hwnd, sampler, windows)
            while dragger.is_alive() or not sampler.done.is_set():
                time.sleep(0.05)  # collect straggler marks and rect samples

            summary = analyze(trace, edges, dragger.marks, sampler, config)
            summary["app_pid"] = proc.pid
            summary["drags"] = drags
            summary["trace-frames"] = len(trace)
            with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
                json.dump(summary, handle, indent=2)
            with open(os.path.join(run_dir, "trace.csv"), "w", encoding="utf-8") as handle:
                handle.write("t,pixel_right,gt_right,pixel_bottom,gt_bottom,"
                             "cover_top,circle_x,fm_bottom,fm_right,fm_col,"
                             + ",".join(f"edge{i}" for i in range(len(edges))) + "\n")
                for row in trace:
                    values = (row[0], row[1], sampler.edge_at(row[0], "right"),
                              row[2], sampler.edge_at(row[0], "bottom"),
                              row[3], row[4], row[5], row[6], *row[7:])
                    handle.write(",".join(f"{v:.2f}" for v in values) + "\n")
            print(json.dumps(summary["total"], indent=2))
            print(json.dumps(summary["sessions"], indent=2))
            return summary
    finally:
        log.close()
        subprocess.run(["taskkill", "/F", "/IM", "echomusicnext.exe"], capture_output=True)


def probe():
    """Capture-only sanity check against an already running instance."""
    global OUT_DIR
    OUT_DIR = DEFAULT_OUT
    os.makedirs(DEFAULT_OUT, exist_ok=True)
    require_dpi_awareness()
    hwnd = find_app_window()
    user32.ShowWindow(hwnd, 0x9)
    time.sleep(0.4)
    user32.MoveWindow(hwnd, WIN_X, WIN_Y, WIN_W, WIN_H, True)
    time.sleep(0.8)
    origin = time.monotonic()
    grabber = GdiGrabber(origin, fps=30, duration=1.0)
    grabber.start()
    frames = []
    while True:
        item = grabber.frames.get()
        if item is None:
            break
        frames.append(item[1])
    _, _, right, bottom = window_rect(hwnd)
    right0 = right - CAP_X
    reference = np.median(np.stack(frames), axis=0).astype(np.uint8)
    edges = reference_edges(reference, right0)
    feats = init_features(reference)
    grad = gradient_columns(reference, TRACK_ROWS)
    print(f"frames={len(frames)} size={CAP_W}x{CAP_H} "
          f"window_right_in_frame={right0} window_bottom_in_frame={bottom - CAP_Y}")
    print(f"edge_candidates={edges} "
          f"grad_at_edges={[int(grad[e]) for e in edges if e < len(grad)]}")
    print(f"cover_base_row={BARCOVER_ROWS[0] + feats['cover-base']} "
          f"(window bottom {bottom - CAP_Y}, expect ~58 above) "
          f"circle_base_col={CIRCLE_COLS[0] + feats['circle-base']}")
    from PIL import Image
    Image.fromarray(reference).save(os.path.join(DEFAULT_OUT, "probe-reference.png"))
    print(f"reference image: {os.path.join(DEFAULT_OUT, 'probe-reference.png')}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "probe":
        probe()
    elif len(sys.argv) >= 2 and sys.argv[1] == "manual":
        seconds, out = 60, DEFAULT_OUT
        if "--seconds" in sys.argv:
            seconds = int(sys.argv[sys.argv.index("--seconds") + 1])
        if "--out" in sys.argv:
            out = sys.argv[sys.argv.index("--out") + 1]
        manual(seconds, out)
    elif len(sys.argv) >= 3 and sys.argv[1] == "run":
        config = sys.argv[2]
        drags = 3
        out = DEFAULT_OUT
        if "--drags" in sys.argv:
            drags = int(sys.argv[sys.argv.index("--drags") + 1])
        if "--out" in sys.argv:
            out = sys.argv[sys.argv.index("--out") + 1]
        run(config, drags, out)
    else:
        print(__doc__)
