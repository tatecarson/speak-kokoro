"""Render the desktop UI in the Linux CI virtual display for visual review."""
import os
from pathlib import Path
import queue
import sys
import tempfile
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PIL import ImageGrab
from kokoro_gui import ReaderWindow
import kokoro_runtime as runtime


class PreviewReader:
    def __init__(self): self.events = queue.Queue()
    def read(self, *args): pass
    def control(self, *args): pass
    def configure(self, *args): pass
    def close(self): pass


assert os.environ.get('CI'), 'This screenshot helper runs only in the CI virtual display.'
with tempfile.TemporaryDirectory() as folder:
    runtime.CONF = Path(folder) / 'settings.conf'
    root = tk.Tk()
    window = ReaderWindow(root, PreviewReader())
    window.voice.set('Heart / American English')
    sample = ('Make a little room for listening.\n\n'
              'Paste an article, a few notes, or a passage you want to hear again. '
              'Choose a voice and let the words find their own pace.\n\n'
              'Everything is read on your computer. You can pause for a thought, '
              'go back a sentence, or pick up right where you left off.')
    window.text.insert('1.0', sample)
    root.update()
    output = Path('build/desktop-preview')
    output.mkdir(parents=True, exist_ok=True)
    def capture(name):
        root.update()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x+root.winfo_width(), y+root.winfo_height())).save(output/name)
    capture('reader.png')
    root.geometry('760x540')
    capture('reader-small.png')
    root.geometry('960x720')
    window.handle_event({'ev': 'start', 'id': 1, 'text': sample, 'spans': [[0, 32], [34, 100]]})
    window.handle_event({'ev': 'sentence', 'id': 1, 'i': 0})
    window.handle_event({'ev': 'word', 'id': 1, 's': 19, 'e': 22})
    capture('reader-playing.png')
    window.handle_event({'ev': 'error', 'id': 1, 'message': 'No audio output device is available.'})
    capture('reader-error.png')
    window.stop()
    window.show_toolbar()
    root.update()
    panel = window.toolbar
    x, y = panel.winfo_rootx(), panel.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x+panel.winfo_width(), y+panel.winfo_height())).save(output/'toolbar.png')
    window.close()
