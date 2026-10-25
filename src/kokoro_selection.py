"""Read an explicit selection without replacing the user's clipboard."""
import json
import os
from pathlib import Path
import subprocess
import sys

LIMIT = 1_000_000


def checked_text(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Select some text in your document, then click Read selection.')
    if len(text) > LIMIT:
        raise ValueError('Select a shorter passage, under one million characters.')
    return text


def windows_selection():
    # This helper process owns no windows. UI Automation must use an MTA.
    sys.coinit_flags = 0
    import comtypes.client
    if not getattr(sys, 'frozen', False):
        comtypes.client.GetModule('UIAutomationCore.dll')
    from comtypes.gen import UIAutomationClient as UIA
    automation = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
    element = automation.GetFocusedElement()
    for _ in range(12):
        if not element:
            break
        if element.CurrentIsPassword:
            raise ValueError('Password fields cannot be read.')
        try:
            pattern = element.GetCurrentPattern(UIA.UIA_TextPatternId)
            pattern = pattern.QueryInterface(UIA.IUIAutomationTextPattern)
        except (comtypes.COMError, ValueError, AttributeError):
            element = automation.ControlViewWalker.GetParentElement(element)
            continue
        ranges = pattern.GetSelection()
        # A caret is an empty range. Never fall back to the entire document.
        parts = [ranges.GetElement(i).GetText(LIMIT + 1) for i in range(ranges.Length)] if ranges else []
        return checked_text('\n'.join(parts))
    raise ValueError('This app does not expose selected text to Windows accessibility. Try a text-based document in another app, or use Settings & text to read clipboard text.')


def capture_selection():
    """Called off the UI thread; each external reader has a bounded lifetime."""
    if sys.platform == 'win32':
        command = ([str(Path(sys.executable).with_name('speak-kokoro.exe')), '--capture-selection']
                   if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'kokoro_selection'])
        result = subprocess.run(command, capture_output=True, timeout=8,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'))
        try:
            payload = json.loads(result.stdout.decode('utf-8'))
        except (ValueError, UnicodeError):
            raise ValueError('Windows could not read the selection. Select text in a supported document and try again.') from None
        if 'error' in payload:
            raise ValueError(payload['error'])
        return checked_text(payload.get('text'))
    if sys.platform.startswith('linux'):
        wayland = bool(os.environ.get('WAYLAND_DISPLAY'))
        command = (['wl-paste', '--primary', '--no-newline', '--type', 'text'] if wayland else
                   ['xclip', '-selection', 'primary', '-out', '-target', 'UTF8_STRING'])
        try:
            result = subprocess.run(command, capture_output=True, timeout=3)
        except FileNotFoundError:
            raise ValueError('Selection reading needs wl-clipboard on Wayland or xclip on X11. Install it with your package manager.') from None
        if result.returncode:
            message = ('This Wayland desktop or app did not provide its primary selection. Try an X11 desktop session, or open Settings & text for clipboard reading.' if wayland else
                       'No selected text is available. Select text in your document, then click Read selection.')
            raise ValueError(message)
        return checked_text(result.stdout.decode('utf-8'))
    raise ValueError('Use the Mac Speak with Kokoro Service to read selected text.')


def protect_document_focus(window):
    """Keep clicks on the floating Windows toolbar from activating it."""
    if sys.platform != 'win32':
        return
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.CallWindowProcW.restype = ctypes.c_ssize_t
    handle = user.GetParent(window.winfo_id())
    if not handle:
        raise OSError('Could not create the selection toolbar window.')
    style = user.GetWindowLongPtrW(handle, -20)
    user.SetWindowLongPtrW(handle, -20, style | 0x08000000)  # WS_EX_NOACTIVATE
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    old = user.GetWindowLongPtrW(handle, -4)
    def dispatch(hwnd, message, wparam, lparam):
        if message == 0x21:  # WM_MOUSEACTIVATE
            return 3  # MA_NOACTIVATE: keep document focused, still deliver click
        return user.CallWindowProcW(old, hwnd, message, wparam, lparam)
    window._selection_wndproc = callback_type(dispatch)
    user.SetWindowLongPtrW(handle, -4, ctypes.cast(window._selection_wndproc, ctypes.c_void_p).value)


def worker_main():
    try:
        payload = {'text': windows_selection() if sys.platform == 'win32' else capture_selection()}
    except Exception as exc:
        payload = {'error': str(exc)}
    # ASCII JSON avoids Windows console code-page changes and preserves Unicode.
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(worker_main())
