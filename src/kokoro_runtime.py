"""Paths and local transport shared by the client, daemon, and Mac menu."""
import ctypes.util
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import sys

WINDOWS = sys.platform == "win32"
HOME_DIR = Path.home()
DATA_DIR = (Path(os.environ.get("LOCALAPPDATA", HOME_DIR / "AppData/Local")) / "speak-kokoro"
            if WINDOWS else HOME_DIR / ".local/share/speak-kokoro")
CONFIG_DIR = (Path(os.environ.get("APPDATA", HOME_DIR / "AppData/Roaming")) / "speak-kokoro"
              if WINDOWS else HOME_DIR / ".config")
RUNTIME_DIR = Path(os.environ.get("KOKORO_RUNTIME_DIR", DATA_DIR / "run"))
CONF = CONFIG_DIR / "kokoro-tts.conf"
LEXICON = CONFIG_DIR / "kokoro-lexicon.json"
SOCKET = RUNTIME_DIR / "tts.sock"
ENDPOINT = RUNTIME_DIR / "endpoint.json"
SPEAKING_FLAG = RUNTIME_DIR / "speaking"
LOG = RUNTIME_DIR / "daemon.log"
MAX_REQUEST = 4 * 1024 * 1024


def prepare_runtime():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not WINDOWS:
        RUNTIME_DIR.chmod(0o700)


def configure_espeak():
    """Find common eSpeak library locations without changing the user's PATH."""
    if os.environ.get("PHONEMIZER_ESPEAK_LIBRARY"):
        return os.environ["PHONEMIZER_ESPEAK_LIBRARY"]
    candidates = []
    if WINDOWS:
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if root:
                candidates.append(str(Path(root) / "eSpeak NG/libespeak-ng.dll"))
    elif sys.platform == "darwin":
        candidates = ["/opt/homebrew/lib/libespeak-ng.dylib", "/usr/local/lib/libespeak-ng.dylib"]
    for candidate in candidates:
        if Path(candidate).is_file():
            os.environ["PHONEMIZER_ESPEAK_LIBRARY"] = candidate
            return candidate
    return ctypes.util.find_library("espeak-ng") or ctypes.util.find_library("espeak")


def read_config():
    cfg = {"VOICE": "af_heart", "SPEED": "1.0"}
    try:
        for line in CONF.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() in cfg:
                cfg[key.strip()] = value.strip().strip("\"'")
    except FileNotFoundError:
        pass
    for key in cfg:
        cfg[key] = os.environ.get(key, cfg[key])
    return cfg


def listen():
    """Caller must hold the daemon lock. TCP is loopback-only on Windows."""
    prepare_runtime()
    srv = socket.socket(socket.AF_INET if WINDOWS else socket.AF_UNIX, socket.SOCK_STREAM)
    token = None
    if WINDOWS:
        srv.bind(("127.0.0.1", 0))
        token = secrets.token_hex(32)
    else:
        SOCKET.unlink(missing_ok=True)
        srv.bind(str(SOCKET))
    srv.listen(8)
    if WINDOWS:
        temp = ENDPOINT.with_suffix(".tmp")
        temp.write_text(json.dumps({"port": srv.getsockname()[1], "token": token}), encoding="utf-8")
        temp.replace(ENDPOINT)
    return srv, token


def connect(timeout=3):
    s = socket.socket(socket.AF_INET if WINDOWS else socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        if WINDOWS:
            endpoint = json.loads(ENDPOINT.read_text(encoding="utf-8"))
            s.connect(("127.0.0.1", endpoint["port"]))
            s.sendall((endpoint["token"] + "\n").encode("ascii"))
        else:
            s.connect(str(SOCKET))
        return s
    except (OSError, ValueError, KeyError, TypeError):
        s.close()
        raise


def receive(conn, token=None):
    data = bytearray()
    conn.settimeout(10)
    while chunk := conn.recv(65536):
        data.extend(chunk)
        if len(data) > MAX_REQUEST:
            raise ValueError("Text is too large; send less than 4 MB at a time.")
    if token is not None:
        auth, separator, body = bytes(data).partition(b"\n")
        if not separator or not hmac.compare_digest(auth, token.encode("ascii")):
            raise ValueError("Invalid local access token")
        data = body
    return data.decode("utf-8")


def send(message, reply=False):
    with connect() as conn:
        conn.sendall(message.encode("utf-8"))
        conn.shutdown(socket.SHUT_WR)
        return conn.recv(4096).decode("utf-8") if reply else ""


def running():
    try:
        return send("PING", reply=True) == "OK"
    except (OSError, ValueError, KeyError, TypeError):
        return False
