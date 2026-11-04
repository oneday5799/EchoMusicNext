"""Repro the topmost strip: topmost -> minimize -> restore -> maximize.

Launches the app with windowLog captured to a file, runs the sequence,
then samples the physical rows around the taskbar boundary (work bottom =
1380 at 125% DPI) and saves a PNG of the region.

Usage: python repro-topmost.py [stage]
  stage in {launch, sequence, capture, all}  default all
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

APP = r"D:\Code\EchoMusicNext\build\release\app\echomusicnext.exe"
QT_BIN = r"D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin"
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "topmost-app.log")
PNG = os.path.join(HERE, "topmost-after-maximize.png")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0
TOPMOST = -1
NOTOPMOST = -2
SWP_NOMOVE = 0x2
SWP_NOSIZE = 0x1
SWP_SHOWWINDOW = 0x40


class BMIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class BMI(ctypes.Structure):
    _fields_ = [("bmiHeader", BMIH), ("bmiColors", ctypes.c_uint32 * 3)]


def find_window():
    hwnd = None
    WF = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, _):
        nonlocal hwnd
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, buf, 256)
        if buf.value == "EchoMusicNext" and user32.IsWindowVisible(h):
            rc = wt.RECT()
            user32.GetWindowRect(h, ctypes.byref(rc))
            if rc.right - rc.left > 0:
                hwnd = h
                return False
        return True

    user32.EnumWindows(WF(cb), 0)
    return hwnd


def rects(hwnd):
    wr = wt.RECT()
    cr = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wr))
    user32.GetClientRect(hwnd, ctypes.byref(cr))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return wr, cr, (pt.x, pt.y)


def capture_region(x, y, w, h, path):
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BMI()
    bmi.bmiHeader.biSize = ctypes.sizeof(BMIH)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB
    hbmp = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), DIB_RGB_COLORS, None, None, 0)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, SRCCOPY)
    gdi32.SelectObject(hdc_mem, old)

    size = w * h * 4
    buf = (ctypes.c_ubyte * size)()
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)

    from PIL import Image
    img = Image.new("RGB", (w, h))
    px = img.load()
    for row in range(h):
        base = row * w * 4
        for col in range(w):
            b, g, r = buf[base + col * 4], buf[base + col * 4 + 1], buf[base + col * 4 + 2]
            px[col, row] = (r, g, b)
    img.save(path)

    # per-row mean color report
    lines = []
    for row in range(h):
        base = row * w * 4
        rs = gs = bs = 0
        for col in range(0, w, 8):
            i = base + col * 4
            rs += buf[i + 2]
            gs += buf[i + 1]
            bs += buf[i]
        n = len(range(0, w, 8))
        lines.append(f"row {y + row}: {rs // n} {gs // n} {bs // n}")
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)
    with open(path + ".rows.txt", "w") as f:
        f.write("\n".join(lines))
    return buf, w, h


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"

    if stage in ("all", "launch"):
        subprocess.run(["taskkill", "/F", "/IM", "echomusicnext.exe"], capture_output=True)
        time.sleep(1.5)
        if os.path.exists(LOG):
            os.remove(LOG)
        env = dict(os.environ)
        env["PATH"] = QT_BIN + os.pathsep + env.get("PATH", "")
        env["QT_LOGGING_RULES"] = "echo.platform.windows.window.debug=true"
        with open(LOG, "w") as lf:
            proc = subprocess.Popen([APP], env=env, cwd=os.path.dirname(APP),
                                    stdout=lf, stderr=subprocess.STDOUT)
        hwnd = None
        for _ in range(40):
            time.sleep(0.25)
            hwnd = find_window()
            if hwnd:
                break
        if not hwnd:
            sys.exit("window never appeared")
        time.sleep(6)  # deferred geometry restore
        if user32.IsZoomed(hwnd):
            user32.ShowWindow(hwnd, 9)
            time.sleep(2)
        user32.MoveWindow(hwnd, 400, 150, 1280, 800, True)
        time.sleep(1.5)
        print(f"hwnd=0x{hwnd:X} rect={rects(hwnd)}")
        if stage == "launch":
            return

    hwnd = find_window()
    if not hwnd:
        sys.exit("window not found; run stage launch first")

    if stage in ("all", "sequence"):
        # topmost (user's external tool equivalent)
        user32.SetWindowPos(hwnd, TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        time.sleep(1.5)
        print("after topmost:", rects(hwnd), "zoomed", bool(user32.IsZoomed(hwnd)))
        # minimize -> restore -> maximize (the user's sequence)
        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        time.sleep(2.0)
        print("after minimize: zoomed", bool(user32.IsZoomed(hwnd)))
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(2.0)
        print("after restore:", rects(hwnd), "zoomed", bool(user32.IsZoomed(hwnd)))
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        time.sleep(2.5)
        print("after maximize:", rects(hwnd), "zoomed", bool(user32.IsZoomed(hwnd)))
        if stage == "sequence":
            return

    if stage in ("all", "capture"):
        hwnd2 = find_window()
        print("final:", rects(hwnd2), "zoomed", bool(user32.IsZoomed(hwnd2)),
              "topmost-exstyle", hex(user32.GetWindowLongW(hwnd2, -20) & 0x8))
        # physical rows around the work-area bottom (taskbar top = 1380)
        capture_region(0, 1330, 2560, 110, PNG)
        print("captured", PNG)


if __name__ == "__main__":
    main()
