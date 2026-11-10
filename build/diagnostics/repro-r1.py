"""R1 repro loop: restore rescan-state values.sqlite, relaunch, watch for crash.

Usage: python repro-r1.py [rounds] [--keepdb]
Each round:
  1. taskkill the app
  2. restore values.sqlite.bak (rescan state) unless --keepdb
  3. launch the app with Qt bin in PATH
  4. poll liveness for WINDOW seconds; a round is a CRASH if the process exits
     before the window and a fresh crash dump appears
  5. record result; on crash, print the newest dump name and the log tail
"""
import os
import subprocess
import sys
import time
import glob

APP = r"D:\Code\EchoMusicNext\build\release\app\echomusicnext.exe"
QT_BIN = r"D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin"
DATA_DIR = (r"C:\Users\Oneday\AppData\Local\hoowhoami\EchoMusicNext"
            r"\plugins\.data\local-music")
DB = os.path.join(DATA_DIR, "values.sqlite")
BAK = r"D:\Code\EchoMusicNext\build\diagnostics\values.sqlite.bak"
REPORTS = (r"C:\Users\Oneday\AppData\Local\hoowhoami\EchoMusicNext"
           r"\logs\crashes\database\reports")
LOGS = r"C:\Users\Oneday\AppData\Local\hoowhoami\EchoMusicNext\logs"
WINDOW = float(os.environ.get("REPRO_WINDOW", "45"))


def newest(pattern):
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def kill():
    subprocess.run(["taskkill", "/F", "/IM", "echomusicnext.exe"],
                   capture_output=True)
    time.sleep(1.5)


def launch(extra_env=None):
    env = dict(os.environ)
    env["PATH"] = QT_BIN + os.pathsep + env.get("PATH", "")
    if extra_env:
        env.update(extra_env)
    return subprocess.Popen([APP], env=env, cwd=os.path.dirname(APP))


def wait_outcome(proc):
    """Returns 'crash', 'alive' or 'exited' (clean exit) within WINDOW."""
    deadline = time.time() + WINDOW
    dumps_before = set(glob.glob(os.path.join(REPORTS, "*.dmp")))
    while time.time() < deadline:
        if proc.poll() is not None:
            # crashpad writes the dump asynchronously; allow a grace period
            for _ in range(10):
                new = set(glob.glob(os.path.join(REPORTS, "*.dmp"))) - dumps_before
                if new:
                    return "crash", sorted(new, key=os.path.getmtime)[-1]
                time.sleep(0.5)
            return "exited", None
        time.sleep(0.5)
    return "alive", None


def log_tail():
    logs = glob.glob(os.path.join(LOGS, "echomusicnext-*.log"))
    latest = max(logs, key=os.path.getmtime) if logs else None
    if not latest:
        return ""
    with open(latest, "r", errors="replace") as fh:
        return "".join(fh.readlines()[-6:])


def session_files(since):
    """All log files modified after `since` (epoch seconds)."""
    out = []
    for f in glob.glob(os.path.join(LOGS, "echomusicnext-*.log")):
        if os.path.getmtime(f) >= since:
            out.append(f)
    return out


def op_count(files):
    import re
    n = 0
    for f in files:
        try:
            with open(f, "r", errors="replace") as fh:
                n += len(re.findall(r"EchoPluginFiles::invoke", fh.read()))
        except OSError:
            pass
    return n


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    keepdb = "--keepdb" in sys.argv
    for i in range(1, rounds + 1):
        kill()
        if not keepdb:
            with open(BAK, "rb") as src, open(DB, "wb") as dst:
                dst.write(src.read())
        started = time.time() - 1
        proc = launch()
        time.sleep(2)
        outcome, dump = wait_outcome(proc)
        stamp = time.strftime("%H:%M:%S")
        ops = op_count(session_files(started))
        print(f"[{stamp}] round {i}/{rounds}: {outcome}"
              f"{' dump=' + os.path.basename(dump) if dump else ''}"
              f" invokes={ops}",
              flush=True)
        if outcome == "alive" and ops == 0:
            print("  WARNING: storm did not run — round not comparable",
                  flush=True)
        if outcome == "crash":
            print(log_tail())
            print("RESULT=crash after", i, "rounds")
            return 1
        if outcome == "exited":
            print("app exited cleanly before window elapsed", flush=True)
    print(f"RESULT=survived {rounds} round(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
