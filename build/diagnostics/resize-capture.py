# Vertical resize capture: step the window's bottom edge one physical pixel
# at a time and print the client contents after each step. The evidence for
# text-edge shimmer is the per-step ink pattern of a text block.
import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0
BI_RGB = 0
SRCCOPY = 0x00CC0020


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]

user32.GetDpiForWindow.restype = ctypes.c_uint
user32.SetProcessDPIAwarenessContext = getattr(user32, "SetProcessDPIAwarenessContext", None)


def find_main_window(pid):
    result = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lparam):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            result.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return result


def capture_client(hwnd, path):
    rc = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    hdc = user32.GetDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = BI_RGB
    ppv = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bi), DIB_RGB_COLORS, ctypes.byref(ppv), None, 0)
    old = gdi32.SelectObject(mem, hbmp)
    # PrintWindow with full content grabs the D3D-composited surface.
    ok = user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
    if not ok:
        user32.PrintWindow(hwnd, mem, 0)
    buf = (ctypes.c_ubyte * (w * h * 4)).from_address(ppv.value)
    data = bytes(buf)
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    # PNG via pure zlib (avoid Pillow dependency questions): write BMP instead,
    # PIL reads BMP fine and the analysis is ours.
    from PIL import Image
    img = Image.frombytes("RGBA", (w, h), data, "raw", "BGRA")
    img.convert("RGB").save(path)
    return w, h


def main():
    exe = "echomusicnext.exe"
    arr = (wt.DWORD * 4096)()
    count = 0
    # find pid by process name
    import subprocess
    out = subprocess.check_output(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV"], text=True)
    pid = None
    for line in out.splitlines():
        if exe.lower() in line.lower():
            pid = int(line.split('","')[1])
            break
    if not pid:
        print("app not running")
        return 1
    wins = find_main_window(pid)
    if not wins:
        print("no visible window for pid", pid)
        return 1
    hwnd, title = wins[0]
    print(f"hwnd={hwnd:#x} title={title!r}")
    dpi = user32.GetDpiForWindow(hwnd)
    print("dpi:", dpi, "dpr:", dpi / 96.0)
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    print("window rect:", rect.left, rect.top, rect.right, rect.bottom)

    out_dir = r"D:\Code\EchoMusicNext\build\diagnostics\resize-frames"
    import os
    os.makedirs(out_dir, exist_ok=True)

    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
    width = right - left
    height = bottom - top

    # Optional canonical start size so A/B runs share the same step pattern.
    if len(sys.argv) > 2:
        cw, ch = int(sys.argv[2]), int(sys.argv[3])
        user32.SetWindowPos(hwnd, 0, left, top, cw, ch, 0x0004)
        time.sleep(0.5)
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        left, top = rect.left, rect.top
        width, height = rect.right - left, rect.bottom - top
        print(f"canonical start {width}x{height}")
    for step in range(steps + 1):
        if step:
            # grow the bottom (default) or right edge by one physical pixel
            # per step; axis is the optional 4th argument
            axis = sys.argv[4] if len(sys.argv) > 4 else "v"
            if axis == "h":
                user32.SetWindowPos(hwnd, 0, left, top, width + step, height, 0x0004)
            else:
                user32.SetWindowPos(hwnd, 0, left, top, width, height + step, 0x0004)
            time.sleep(0.16)
        w, h = capture_client(hwnd, os.path.join(out_dir, f"step-{step:03d}.png"))
        if step % 8 == 0:
            print(f"step {step}: client {w}x{h}")
    print("captures in", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
