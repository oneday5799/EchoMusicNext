# Continuous-resize transient capture: mimic an interactive vertical drag by
# growing the window one physical pixel per tick with short sleeps, capturing
# the bottom band as fast as PrintWindow allows (no settle), so frames land
# mid-relayout the way the eye sees them during a drag.
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


def find_main_window(pid):
    result = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lparam):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            result.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return result


def capture_band(hwnd, band_h, path):
    rc = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    w = rc.right - rc.left
    h = rc.bottom - rc.top
    y0 = max(0, h - band_h)
    band = h - y0
    hdc = user32.GetDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -band
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = DIB_RGB_COLORS
    ppv = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bi), DIB_RGB_COLORS, ctypes.byref(ppv), None, 0)
    old = gdi32.SelectObject(mem, hbmp)
    # full-window capture then crop the band (PrintWindow origin = window origin)
    ok = user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT) or user32.PrintWindow(hwnd, mem, 0)
    buf = (ctypes.c_ubyte * (w * band * 4)).from_address(ppv.value)
    data = bytes(buf)
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    from PIL import Image
    img = Image.frombytes("RGBA", (w, band), data, "raw", "BGRA").convert("RGB")
    img.save(path)
    return w, band, ok


def main():
    exe = "echomusicnext.exe"
    out = subprocess.check_output(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV"], text=True)
    pid = None
    for line in out.splitlines():
        if exe.lower() in line.lower():
            pid = int(line.split('","')[1])
            break
    hwnd = find_main_window(pid)[0]
    dpi = user32.GetDpiForWindow(hwnd)
    print(f"hwnd={hwnd:#x} dpr={dpi / 96.0}")
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    left, top, width, height = rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    out_dir = r"D:\Code\EchoMusicNext\build\diagnostics\storm-frames"
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, f))
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    t0 = time.perf_counter()
    lat = []
    for step in range(steps + 1):
        if step:
            user32.SetWindowPos(hwnd, 0, left, top, width, height + step, 0x0004)
        w, band, ok = capture_band(hwnd, 320, os.path.join(out_dir, f"f-{step:03d}.png"))
        lat.append(time.perf_counter() - t0)
    dt = lat[-1] - lat[0]
    print(f"{steps} steps in {dt:.2f}s -> {steps / dt:.1f} steps/s, captures ok")
    # restore original size
    user32.SetWindowPos(hwnd, 0, left, top, width, height, 0x0004)
    return 0


if __name__ == "__main__":
    sys.exit(main())
