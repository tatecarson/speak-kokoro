#!/usr/bin/env python3
"""Menu bar companion for speak-kokoro.

Deliberately lightweight: it never imports torch, it only talks to the
synthesis daemon over its unix socket. The heavy model stays on demand.
"""
import fcntl
import json
import os
import socket
import subprocess
import threading
import time

import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
from AppKit import NSPasteboard, NSPasteboardTypeString
from AppKit import (NSEventModifierFlagCommand, NSEventModifierFlagControl,
                    NSEventModifierFlagOption, NSEventModifierFlagShift)
from PyObjCTools import AppHelper

import kokoro_player

SOCK = "/tmp/kokoro-tts.sock"
CONF = os.path.expanduser("~/.config/kokoro-tts.conf")
SPEAK = os.path.expanduser("~/.local/bin/speak-kokoro")
AGENT = os.path.expanduser("~/Library/LaunchAgents/com.tatecarson.kokoro-tts.plist")

IDLE, BUSY = "○)", "●)"     # ○) and ●)


MOD_CHARS = {
    "^": NSEventModifierFlagControl,
    "~": NSEventModifierFlagOption,
    "$": NSEventModifierFlagShift,
    "@": NSEventModifierFlagCommand,
}


def bound_shortcut(service_name):
    """Return (key, mask) for a Quick Action's shortcut, or None if unbound.

    Read live from macOS rather than hardcoded, so the menu can never claim a
    shortcut the user has not actually assigned.
    """
    try:
        out = subprocess.run(
            ["defaults", "read", "pbs", "NSServicesStatus"],
            capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    block = None
    for chunk in out.split("}"):
        if service_name in chunk and "key_equivalent" in chunk:
            block = chunk
            break
    if not block:
        return None
    for line in block.splitlines():
        if "key_equivalent" in line and "=" in line:
            raw = line.split("=", 1)[1].strip().strip(';').strip('"')
            mask, key = 0, ""
            for ch in raw:
                if ch in MOD_CHARS:
                    mask |= MOD_CHARS[ch]
                else:
                    key = ch
            if key:
                return key, mask
    return None


def show_shortcut(item, service_name):
    """Show the service's real shortcut beside the item, if one is assigned."""
    found = bound_shortcut(service_name)
    if found:
        key, mask = found
        item._menuitem.setKeyEquivalent_(key)
        item._menuitem.setKeyEquivalentModifierMask_(mask)
    return item


def read_conf():
    cfg = {"VOICE": "af_heart", "SPEED": "1.0", "CONTROLS": "1", "HIGHLIGHT": "1"}
    try:
        with open(CONF) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    except OSError:
        pass
    return cfg


def write_conf(cfg):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF, "w") as fh:
        fh.write("# Voice and speed for speak-kokoro. Managed by the menu bar app.\n")
        fh.write(f"VOICE={cfg['VOICE']}\nSPEED={cfg['SPEED']}\n")
        fh.write(f"CONTROLS={cfg['CONTROLS']}\nHIGHLIGHT={cfg['HIGHLIGHT']}\n")


