"""CI-only smoke check of the actual installer in an ephemeral runner account."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install

subprocess.run([sys.executable, "install.py"], check=True)
subprocess.run([str(install.PYTHON), "-m", "pip", "check"], check=True)
subprocess.run([str(install.PYTHON), "-c", "import kokoro, soundfile, filelock, kokoro_cli"], check=True)
launcher = install.BIN / ("speak-kokoro.cmd" if install.WINDOWS else "speak-kokoro")
subprocess.run([str(launcher), "--help"], check=True)
conf = install.CONFIG / "kokoro-tts.conf"
original = conf.read_text(encoding="utf-8")
subprocess.run([sys.executable, "install.py", "--uninstall"], check=True)
assert not install.VENV.exists()
assert not launcher.exists()
assert conf.read_text(encoding="utf-8") == original
