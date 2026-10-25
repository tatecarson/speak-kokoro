"""No model downloads or audio hardware required; exercise real local sockets."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import kokoro_cli as cli
import kokoro_runtime as runtime


class SettingsTests(unittest.TestCase):
    def test_flags_and_environment_override_saved_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            conf = Path(directory) / "settings"
            conf.write_text('VOICE=bm_george\nSPEED=1.2\nIGNORED=$(whoami)\n', encoding='utf-8')
            with patch.object(runtime, "CONF", conf), patch.dict(os.environ, {"VOICE": "af_heart"}):
                self.assertEqual(runtime.read_config()["VOICE"], "af_heart")
                self.assertEqual(runtime.read_config()["SPEED"], "1.2")
            with patch.object(runtime, "read_config", return_value={"VOICE": "bm_george", "SPEED": "1.2"}), \
                 patch.object(cli, "start_daemon") as start, patch.object(runtime, "send") as send:
                self.assertEqual(cli.main(["--voice", "af_heart", "--speed", "1.1", "héllo"]), 0)
                start.assert_called_once_with("af_heart")
                send.assert_called_once_with("SAY af_heart 1.1 héllo")

    def test_bad_speed_and_voice_rejected_before_startup(self):
        for voice, speed in [("../voice", "1"), ("af_heart", "nan"), ("af_heart", "inf"),
                             ("af_heart", "0"), ("af_heart", "3")]:
            with self.subTest(voice=voice, speed=speed), self.assertRaises(ValueError):
                cli.validate_settings(voice, speed)

    def test_stop_does_not_start_model(self):
        with patch.object(runtime, "running", return_value=False), patch.object(cli, "start_daemon") as start:
            self.assertEqual(cli.main(["--stop"]), 0)
            start.assert_not_called()

    def test_help_does_not_import_ml_or_mac_modules(self):
        output = subprocess.check_output([sys.executable, "-c",
            "import kokoro_cli,sys; "
            "assert not any(m in sys.modules for m in ['torch','kokoro','rumps','AppKit']); "
            "kokoro_cli.main(['--paths'])"], env=dict(os.environ, PYTHONPATH=str(Path(cli.__file__).parent)), text=True)
        self.assertIn("Settings:", output)

    def test_unicode_stdin(self):
        with patch.object(sys, "stdin", io.StringIO("こんにちは\n")), \
             patch.object(cli, "start_daemon"), patch.object(runtime, "send") as send:
            self.assertEqual(cli.main([]), 0)
            self.assertTrue(send.call_args.args[0].endswith("こんにちは\n"))

    def test_doctor_fails_when_audio_is_missing(self):
        fake = types.SimpleNamespace(query_devices=lambda **kw: (_ for _ in ()).throw(OSError("no device")))
        with patch.dict(sys.modules, {"sounddevice": fake}), patch.object(runtime, "configure_espeak", return_value=None), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.doctor(), 1)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        for name, value in {"RUNTIME_DIR": directory, "SOCKET": directory / "t.sock",
                            "ENDPOINT": directory / "endpoint.json"}.items():
            patcher = patch.object(runtime, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def roundtrip(self, windows):
        with patch.object(runtime, "WINDOWS", windows):
            server, token = runtime.listen()
            received = []
            def serve():
                conn, _ = server.accept()
                with conn:
                    received.append(runtime.receive(conn, token))
                    conn.sendall(b"OK")
            thread = threading.Thread(target=serve)
            thread.start()
            try:
                self.assertEqual(runtime.send("SAY af_heart 1.0 café", reply=True), "OK")
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(received, ["SAY af_heart 1.0 café"])
            finally:
                server.close()

    @unittest.skipIf(sys.platform == 'win32', 'Unix transport is used only on macOS/Linux')
    def test_unix_transport(self):
        self.roundtrip(False)

    def test_windows_loopback_transport(self):
        self.roundtrip(True)

    def test_unauthorized_tcp_message_is_rejected(self):
        with patch.object(runtime, "WINDOWS", True):
            server, token = runtime.listen()
            try:
                endpoint = json.loads(runtime.ENDPOINT.read_text())
                with socket.create_connection(("127.0.0.1", endpoint["port"])) as client:
                    client.sendall(b"wrong-token\nQUIT")
                    client.shutdown(socket.SHUT_WR)
                    conn, _ = server.accept()
                    with conn, self.assertRaises(ValueError):
                        runtime.receive(conn, token)
            finally:
                server.close()

    def test_stale_endpoint_is_not_running(self):
        with patch.object(runtime, "WINDOWS", True):
            runtime.ENDPOINT.write_text("{}")
            self.assertFalse(runtime.running())


class InstallerTests(unittest.TestCase):
    def test_packaged_dependencies_exclude_mac_libraries_elsewhere(self):
        from importlib.metadata import requires
        from packaging.requirements import Requirement
        dependencies = [Requirement(s) for s in requires("speak-kokoro")]
        for platform in ("linux", "win32"):
            enabled = [r.name for r in dependencies if r.marker is None or r.marker.evaluate({"sys_platform": platform})]
            self.assertNotIn("rumps", enabled)
            self.assertNotIn("pyobjc-framework-ApplicationServices", enabled)
        self.assertTrue(any(r.name == 'kokoro' for r in dependencies))


if __name__ == "__main__":
    unittest.main()

class FrozenCommandTests(unittest.TestCase):
    def test_frozen_processes_reenter_the_executable(self):
        with patch.object(runtime, 'BUNDLE', Path('/bundle')):
            self.assertEqual(runtime.client_command(), [sys.executable])
            self.assertEqual(runtime.daemon_command(), [sys.executable, '--daemon'])
            self.assertEqual(runtime.menu_command(), [sys.executable, '--menubar'])

    def test_missing_bundled_voice_is_an_error_instead_of_a_download(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runtime, 'BUNDLE', Path(temp)):
            with self.assertRaises(ValueError):
                runtime.voice_path('af_missing')

    def test_long_pronunciation_data_path_is_copied_to_a_short_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / ('long-install-folder-' * 6) / 'espeak-ng-data'
            data.mkdir(parents=True)
            (data / 'phontab').write_bytes(b'pronunciation-data')
            loader = types.SimpleNamespace(get_library_path=lambda: '/bundle/espeak',
                                           get_data_path=lambda: str(data))
            with patch.dict(sys.modules, {'espeakng_loader': loader}), \
                 patch.dict(os.environ, {}, clear=False), \
                 patch.object(runtime, 'BUNDLE', Path(temp)), \
                 patch.object(runtime, '_ESPEAK_TEMP', None):
                try:
                    runtime.configure_espeak()
                    relocated = Path(loader.get_data_path())
                    self.assertLess(len(os.fsencode(relocated)), 140)
                    self.assertEqual((relocated / 'phontab').read_bytes(), b'pronunciation-data')
                    self.assertEqual(os.environ['PHONEMIZER_ESPEAK_DATA_PATH'], str(relocated))
                    runtime.configure_espeak()
                    self.assertEqual(Path(loader.get_data_path()), relocated)
                finally:
                    if runtime._ESPEAK_TEMP:
                        runtime._ESPEAK_TEMP.cleanup()
