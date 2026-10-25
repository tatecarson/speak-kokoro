#!/bin/bash
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
# Use the system interpreter because uninstall removes the app's environment.
exec "${KOKORO_PYTHON:-python3}" "$SRC/install.py" --uninstall "$@"
