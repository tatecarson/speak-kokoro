"""Desktop client integration against the real daemon with fake audio hardware."""
import contextlib
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import kokoro_runtime as runtime
import kokoro_controller as desktop
from test_daemon import FAKE_AUDIO, FAKE_KOKORO


class ReaderTests(unittest.TestCase):
    def test_preferences_preserve_other_settings_and_reject_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.conf'
            path.write_text('# Custom settings\nVOICE=af_heart\nSPEED=1\nHIGHLIGHT=0\n', encoding='utf-8')
            with patch.object(runtime, 'CONF', path):
                runtime.save_settings('bm_george', 1.2)
                self.assertEqual(path.read_text(), '# Custom settings\nVOICE=bm_george\nSPEED=1.2\nHIGHLIGHT=0\n')
                with self.assertRaises(ValueError):
                    runtime.save_settings('af_heart', float('nan'))
                self.assertIn('SPEED=1.2', path.read_text())

    def test_stop_cancels_loading_before_a_read_is_submitted(self):
        entered = threading.Event()
        cancelled = threading.Event()
        def startup(voice, cancel_event):
            entered.set()
            if cancel_event.wait(3):
                cancelled.set()
                raise InterruptedError()
            raise RuntimeError('Cancellation did not arrive')
        with patch.object(desktop, 'start_daemon', side_effect=startup), \
             patch.object(desktop.ReaderController, '_watch'), \
             patch.object(desktop.ReaderController, '_send') as send:
            reader = desktop.ReaderController()
            try:
                reader.read('Read this.', 'af_heart', 1)
                self.assertTrue(entered.wait(3))
                reader.control('STOP')
                self.assertTrue(cancelled.wait(3))
            finally:
                reader.close()
            self.assertFalse(any(call.args[0].startswith('SAY ') for call in send.call_args_list))

    def wait_event(self, reader, kind, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = reader.events.get(timeout=0.25)
            except queue.Empty:
                continue
            if event['ev'] == 'client_error':
                self.fail(event['message'])
            if event['ev'] == kind:
                return event
        self.fail(f'Timed out waiting for {kind}')

    @contextlib.contextmanager
    def backend(self, broken_audio=False, broken_speech=False):
        with tempfile.TemporaryDirectory(prefix='kr-') as folder:
            root = Path(folder)
            kokoro = FAKE_KOKORO
            if broken_speech:
                kokoro = kokoro.replace('yield SimpleNamespace',
                    'if text != "Ready.": raise RuntimeError("Speech test failure")\n        yield SimpleNamespace')
            (root / 'kokoro.py').write_text(kokoro)
            audio = FAKE_AUDIO
            if broken_audio:
                audio = audio.replace('def start(self): pass', 'def start(self): raise PortAudioError("No audio output")')
            (root / 'sounddevice.py').write_text(audio)
            run = root / 'r'
            src = Path(__file__).resolve().parents[1] / 'src'
            with patch.dict(os.environ, {'PYTHONPATH': os.pathsep.join([str(root), str(src)]),
                                         'KOKORO_RUNTIME_DIR': str(run), 'VOICE': 'af_heart'}), \
                 patch.multiple(runtime, RUNTIME_DIR=run, SOCKET=run/'tts.sock',
                                ENDPOINT=run/'endpoint.json', LOG=run/'daemon.log'):
                reader = desktop.ReaderController()
                try:
                    yield reader
                finally:
                    reader.close()
                    deadline = time.monotonic() + 5
                    while runtime.running() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertFalse(runtime.running())

    def test_read_pause_resume_settings_stop_and_close(self):
        with self.backend() as reader:
            reader.read('Hello there. Read the next sentence.', 'af_heart', 1)
            self.assertIn('Hello', self.wait_event(reader, 'start')['text'])
            reader.control('TOGGLE')
            self.assertTrue(self.wait_event(reader, 'state')['paused'])
            reader.configure('bm_george', 1.2)
            reader.control('TOGGLE')
            self.assertFalse(self.wait_event(reader, 'state')['paused'])
            reader.control('STOP')
            self.wait_event(reader, 'end')

    def test_audio_and_synthesis_errors_reach_the_window(self):
        for audio, speech in ((True, False), (False, True)):
            with self.subTest(audio=audio, speech=speech), self.backend(audio, speech) as reader:
                reader.read('Hello there.', 'af_heart', 1)
                event = self.wait_event(reader, 'error')
                self.assertIn('No audio' if audio else 'Speech test failure', event['message'])
                self.wait_event(reader, 'end')
