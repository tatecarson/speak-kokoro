"""Run the real daemon with fake speech/audio dependencies, including on Windows."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import kokoro_runtime as runtime


FAKE_KOKORO = '''
import numpy as np
from types import SimpleNamespace
class KPipeline:
    def __init__(self, **kwargs):
        self.model = True
        self.g2p = SimpleNamespace(lexicon=SimpleNamespace(golds={}))
    def __call__(self, text, **kwargs):
        yield SimpleNamespace(audio=np.ones(24000, dtype=np.float32) * 0.1, tokens=[])
'''
FAKE_AUDIO = '''
import time
class PortAudioError(Exception): pass
def query_devices(**kwargs): return {"name": "Test output"}
class OutputStream:
    latency = 0
    def __init__(self, **kwargs): pass
    def start(self): pass
    def stop(self): pass
    def close(self): pass
    def write(self, block): time.sleep(len(block) / 24000)
'''


class DaemonTests(unittest.TestCase):
    def test_start_speak_watch_stop_quit_and_restart(self):
        # A short path also stays below macOS's Unix-socket path length limit.
        with tempfile.TemporaryDirectory(prefix="kk-") as temporary:
            root = Path(temporary)
            (root / "kokoro.py").write_text(FAKE_KOKORO)
            (root / "sounddevice.py").write_text(FAKE_AUDIO)
            run = root / "r"
            src = Path(__file__).resolve().parents[1] / "src"
            env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(root), str(src)]),
                       KOKORO_RUNTIME_DIR=str(run), VOICE="af_heart")
            patches = {"RUNTIME_DIR": run, "SOCKET": run / "tts.sock", "ENDPOINT": run / "endpoint.json"}
            with patch.multiple(runtime, **patches):
                for attempt in range(2):
                    with (root / "test.log").open("w") as log:
                        child = subprocess.Popen([sys.executable, "-m", "kokoro_daemon"], env=env, stdout=log, stderr=log)
                        try:
                            deadline = time.monotonic() + 20
                            while not runtime.running() and child.poll() is None and time.monotonic() < deadline:
                                time.sleep(0.1)
                            self.assertTrue(runtime.running(), (root / "test.log").read_text())
                            # A duplicate must exit without removing the live endpoint.
                            duplicate = subprocess.run([sys.executable, "-m", "kokoro_daemon"], env=env,
                                                       capture_output=True, text=True, timeout=20)
                            self.assertNotEqual(duplicate.returncode, 0)
                            self.assertTrue(runtime.running())
                            with runtime.connect() as watcher:
                                watcher.sendall(b"WATCH")
                                watcher.shutdown(1)
                                time.sleep(0.1)
                                runtime.send("SAY af_heart 1.0 Hello there. Second sentence.")
                                with watcher.makefile("rb") as events:
                                    self.assertEqual(json.loads(events.readline())["ev"], "start")
                                    runtime.send("STOP")
                                    for _ in range(20):
                                        if json.loads(events.readline())["ev"] == "end":
                                            break
                                    else:
                                        self.fail("No playback end event")
                            runtime.send("QUIT")
                            child.wait(timeout=10)
                            self.assertEqual(child.returncode, 0)
                            self.assertFalse(runtime.running())
                        finally:
                            if child.poll() is None:
                                child.terminate()
                                child.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
