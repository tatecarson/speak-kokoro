"""Install Mac Services for the current user when the packaged app opens."""
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys


def install_mac_services():
    if not getattr(sys, "frozen", False):
        return
    resources = Path(sys._MEIPASS) / "quickactions"
    services = Path.home() / "Library/Services"
    services.mkdir(parents=True, exist_ok=True)
    for source in resources.glob("*.workflow"):
        target = services / source.name
        shutil.copytree(source, target, dirs_exist_ok=True)
        document = target / "Contents/document.wflow"
        with document.open("rb") as file:
            data = plistlib.load(file)
        command = "exec " + shlex.quote(sys.executable)
        if source.name.startswith("Stop"):
            command += " --stop"
        data["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"] = command
        with document.open("wb") as file:
            plistlib.dump(data, file)
    subprocess.run(["/System/Library/CoreServices/pbs", "-update"], capture_output=True)
