#!/bin/bash
# macOS and Linux setup. Does not require activation or sudo for Python packages.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"

case "$(uname -s)" in
  Darwin)
    command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
    brew list espeak-ng >/dev/null 2>&1 || brew install espeak-ng
    ;;
  Linux)
    command -v espeak-ng >/dev/null || {
      echo "Install eSpeak NG and PortAudio first."
      echo "Ubuntu/Debian: sudo apt install python3.12 python3.12-venv espeak-ng libportaudio2"
      echo "Fedora: sudo dnf install python3.12 espeak-ng portaudio"
      echo "Then run bash install.sh again. See README for other distributions."
      exit 1
    }
    ;;
  *) echo "Use install.ps1 on Windows."; exit 1 ;;
esac

PYTHON="${KOKORO_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; sys.exit(not ((3,10) <= sys.version_info[:2] < (3,13)))'; then
      PYTHON="$candidate"
      break
    fi
  done
fi
[ -n "$PYTHON" ] || { echo "Install Python 3.12, then retry. See README."; exit 1; }
exec "$PYTHON" "$SRC/install.py" "$@"
