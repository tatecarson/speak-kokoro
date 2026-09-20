#!/bin/bash
# Remove speak-kokoro. Leaves Homebrew's espeak-ng in place.
set -e
AGENT="$HOME/Library/LaunchAgents/com.tatecarson.kokoro-tts.plist"

pkill -f kokoro_menubar.py 2>/dev/null || true
pkill -f kokoro_daemon.py 2>/dev/null || true
[ -f "$AGENT" ] && { launchctl unload -w "$AGENT" 2>/dev/null || true; rm -f "$AGENT"; }

rm -rf "$HOME/Library/Services/Speak with Kokoro.workflow" \
       "$HOME/Library/Services/Stop Kokoro Speech.workflow"
rm -f "$HOME/.local/bin/speak-kokoro" "$HOME/.config/kokoro-tts.conf"
rm -rf "$HOME/.local/share/kokoro-venv"
rm -f /tmp/kokoro-tts.sock /tmp/kokoro-speaking /tmp/kokoro-menubar.lock

/System/Library/CoreServices/pbs -flush 2>/dev/null || true
echo "Removed. Model weights remain cached in ~/.cache/huggingface (delete manually if you want them gone)."
echo "Any keyboard shortcuts you assigned must be cleared in System Settings > Keyboard > Services."
