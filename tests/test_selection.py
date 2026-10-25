import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kokoro_selection import capture_selection, checked_text


class SelectionTests(unittest.TestCase):
    def test_empty_and_large_selections_are_rejected(self):
        for text in ('', ' \n ', None, 'x' * 1_000_001):
            with self.assertRaises(ValueError):
                checked_text(text)
        self.assertEqual(checked_text(' Selected 😀 text. '), ' Selected 😀 text. ')

    @patch('kokoro_selection.sys.platform', 'linux')
    def test_x11_reads_primary_not_clipboard(self):
        with patch.dict(os.environ, {}, clear=True), patch('subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, b'Chosen passage', b'')
            self.assertEqual(capture_selection(), 'Chosen passage')
            self.assertEqual(run.call_args.args[0], ['xclip', '-selection', 'primary', '-out', '-target', 'UTF8_STRING'])

    @patch('kokoro_selection.sys.platform', 'linux')
    def test_wayland_failure_does_not_read_stale_x11_selection(self):
        with patch.dict(os.environ, {'WAYLAND_DISPLAY':'wayland-0'}), patch('subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 1, b'', b'Unsupported')
            with self.assertRaisesRegex(ValueError, 'Wayland'):
                capture_selection()
            self.assertEqual(run.call_count, 1)
            self.assertIn('--primary', run.call_args.args[0])

    @patch('kokoro_selection.sys.platform', 'linux')
    def test_missing_reader_is_actionable(self):
        with patch('subprocess.run', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ValueError, 'package manager'):
                capture_selection()
