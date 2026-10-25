"""Exercise a separate document and the floating button on an isolated CI desktop."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import time
import tkinter as tk

assert os.environ.get('CI'), 'This integration check requires an isolated CI desktop.'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import kokoro_runtime as runtime
import kokoro_selection as selection
from kokoro_gui import ReaderWindow

SELECTED = 'Only this selected passage.'
parser = argparse.ArgumentParser()
parser.add_argument('--executable')
args = parser.parse_args()

class FakeReader:
    def __init__(self): self.events = queue.Queue(); self.readings = []
    def read(self, text, *args): self.readings.append(text)
    def close(self): pass
    def control(self, command): pass

with tempfile.TemporaryDirectory() as temporary:
    runtime.CONF = Path(temporary) / 'settings.conf'
    root = tk.Tk()
    root.withdraw()
    reader = FakeReader()
    app = ReaderWindow(root, reader)
    app.show_toolbar()
    root.update()
    sentinel = 'Clipboard stays unchanged.'
    root.clipboard_clear()
    root.clipboard_append(sentinel)
    root.update()
    document = Path(temporary) / ('document.ps1' if sys.platform == 'win32' else 'document.py')
    ready = Path(temporary) / 'ready'
    if sys.platform == 'win32':
        document.write_text('''Add-Type -AssemblyName PresentationFramework
$window = New-Object Windows.Window
$window.Title = 'Kokoro selection test document'
$window.Width = 500; $window.Height = 300
$box = New-Object Windows.Controls.TextBox
$box.Text = 'Before. Only this selected passage. After.'
$box.AcceptsReturn = $true
$window.Content = $box
$window.Add_ContentRendered({
    $window.Activate() | Out-Null
    $box.Focus() | Out-Null
    $box.Select(8, 27)
    [IO.File]::WriteAllText($args[0], 'ready')
}.GetNewClosure())
'''.replace("[IO.File]::WriteAllText($args[0], 'ready')", "[IO.File]::WriteAllText('" + str(ready).replace("'", "''") + "', 'ready')") + '$window.ShowDialog() | Out-Null\n')
        command = ['powershell', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', str(document)]
    else:
        document.write_text('''import tkinter as tk
from pathlib import Path
root = tk.Tk()
root.title('Kokoro selection test document')
root.geometry('500x300+40+60')
text = tk.Text(root)
text.pack()
text.insert('1.0', 'Before. Only this selected passage. After.')
text.tag_add('sel', '1.8', '1.35')
text.focus_force()
root.update()
Path(READY).write_text('ready')
root.mainloop()
'''.replace('READY', repr(str(ready))))
        command = [sys.executable, str(document)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 20
        while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
            root.update(); time.sleep(.05)
        assert ready.exists(), 'Test document did not open'
        # For native packages, exercise their bundled selection helper as well.
        if args.executable:
            flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
            result = subprocess.run([args.executable, '--capture-selection'], capture_output=True, timeout=15, **flags)
            assert json.loads(result.stdout)['text'] == SELECTED, result.stdout
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            user = ctypes.windll.user32
            user.GetForegroundWindow.restype = wintypes.HWND
            before = user.GetForegroundWindow()
            # Actual mouse input verifies that toolbar clicks preserve app focus.
            user.SetCursorPos(app.selection_button.winfo_rootx()+25, app.selection_button.winfo_rooty()+20)
            user.mouse_event(2, 0, 0, 0, 0)
            user.mouse_event(4, 0, 0, 0, 0)
        else:
            app.selection_button.invoke()
        deadline = time.monotonic() + 15
        while not reader.readings and time.monotonic() < deadline:
            root.update(); time.sleep(.05)
        assert reader.readings == [SELECTED], (reader.readings, app.status.get())
        assert app.content() == '', 'The document selection was copied into the large editor'
        assert root.clipboard_get() == sentinel, 'Selection reading changed the clipboard'
        if sys.platform == 'win32':
            assert user.GetForegroundWindow() == before, 'Toolbar stole document focus'
        app.stop()
        app.handle_event({'ev':'selection','request':app.capture_id-1,'text':'Stale selection'})
        assert reader.readings == [SELECTED], 'Stop allowed a late selection to restart speech'
        print('Selected passage read through floating button; document, clipboard, and cancellation preserved.')
    finally:
        app.close()
        process.terminate()
        process.communicate(timeout=10)
