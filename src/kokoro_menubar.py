#!/usr/bin/env python3
"""Menu bar companion for speak-kokoro.

Deliberately lightweight: it never imports torch, it only talks to the
synthesis daemon over its unix socket. The heavy model stays on demand.
"""
import fcntl
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

SOCK = "/tmp/kokoro-tts.sock"
CONF = os.path.expanduser("~/.config/kokoro-tts.conf")
SPEAK = os.path.expanduser("~/.local/bin/speak-kokoro")
AGENT = os.path.expanduser("~/Library/LaunchAgents/com.tatecarson.kokoro-tts.plist")

VOICES = {
    "US female": "af_heart af_bella af_nicole af_sarah af_sky af_alloy af_aoede "
                 "af_jessica af_kore af_nova af_river".split(),
    "US male": "am_michael am_adam am_echo am_eric am_fenrir am_liam am_onyx "
               "am_puck am_santa".split(),
    "UK female": "bf_emma bf_alice bf_isabella bf_lily".split(),
    "UK male": "bm_george bm_daniel bm_fable bm_lewis".split(),
}
SPEEDS = ["0.9", "1.0", "1.1", "1.2", "1.3", "1.5"]

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
    cfg = {"VOICE": "af_heart", "SPEED": "1.0"}
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
        self.status = rumps.MenuItem("Model: checking…", callback=None)
        self.build_menu()
        threading.Thread(target=self.watch, daemon=True).start()

    def build_menu(self):
        voice_menu = []
        for group, names in VOICES.items():
            items = [rumps.MenuItem(n, callback=self.pick_voice) for n in names]
            voice_menu.append([rumps.MenuItem(group), items])
        speed_items = [rumps.MenuItem(s, callback=self.pick_speed) for s in SPEEDS]

        speak_sel = show_shortcut(
            rumps.MenuItem("Speak Selection", callback=self.explain_hotkey),
            "Speak with Kokoro")
        stop_sel = show_shortcut(
            rumps.MenuItem("Stop Speaking", callback=self.stop),
            "Stop Kokoro Speech")

        self.menu = [
            speak_sel,
            stop_sel,
            rumps.MenuItem("Speak Clipboard", callback=self.speak_clipboard),
            None,
            [rumps.MenuItem("Voice"), voice_menu],
            [rumps.MenuItem("Speed"), speed_items],
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
        for group in VOICES:
            for item in self.menu["Voice"][group].values():
                item.state = item.title == self.cfg["VOICE"]
        for item in self.menu["Speed"].values():
            item.state = item.title == self.cfg["SPEED"]
        self.menu["Start at Login"].state = os.path.exists(AGENT)

    # --- actions -------------------------------------------------------
    def pick_voice(self, sender):
        self.cfg["VOICE"] = sender.title
        write_conf(self.cfg)
        self.mark_checks()
        threading.Thread(
            target=lambda: self.say(f"This is {sender.title.split('_')[1]}."),
            daemon=True).start()

    def pick_speed(self, sender):
        self.cfg["SPEED"] = sender.title
        write_conf(self.cfg)
        self.mark_checks()

    def say(self, text):
        subprocess.run([SPEAK, text])

    def speak_clipboard(self, _):
        text = clipboard_text().strip()
        if not text:
            rumps.notification("Kokoro", "Nothing to speak",
                               "The clipboard is empty.")
            return
        threading.Thread(target=self.say, args=(text,), daemon=True).start()

    def explain_hotkey(self, _):
        rumps.notification(
            "Kokoro", "Speak Selection",
            "Select text in any app, then press \u2303\u2325S. "
            "Or use Speak Clipboard from this menu.")

    def stop(self, _):
        subprocess.run([SPEAK, "--stop"])

    def unload(self, _):
        subprocess.run([SPEAK, "--quit"])

    def preload(self, _):
        threading.Thread(target=self.say, args=("Ready.",), daemon=True).start()

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
    def watch(self):
        while True:
            self.title = BUSY if speaking() else IDLE
            loaded = daemon_loaded()
            self.status.title = ("Model: loaded (1.5 GB)" if loaded
                                 else "Model: not loaded")
            self.menu["Stop Model"].set_callback(self.unload if loaded else None)
            self.menu["Start Model"].set_callback(None if loaded else self.preload)
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
