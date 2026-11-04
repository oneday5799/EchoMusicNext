"""Launch echomusicnext.exe for diagnostics with a small default window.

Usage: python launch-app.py [W H [X Y]]
  W/H  native window size in physical pixels (default 1280x800)
  X/Y  top-left position (default 400,150)

The app re-asserts its persisted geometry shortly after startup, so the
script waits for that restore to settle, moves the window, and re-checks
twice before giving up. The app is left running.
"""
import ctypes
import os
import subprocess
import sys
import time
import ctypes.wintypes as wt

APP = r"D:\Code\EchoMusicNext\build\release\app\echomusicnext.exe"
QT_BIN = r"D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin"

W, H = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) >= 3 else (1280, 800)
X, Y = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) >= 5 else (400, 150)

user32 = ctypes.windll.user32


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


def rect_of(hwnd):
    rc = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return (rc.left, rc.top, rc.right, rc.bottom)


subprocess.run(["taskkill", "/F", "/IM", "echomusicnext.exe"], capture_output=True)
time.sleep(1.5)
env = dict(os.environ)
env["PATH"] = QT_BIN + os.pathsep + env.get("PATH", "")
subprocess.Popen([APP], env=env, cwd=os.path.dirname(APP))

hwnd = None
for _ in range(40):  # up to 10s for the window to appear
    time.sleep(0.25)
    hwnd = find_window()
    if hwnd:
        break
if not hwnd:
    sys.exit("window never appeared")

# The persisted session state can be maximized; MoveWindow then fights the
# app's own maximize-restore logic and the rect oscillates. Leave the
# maximized state first and give the restore time to settle.
if user32.IsZoomed(hwnd):
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    time.sleep(2.0)

# Let the app's deferred geometry restore run out before resizing, otherwise
# it overwrites the move a few seconds later.
time.sleep(6)
target = (X, Y, X + W, Y + H)
for attempt in range(3):
    user32.MoveWindow(hwnd, X, Y, W, H, True)
    time.sleep(1.5)
    if rect_of(hwnd) == target:
        break
    time.sleep(1.5)
print(f"hwnd=0x{hwnd:X} rect={rect_of(hwnd)} target={target} "
      f"{'OK' if rect_of(hwnd) == target else 'MISMATCH'}")
