import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = ctypes.c_uint
user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
user32.MapVirtualKeyW.restype = ctypes.c_uint

KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1

VK_MOD = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
VK_KEY = {"space": 0x20, "left": 0x25, "right": 0x26, "up": 0x26, "down": 0x28,
          "s": 0x53, "d": 0x44, "i": 0x49, "m": 0x4D, "l": 0x4C, "p": 0x50,
          "b": 0x42, "k": 0x4B}
VK_KEY["up"] = 0x26


def send(combo, hold_ms=40):
    vks = [VK_MOD[c] for c in combo if c in VK_MOD] + \
          [VK_KEY[c] for c in combo if c in VK_KEY]
    if len(vks) != len(combo):
        raise SystemExit(f"unknown key in {combo}")
    events = []
    scan = [user32.MapVirtualKeyW(v, 0) for v in vks]
    for v, s in zip(vks, scan):
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.u.ki = KEYBDINPUT(v, s, 0, 0, None)
        events.append(inp)
    for v, s in reversed(list(zip(vks, scan))):
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.u.ki = KEYBDINPUT(v, s, KEYEVENTF_KEYUP, 0, None)
        events.append(inp)
    arr = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise SystemExit(f"SendInput failed: {sent}/{len(events)} err={ctypes.get_last_error()}")
    time.sleep(hold_ms / 1000.0)
    print(f"sent {'+'.join(combo)}")


if __name__ == "__main__":
    combos = {
        "togglePlayback": ["ctrl", "shift", "space"],
        "toggleWindow": ["alt", "ctrl", "s"],
        "toggleDesktopLyric": ["ctrl", "shift", "d"],
        "toggleMiniPlayer": ["ctrl", "shift", "i"],
        "toggleMute": ["ctrl", "shift", "m"],
    }
    for name in sys.argv[1:] or [None]:
        if name is None:
            continue
        send(combos[name])