def send(cmd):
    """Send a playback command straight to the daemon, if it is running."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(SOCK)
            s.sendall(cmd.encode())
    except OSError:
        pass


def daemon_loaded():
    return os.path.exists(SOCK) and bool(
        subprocess.run(["pgrep", "-f", "kokoro_daemon.py"],
                       capture_output=True).stdout.strip()
    )


def speaking():
    """The daemon writes this flag while audio is actually playing."""
    return os.path.exists("/tmp/kokoro-speaking") and daemon_loaded()


def clipboard_text():
    pb = NSPasteboard.generalPasteboard()
    return pb.stringForType_(NSPasteboardTypeString) or ""


class KokoroApp(rumps.App):
    def __init__(self):
        super().__init__("Kokoro", title=IDLE, quit_button=None)
        self.cfg = read_conf()
        self.loading = False
        self.status = rumps.MenuItem("Model: checking…", callback=None)
        self.player = kokoro_player.Player(send, self.cfg,
                                           lambda: write_conf(self.cfg))
        self.build_menu()
        threading.Thread(target=self.watch, daemon=True).start()
        threading.Thread(target=self.listen, daemon=True).start()

    def build_menu(self):
        speak_sel = show_shortcut(
            rumps.MenuItem("Select text anywhere, then press"),
            "Speak with Kokoro")
        stop_sel = show_shortcut(
            rumps.MenuItem("Stop Speaking", callback=self.stop),
            "Stop Kokoro Speech")
        speak_sel._menuitem.setEnabled_(False)

        self.menu = [
            speak_sel,
            stop_sel,
            rumps.MenuItem("Speak Clipboard", callback=self.speak_clipboard),
            rumps.MenuItem("Open Reading Panel", callback=self.open_panel),
            None,
            rumps.MenuItem("Show Panel When Reading", callback=self.toggle_controls),
            rumps.MenuItem("Highlight Words in Document",
                           callback=self.toggle_highlight),
            None,
            self.status,
            rumps.MenuItem("Start Model", callback=self.preload),
            rumps.MenuItem("Stop Model", callback=self.unload),
            None,
            rumps.MenuItem("Start at Login", callback=self.toggle_login),
            None,
            rumps.MenuItem("Quit", callback=rumps.quit_application, key="q"),
        ]
        self.mark_checks()

    def mark_checks(self):
        self.menu["Start at Login"].state = os.path.exists(AGENT)
        controls = self.cfg["CONTROLS"] == "1"
        # Only claim highlighting is on once macOS actually allows it.
        highlight = self.cfg["HIGHLIGHT"] == "1" and kokoro_player.ax_available()
        self.menu["Show Panel When Reading"].state = controls
        self.menu["Highlight Words in Document"].state = highlight
        self.player.set_options(controls, highlight)

    # --- actions -------------------------------------------------------
    def open_panel(self, _):
        self.player.open()

    def toggle_controls(self, sender):
        self.cfg["CONTROLS"] = "0" if sender.state else "1"
        write_conf(self.cfg)
        self.mark_checks()

    def toggle_highlight(self, sender):
        if sender.state:
            self.cfg["HIGHLIGHT"] = "0"
        else:
            self.cfg["HIGHLIGHT"] = "1"
            if not kokoro_player.ax_available():
                kokoro_player.ask_for_accessibility()
                rumps.alert(
                    "Accessibility permission needed",
                    "Highlighting finds the words on screen through macOS "
                    "Accessibility. Allow Python in System Settings > Privacy "
                    "& Security > Accessibility, then choose this item again.")
        write_conf(self.cfg)
        self.mark_checks()

    def say(self, text):
        subprocess.run([SPEAK, text])

    def speak_clipboard(self, _):
        text = clipboard_text().strip()
        if not text:
            # rumps.notification is silently dropped for an unbundled app;
            # NSAlert works regardless of bundle identity.
            rumps.alert("Nothing to speak", "The clipboard is empty.")
            return
        threading.Thread(target=self.say, args=(text,), daemon=True).start()

    def stop(self, _):
        subprocess.run([SPEAK, "--stop"])

    def unload(self, _):
        if self.loading:
            return
        subprocess.run([SPEAK, "--quit"])

    def preload(self, _):
        # Loading takes ~5 s, far longer than the 1 s state poll, so disable the
        # item here rather than waiting for the watcher to notice.
        if self.loading or daemon_loaded():
            return
        self.loading = True
        self.menu["Start Model"].set_callback(None)
        self.status.title = "Model: loading…"

        def run():
            try:
                self.say("Ready.")
            finally:
                self.loading = False

        threading.Thread(target=run, daemon=True).start()

    def toggle_login(self, sender):
        if os.path.exists(AGENT):
            subprocess.run(["launchctl", "unload", "-w", AGENT],
                           capture_output=True)
            os.remove(AGENT)
        else:
            os.makedirs(os.path.dirname(AGENT), exist_ok=True)
            with open(AGENT, "w") as fh:
                fh.write(PLIST)
            subprocess.run(["launchctl", "load", "-w", AGENT],
                           capture_output=True)
        sender.state = os.path.exists(AGENT)

    # --- state watcher -------------------------------------------------
    def listen(self):
        """Follow the daemon's playback events and hand them to the player.

        The daemon comes and goes, so keep trying to reconnect. Connecting
        does not start it.
        """
        while True:
            heard = False
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.connect(SOCK)
                    s.sendall(b"WATCH")
                    s.shutdown(socket.SHUT_WR)
                    for line in s.makefile("rb"):
                        heard = True
                        AppHelper.callAfter(self.player.handle, json.loads(line))
            except (OSError, ValueError):
                pass
            if heard:       # daemon quit, perhaps mid-sentence
                AppHelper.callAfter(self.player.handle, {"ev": "gone"})
            time.sleep(1)

    def watch(self):
        while True:
            self.title = BUSY if speaking() else IDLE
            loaded = daemon_loaded()
            if self.loading:
                self.status.title = "Model: loading…"
            else:
                self.status.title = ("Model: loaded (1.5 GB)" if loaded
                                     else "Model: not loaded")
            busy = loaded or self.loading
            self.menu["Stop Model"].set_callback(
                self.unload if (loaded and not self.loading) else None)
            self.menu["Start Model"].set_callback(None if busy else self.preload)
            time.sleep(1)


PLIST = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.tatecarson.kokoro-tts</string>
    <key>ProgramArguments</key>
    <array>
        <string>{os.path.expanduser('~/.local/share/kokoro-venv/bin/python')}</string>
        <string>{os.path.expanduser('~/.local/share/kokoro-venv/kokoro_menubar.py')}</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardErrorPath</key><string>/tmp/kokoro-menubar.log</string>
</dict>
</plist>
"""

def _single_instance():
    """Abort if another copy is already in the menu bar.

    launchd (Start at Login) and a manual launch can otherwise each put an
    icon up. flock is released by the kernel when the process dies, so there
    is no stale lock to clean up, unlike a pidfile.
    """
    lock = open("/tmp/kokoro-menubar.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit("kokoro menubar already running")
    return lock


if __name__ == "__main__":
    _lock = _single_instance()
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory)      # no Dock icon
    KokoroApp().run()
