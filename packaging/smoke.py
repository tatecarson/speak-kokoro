"""Exercise the frozen executable with no Python/model cache supplied at runtime."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'dist' / ('Speak Kokoro.app' if sys.platform == 'darwin' else 'speak-kokoro')
with tempfile.TemporaryDirectory(prefix='kokoro-test-') as temporary:
    folder = Path(temporary)
    relocated = folder / 'Path with spaces' / source.name
    shutil.copytree(source, relocated, symlinks=True)
    executable = (relocated / 'Contents/MacOS/speak-kokoro' if sys.platform == 'darwin'
                  else relocated / ('speak-kokoro.exe' if sys.platform == 'win32' else 'speak-kokoro'))
    env = dict(os.environ, HF_HOME=str(folder / 'empty-cache'), HF_HUB_OFFLINE='1',
               TRANSFORMERS_OFFLINE='1', KOKORO_RUNTIME_DIR=str(folder / 'run'),
               VOICE='af_heart', PYTHONUTF8='1')
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    for args in (['--help'], ['--voices'], ['--self-test', '--voice', 'af_heart']):
        subprocess.run([str(executable), *args], env=env, check=True, timeout=300)
    if sys.platform != 'darwin':
        subprocess.run([str(executable), '--gui-self-test'], env=env, check=True, timeout=60)
    if sys.platform == 'win32':
        subprocess.run([str(relocated / 'Speak Kokoro.exe'), '--gui-self-test'],
                       env=env, check=True, timeout=60)
    # Exercise frozen child dispatch separately from audio-device playback.
    child = subprocess.Popen([str(executable), '--daemon'], env=env)
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and child.poll() is None:
            status = subprocess.check_output([str(executable), '--status'], env=env, text=True)
            if 'Model is running.' in status:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Packaged daemon did not become ready')
        subprocess.run([str(executable), '--quit'], env=env, check=True)
        child.wait(timeout=30)
        assert child.returncode == 0
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=30)
print('Packaged offline synthesis, relocation, daemon startup and shutdown passed.')
