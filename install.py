#!/usr/bin/env python3
"""Install into a private environment without changing the system Python."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import venv

SOURCE = Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"
DATA = (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "speak-kokoro"
        if WINDOWS else Path.home() / ".local/share")
VENV = DATA / ("venv" if WINDOWS else "kokoro-venv")
BIN = DATA / "bin" if WINDOWS else Path.home() / ".local/bin"
CONFIG = (Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "speak-kokoro"
          if WINDOWS else Path.home() / ".config")
PYTHON = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")
AGENT = Path.home() / "Library/LaunchAgents/com.tatecarson.kokoro-tts.plist"


def run(args):
    subprocess.run([str(arg) for arg in args], check=True)


def windows_path(add):
    """Change only our entry in the user's PATH, preserving expandable values."""
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            value, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            value, kind = "", winreg.REG_EXPAND_SZ
        entries = value.split(";") if value else []
        normalize = lambda p: os.path.normcase(os.path.normpath(os.path.expandvars(p)))
        entries = [p for p in entries if normalize(p) != normalize(str(BIN))]
        if add:
            entries.append(str(BIN))
        winreg.SetValueEx(key, "Path", 0, kind, ";".join(entries))
    # Notify shells launched after setup of the changed environment.
    import ctypes
    notify = ctypes.windll.user32.SendMessageTimeoutW
    notify.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t,
                       ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint,
                       ctypes.POINTER(ctypes.c_size_t)]
    notify.restype = ctypes.c_ssize_t
    result = ctypes.c_size_t()
    notify(0xFFFF, 0x001A, 0, "Environment", 2, 5000, ctypes.byref(result))


def install():
    if not (3, 10) <= sys.version_info[:2] < (3, 13):
        raise RuntimeError("Use Python 3.10, 3.11, or 3.12. Python 3.12 is recommended.")
    if sys.maxsize <= 2**32:
        raise RuntimeError("Install 64-bit Python, then run setup again.")
    if os.name != "nt" and os.geteuid() == 0:
        raise RuntimeError("Run this installer as your normal user, without sudo.")
    print(f"Installing in {VENV}", flush=True)
    if PYTHON.exists():
        existing = subprocess.check_output(
            [str(PYTHON), "-c", "import sys; print('%s.%s' % sys.version_info[:2])"], text=True).strip()
        requested = f"{sys.version_info.major}.{sys.version_info.minor}"
        if existing != requested:
            raise RuntimeError(f"Existing environment uses Python {existing}. Uninstall first, then reinstall with {requested}. Settings will be kept.")
        subprocess.run([str(PYTHON), "-m", "kokoro_cli", "--quit"], check=False)
    venv.EnvBuilder(with_pip=True).create(VENV)
    run([PYTHON, "-m", "pip", "install", "--upgrade", "pip"])
    run([PYTHON, "-m", "pip", "install", "--upgrade", SOURCE])
    BIN.mkdir(parents=True, exist_ok=True)
    CONFIG.mkdir(parents=True, exist_ok=True)
    conf = CONFIG / "kokoro-tts.conf"
    if not conf.exists():
        conf.write_text("# Default voice and speed\nVOICE=af_heart\nSPEED=1.0\n", encoding="utf-8")
    lexicon = CONFIG / "kokoro-lexicon.json"
    if not lexicon.exists():
        shutil.copy2(SOURCE / "config/kokoro-lexicon.json", lexicon)
    if WINDOWS:
        (BIN / "speak-kokoro.cmd").write_text(f'@echo off\nsetlocal\nset PYTHONUTF8=1\n"{PYTHON}" -m kokoro_cli %*\n', encoding="utf-8")
        windows_path(True)
    else:
        # Keep the established location used by macOS Services.
        launcher = BIN / "speak-kokoro"
        if launcher.is_symlink():
            launcher.unlink()
        shutil.copy2(SOURCE / "bin/speak-kokoro", launcher)
        launcher.chmod(0o755)
    if sys.platform == "darwin":
        install_mac()
    print("\nInstalled. Next, check audio and download the first voice:", flush=True)
    launcher = BIN / ("speak-kokoro.cmd" if WINDOWS else "speak-kokoro")
    prefix = "& " if WINDOWS else ""
    for args in ("--doctor", "--download", '"Hello! Kokoro is ready."'):
        print(f'  {prefix}"{launcher}" {args}')
    if WINDOWS:
        print("Open a new terminal to use the short speak-kokoro command. If needed, sign out and back in.")
    elif str(BIN) not in os.environ.get("PATH", "").split(os.pathsep):
        print('To use the short command in this terminal: export PATH="$HOME/.local/bin:$PATH"')
        print("See the README for making that change permanent.")
    if sys.platform == "darwin":
        print(f'For the menu bar and reading panel: "{PYTHON}" -m kokoro_menubar')
        print("Assign shortcuts in System Settings > Keyboard > Keyboard Shortcuts > Services > Text.")


