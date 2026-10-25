"""Check user data preservation and launchers without changing the user's install."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("installer", Path(__file__).resolve().parents[1] / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_install_preserves_user_settings_and_handles_spaces(self):
        for windows in (False, True):
            with self.subTest(windows=windows), tempfile.TemporaryDirectory(prefix="kokoro space ") as temp:
                root = Path(temp)
                config = root / "config"
                config.mkdir()
                conf = config / "kokoro-tts.conf"
                conf.write_text("VOICE=bm_george\nSPEED=1.2\n", encoding="utf-8")
                lexicon = config / "kokoro-lexicon.json"
                lexicon.write_text('{"custom": "phonemes"}', encoding="utf-8")
                venv = root / "venv"
                python = venv / ("Scripts/python.exe" if windows else "bin/python")
                patches = {"WINDOWS": windows, "CONFIG": config, "VENV": venv,
                           "BIN": root / "bin", "PYTHON": python}
                with patch.multiple(installer, **patches), patch.object(installer.sys, "platform", "win32" if windows else "linux"), \
                     patch.object(installer.venv, "EnvBuilder"), patch.object(installer, "run"), \
                     patch.object(installer, "windows_path") as path_update, contextlib.redirect_stdout(io.StringIO()):
                    installer.install()
                    self.assertEqual(conf.read_text(), "VOICE=bm_george\nSPEED=1.2\n")
                    self.assertEqual(lexicon.read_text(), '{"custom": "phonemes"}')
                    launcher = root / "bin" / ("speak-kokoro.cmd" if windows else "speak-kokoro")
                    self.assertTrue(launcher.is_file())
                    if windows:
                        self.assertIn(f'"{python}"', launcher.read_text())
                        self.assertIn('set PYTHONUTF8=1', launcher.read_text())
                        path_update.assert_called_once_with(True)
                    installer.uninstall()
                    self.assertFalse(launcher.exists())
                    self.assertTrue(conf.exists())
                    self.assertTrue(lexicon.exists())
                    installer.uninstall(purge=True)
                    self.assertFalse(conf.exists())
                    self.assertFalse(lexicon.exists())


if __name__ == "__main__":
    unittest.main()
