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
BUNDLE = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else None


def configure_audio():
    """sounddevice's Linux lookup must find our bundled PortAudio without ldconfig."""
    if BUNDLE and sys.platform.startswith("linux"):
        original = ctypes.util.find_library
        portaudio = str(BUNDLE / "libportaudio.so.2")
        ctypes.util.find_library = lambda name: portaudio if name == "portaudio" else original(name)


def client_command():
    return [sys.executable] if BUNDLE else [sys.executable, "-m", "kokoro_cli"]


def daemon_command():
    return [sys.executable, "--daemon"] if BUNDLE else [sys.executable, "-m", "kokoro_daemon"]


def menu_command():
    return [sys.executable, "--menubar"] if BUNDLE else [sys.executable, "-m", "kokoro_menubar"]


def make_pipeline(lang, shared=None):
    from kokoro import KPipeline
    model = shared if shared is not None else True
    if BUNDLE and shared is None:
        from kokoro import KModel
        model = KModel(repo_id="hexgrad/Kokoro-82M",
                       config=str(BUNDLE / "model/config.json"),
                       model=str(BUNDLE / "model/kokoro-v1_0.pth")).to("cpu").eval()
    return KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", model=model, device="cpu")


def voice_path(voice):
    if BUNDLE:
        path = BUNDLE / "model/voices" / (voice + ".pt")
        if not path.is_file():
            raise ValueError(f"Voice {voice!r} is not included. Run --voices for available voices.")
        return str(path)
    return voice


def prepare_runtime():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not WINDOWS:
        RUNTIME_DIR.chmod(0o700)


def configure_espeak():
    """Find common eSpeak library locations without changing the user's PATH."""
    if os.environ.get("PHONEMIZER_ESPEAK_LIBRARY"):
        return os.environ["PHONEMIZER_ESPEAK_LIBRARY"]
    # The packaged app includes the same eSpeak library and data used by Misaki.
    if BUNDLE:
        import espeakng_loader
        library = espeakng_loader.get_library_path()
        os.environ["PHONEMIZER_ESPEAK_LIBRARY"] = library
        os.environ["PHONEMIZER_ESPEAK_DATA_PATH"] = espeakng_loader.get_data_path()
        return library
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