def install_mac():
    # Shut down the pre-0.2 daemon too. Its old socket cannot serve the new client.
    subprocess.run(["pkill", "-f", str(VENV / "kokoro_daemon.py")], check=False)
    services = Path.home() / "Library/Services"
    services.mkdir(parents=True, exist_ok=True)
    for workflow in (SOURCE / "quickactions").glob("*.workflow"):
        target = services / workflow.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(workflow, target)
    for action in ("-flush", "-update"):
        subprocess.run(["/System/Library/CoreServices/pbs", action], capture_output=True)
    # Old installations copied modules into the venv root. Remove only those
    # known app files so they cannot shadow the newly installed package.
    for name in ("kokoro_daemon.py", "kokoro_menubar.py", "kokoro_player.py"):
        (VENV / name).unlink(missing_ok=True)
    subprocess.run(["pkill", "-f", str(VENV / "kokoro_menubar.py")], check=False)
    subprocess.run(["pkill", "-f", str(PYTHON) + " -m kokoro_menubar"], check=False)
    if AGENT.exists():
        subprocess.run(["launchctl", "unload", "-w", str(AGENT)], capture_output=True)
        with AGENT.open("rb") as fh:
            agent = plistlib.load(fh)
        agent["ProgramArguments"] = [str(PYTHON), "-m", "kokoro_menubar"]
        with AGENT.open("wb") as fh:
            plistlib.dump(agent, fh)
        subprocess.run(["launchctl", "load", "-w", str(AGENT)], check=True)


def uninstall(purge=False):
    if PYTHON.exists():
        subprocess.run([str(PYTHON), "-m", "kokoro_cli", "--quit"], check=False)
        # Wait for the daemon to release its executable before deleting on Windows.
        import time
        for _ in range(50):
            result = subprocess.run([str(PYTHON), "-m", "kokoro_cli", "--status"], capture_output=True, text=True)
            if "not running" in result.stdout or result.returncode:
                break
            time.sleep(0.1)
    if sys.platform == "darwin":
        if AGENT.exists():
            subprocess.run(["launchctl", "unload", "-w", str(AGENT)], capture_output=True)
            AGENT.unlink()
        for pattern in (str(VENV / "kokoro_menubar.py"), str(PYTHON) + " -m kokoro_menubar",
                        str(VENV / "kokoro_daemon.py")):
            subprocess.run(["pkill", "-f", pattern], check=False)
        for name in ("Speak with Kokoro.workflow", "Stop Kokoro Speech.workflow"):
            target = Path.home() / "Library/Services" / name
            if target.exists():
                shutil.rmtree(target)
    if VENV.exists():
        shutil.rmtree(VENV)
    (BIN / ("speak-kokoro.cmd" if WINDOWS else "speak-kokoro")).unlink(missing_ok=True)
    if WINDOWS:
        windows_path(False)
    if purge:
        for name in ("kokoro-tts.conf", "kokoro-lexicon.json"):
            (CONFIG / name).unlink(missing_ok=True)
    print("Removed speak-kokoro. Settings are kept unless --purge was supplied.")
    print("Python, eSpeak NG, system audio libraries, logs, and downloaded model caches are kept.")
    if sys.platform == "darwin":
        print("Clear assigned shortcuts in System Settings > Keyboard > Keyboard Shortcuts > Services.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--purge", action="store_true", help="Also remove settings when uninstalling")
    args = parser.parse_args()
    if args.purge and not args.uninstall:
        parser.error("--purge requires --uninstall")
    try:
        uninstall(args.purge) if args.uninstall else install()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Setup failed: {exc}\nSee the README troubleshooting section.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
