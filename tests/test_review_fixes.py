"""Regressions from PR review, isolated from models and the user's install."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import kokoro_cli as cli
import kokoro_runtime as runtime


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReviewFixTests(unittest.TestCase):
    def test_bom_settings_can_be_read_and_updated_without_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            conf = Path(temporary) / 'settings.conf'
            conf.write_text('VOICE=bm_george\nSPEED=1.2\nHIGHLIGHT=0\n', encoding='utf-8-sig')
            with patch.object(runtime, 'CONF', conf), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(runtime.read_config(), {'VOICE':'bm_george', 'SPEED':'1.2'})
                runtime.save_settings('af_heart', 1.1)
                self.assertEqual(runtime.read_config(), {'VOICE':'af_heart', 'SPEED':'1.1'})
            self.assertEqual(conf.read_text().count('VOICE='), 1)
            self.assertIn('HIGHLIGHT=0', conf.read_text())

    def load_daemon(self):
        import numpy  # Keep the extension loaded outside the temporary modules patch.
        with patch.object(runtime, 'configure_espeak'), \
             patch.dict(sys.modules, {'sounddevice': types.SimpleNamespace(PortAudioError=OSError)}):
            return load_file('review_daemon', ROOT / 'src/kokoro_daemon.py')

    def test_bom_lexicon_loads_pronunciation_overrides(self):
        daemon = self.load_daemon()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'lexicon.json'
            path.write_text(json.dumps({'Kokoro':'kəkˈɔːɹoʊ'}), encoding='utf-8-sig')
            with patch.object(daemon, 'LEXICON', path):
                self.assertEqual(daemon.user_lexicon(), {'Kokoro':'kəkˈɔːɹoʊ'})

    def test_missing_bundled_voice_is_rejected_before_client_starts_daemon(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(runtime, 'BUNDLE', Path(temporary)), \
             patch.object(cli, 'start_daemon') as start, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--voice','af_missing','Hello.']), 1)
            start.assert_not_called()

    def test_rejected_voice_does_not_replace_or_reconfigure_active_session(self):
        daemon = self.load_daemon()
        session = daemon.Session('af_heart', 1.0, 'Keep reading this.')
        session.audio[0] = ('cached audio', [])
        with tempfile.TemporaryDirectory() as temporary, patch.object(runtime, 'BUNDLE', Path(temporary)), \
             patch.object(daemon, 'current', session), patch.object(daemon.Session, 'run') as run:
            with self.assertRaises(ValueError):
                daemon.speak('af_missing', 1.0, 'Replacement.')
            self.assertIs(daemon.current, session)
            self.assertFalse(session.done)
            run.assert_not_called()
            with self.assertRaises(ValueError):
                session.configure('af_missing', 1.2)
            self.assertEqual((session.voice, session.speed, session.version), ('af_heart', 1.0, 0))
            self.assertIn(0, session.audio)

    def test_mac_menu_opens_even_if_service_installation_fails(self):
        import kokoro_entry
        import kokoro_desktop
        menu = types.SimpleNamespace(main=Mock())
        error = io.StringIO()
        with patch.object(sys, 'argv', ['speak-kokoro', '--menubar']), \
             patch.object(kokoro_desktop, 'install_mac_services', side_effect=OSError('Services directory is read-only')), \
             patch.dict(sys.modules, {'kokoro_menubar': menu}), contextlib.redirect_stderr(error):
            self.assertEqual(kokoro_entry.main(), 0)
            menu.main.assert_called_once_with()
        self.assertIn('optional Mac Services', error.getvalue())

    def test_failed_source_download_is_removed_and_retry_succeeds(self):
        prepare = load_file('review_prepare', ROOT / 'packaging/prepare.py')
        class BrokenResponse(io.BytesIO):
            def read(self, size=-1):
                if self.tell(): raise OSError('Connection lost')
                return super().read(3)
        with tempfile.TemporaryDirectory() as temporary:
            dest = Path(temporary) / 'source.tar.gz'
            with patch.object(prepare.urllib.request, 'urlopen', return_value=BrokenResponse(b'complete-source')):
                with self.assertRaises(OSError): prepare.download('https://example.invalid/source', dest)
            self.assertFalse(dest.exists())
            self.assertEqual(list(dest.parent.iterdir()), [])
            with patch.object(prepare.urllib.request, 'urlopen', return_value=io.BytesIO(b'complete-source')):
                prepare.download('https://example.invalid/source', dest)
            self.assertEqual(dest.read_bytes(), b'complete-source')
            with patch.object(prepare.urllib.request, 'urlopen') as download:
                prepare.download('https://example.invalid/source', dest)
                download.assert_not_called()

    def test_install_check_refuses_to_modify_local_install_from_any_directory(self):
        env = dict(os.environ)
        env.pop('CI', None)
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, str(ROOT/'tests/check_install.py')],
                                    cwd=temporary, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('may run only in CI', result.stderr)
