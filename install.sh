#!/bin/bash
# Install speak-kokoro: local neural TTS bound to a macOS hotkey.
set -e

VENV="$HOME/.local/share/kokoro-venv"
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "==> Checking prerequisites"
command -v brew >/dev/null || { echo "Homebrew required: https://brew.sh"; exit 1; }
command -v python3 >/dev/null || { echo "python3 required"; exit 1; }

echo "==> Installing espeak-ng"
brew list espeak-ng >/dev/null 2>&1 || brew install espeak-ng

echo "==> Creating virtualenv at $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -q -r "$SRC/requirements.txt"

echo "==> Installing files"
mkdir -p "$HOME/.local/bin" "$HOME/.config"
install -m 755 "$SRC/bin/speak-kokoro" "$HOME/.local/bin/speak-kokoro"
install -m 644 "$SRC/src/kokoro_daemon.py" "$SRC/src/kokoro_menubar.py" \
  "$SRC/src/kokoro_player.py" "$VENV/"

# Anything already running is still the old code.
pkill -f kokoro_daemon.py 2>/dev/null || true
if [ -f "$HOME/Library/LaunchAgents/com.tatecarson.kokoro-tts.plist" ]; then
  pkill -f kokoro_menubar.py 2>/dev/null || true    # launchd restarts it
fi

if [ ! -f "$HOME/.config/kokoro-lexicon.json" ]; then
  install -m 644 "$SRC/config/kokoro-lexicon.json" "$HOME/.config/kokoro-lexicon.json"
fi

if [ ! -f "$HOME/.config/kokoro-tts.conf" ]; then
  printf '# Voice and speed for speak-kokoro. Managed by the menu bar app.\nVOICE=af_heart\nSPEED=1.0\n' \
    > "$HOME/.config/kokoro-tts.conf"
fi

echo "==> Installing Quick Actions"
mkdir -p "$HOME/Library/Services"
for wf in "$SRC/quickactions/"*.workflow; do
  rm -rf "$HOME/Library/Services/$(basename "$wf")"
  cp -R "$wf" "$HOME/Library/Services/"
done
/System/Library/CoreServices/pbs -flush 2>/dev/null || true
/System/Library/CoreServices/pbs -update 2>/dev/null || true

echo "==> Downloading model weights (~327 MB, first run only)"
"$HOME/.local/bin/speak-kokoro" "Installation complete."

cat <<'NEXT'

Done. Two manual steps remain:

  1. Assign hotkeys.
     System Settings > Keyboard > Keyboard Shortcuts > Services > Text
     Bind "Speak with Kokoro"  (suggested: Control-Option-S)
     Bind "Stop Kokoro Speech" (suggested: Control-Option-X)

  2. Start the menu bar app, and tick "Start at Login" in its menu:
     ~/.local/share/kokoro-venv/bin/python ~/.local/share/kokoro-venv/kokoro_menubar.py &

Select text anywhere and press your shortcut.
NEXT
