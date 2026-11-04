"""Verify the topmost strip fix: the maximized rect must equal the work area.

Launches the app, sets REAL topmost (argtypes-declared SetWindowPos), runs
minimize -> restore -> maximize, prints geometry at each stage, then samples
the physical rows around the taskbar boundary (top = 1380 at 125% DPI).
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

user32 = ctypes.windll.user32
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = wt.BOOL


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


def rects(h):
    wr = wt.RECT()
    cr = wt.RECT()
    user32.GetWindowRect(h, ctypes.byref(wr))
    user32.GetClientRect(h, ctypes.byref(cr))
    return (wr.left, wr.top, wr.right, wr.bottom), (cr.right, cr.bottom)


def capture_rows(y0, h, path):
    gdi32 = ctypes.windll.gdi32
    X, Y, W = 0, y0, 2560
    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]
    class BMI(ctypes.Structure):
        _fields_ = [("bmiHeader", BMIH), ("bmiColors", ctypes.c_uint32 * 3)]
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BMI()
    bmi.bmiHeader.biSize = ctypes.sizeof(BMIH)
    bmi.bmiHeader.biWidth = W
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    hbmp = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0, None, None, 0)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    gdi32.BitBlt(hdc_mem, 0, 0, W, h, hdc_screen, X, Y, 0x00CC0020)
    gdi32.SelectObject(hdc_mem, old)
    size = W * h * 4
    buf = (ctypes.c_ubyte * size)()
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)
    lines = []
    for row in range(h):
        base = row * W * 4
        rs = gs = bs = 0
        n = 0
        for col in range(0, W, 8):
            i = base + col * 4
            rs += buf[i + 2]; gs += buf[i + 1]; bs += buf[i]; n += 1
        lines.append(f"row {y0 + row}: {rs // n} {gs // n} {bs // n}")
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)
    with open(path, "w") as f:
        f.write("\n".join(lines))


def main():
    subprocess.run(["taskkill", "/F", "/IM", "echomusicnext.exe"], capture_output=True)
    time.sleep(1.5)
    env = dict(os.environ)
    env["PATH"] = QT_BIN + os.pathsep + env.get("PATH", "")
    env["QT_LOGGING_RULES"] = "echo.platform.windows.window.debug=true"
    with open(LOG, "w") as lf:
        subprocess.Popen([APP], env=env, cwd=os.path.dirname(APP),
                         stdout=lf, stderr=subprocess.STDOUT)
    hwnd = None
    for _ in range(40):
        time.sleep(0.25)
        hwnd = find_window()
        if hwnd:
            break
    if not hwnd:
        sys.exit("window never appeared")
    h = wt.HWND(hwnd)
    time.sleep(6)
    if user32.IsZoomed(h):
        user32.ShowWindow(h, 9)
        time.sleep(2)
    user32.MoveWindow(h, 400, 150, 1280, 800, True)
    time.sleep(1.5)
    print("windowed:", rects(h))

    # real topmost
    ok = user32.SetWindowPos(h, wt.HWND(-1), 0, 0, 0, 0, 0x1 | 0x2 | 0x10)
    time.sleep(1.0)
    print("topmost set:", bool(ok), "bit:", user32.GetWindowLongW(h, -20) & 0x8)

    # the user's sequence: minimize -> restore -> maximize
    user32.ShowWindow(h, 6); time.sleep(2.0)   # minimize
    print("after minimize: zoomed", bool(user32.IsZoomed(h)),
          "bit", user32.GetWindowLongW(h, -20) & 0x8)
    user32.ShowWindow(h, 9); time.sleep(2.0)   # restore (into maximized)
    wr, cr = rects(h)
    print("after restore:", wr, cr, "zoomed", bool(user32.IsZoomed(h)),
          "bit", user32.GetWindowLongW(h, -20) & 0x8)
    user32.ShowWindow(h, 3); time.sleep(2.5)   # maximize
    wr, cr = rects(h)
    print("after maximize:", wr, cr, "zoomed", bool(user32.IsZoomed(h)),
          "bit", user32.GetWindowLongW(h, -20) & 0x8)

    # work area check (physical = DIP * 1.25; work bottom expected 1380)
    work = wt.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # SPI_GETWORKAREA
    print("work area (DIP):", work.left, work.top, work.right, work.bottom)
    print("maximized rect == work:", (wr[0], wr[1], wr[2], wr[3]) ==
          (work.left, work.top, work.right, work.bottom))

    capture_rows(1330, 110, os.path.join(HERE, "verify-fix-rows.txt"))
    print("rows written")


if __name__ == "__main__":
    main()
