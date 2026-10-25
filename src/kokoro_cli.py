"""Small command-line client. Help and playback controls never import torch."""
import argparse
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import kokoro_runtime as runtime


def validate_settings(voice, speed):
    if not re.fullmatch(r"[abefhijpz][fm]_[a-z0-9]+", voice):
        raise ValueError("Use a voice ID such as af_heart. Run --voices to list voices.")
    speed = float(speed)
    if not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
        raise ValueError("Speed must be a number between 0.5 and 2.0.")
    return voice, speed


def start_daemon(voice, timeout=600):
    from filelock import FileLock
    runtime.prepare_runtime()
    # Serialize cold starts so concurrent shortcuts cannot load duplicate models.
    with FileLock(str(runtime.RUNTIME_DIR / "startup.lock"), timeout=timeout):
        if runtime.running():
            return
        print("Loading Kokoro. The first run may download model and language files; please wait.", file=sys.stderr)
        env = dict(os.environ, VOICE=voice, PYINSTALLER_RESET_ENVIRONMENT="1")
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if runtime.WINDOWS else {"start_new_session": True}
        with runtime.LOG.open("a", encoding="utf-8") as log:
            child = subprocess.Popen(runtime.daemon_command(),
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     env=env, **kwargs)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if runtime.running():
                return
            if child.poll() is not None:
                raise RuntimeError(f"Kokoro could not start. See {runtime.LOG}")
            time.sleep(0.25)
        child.terminate()
        raise RuntimeError(f"Startup took longer than {timeout:g} seconds. Check your connection and {runtime.LOG}")


def doctor():
    import ctypes
    errors = []
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    library = runtime.configure_espeak()
    try:
        if not library:
            raise OSError("library not found")
        ctypes.CDLL(library)
        print(f"eSpeak NG: {library}")
    except OSError as exc:
        errors.append(f"eSpeak NG: {exc}. Follow the README instructions for your system.")
    try:
        import sounddevice as sd
        device = sd.query_devices(kind="output")
        sd.check_output_settings(samplerate=24000, channels=1, dtype="float32")
        print(f"Audio output: {device['name']}")
    except Exception as exc:
        errors.append(f"Audio output: {exc}. Check your default speakers; Linux also needs PortAudio.")
    print(f"Settings: {runtime.CONF}\nLog: {runtime.LOG}")
    for error in errors:
        print(error, file=sys.stderr)
    return int(bool(errors))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read text aloud locally with Kokoro." + (" Speech files are included." if runtime.BUNDLE else " First use downloads model files."))
    parser.add_argument("text", nargs="?", help="Text in quotes. With no text, read piped input.")
    parser.add_argument("--voice", help="Voice ID, such as af_heart or bm_george")
    parser.add_argument("--speed", help="Reading speed, 0.5 to 2.0; default 1.0")
    actions = parser.add_mutually_exclusive_group()
    for flag, help_text in {
        "stop": "Stop reading", "toggle": "Pause or resume; replay the last text if idle",
        "next": "Next sentence", "prev": "Previous sentence", "quit": "Unload the model",
        "voices": "List available voices" + ("" if runtime.BUNDLE else ", requires internet"), "doctor": "Check eSpeak and audio setup",
        "download": "Download and test the selected voice without playing audio",
        "self-test": "Check bundled speech generation without playing audio",
        "status": "Show whether the model is running", "paths": "Show settings and log paths",
    }.items():
        actions.add_argument("--" + flag, action="store_true", help=help_text)
    args = parser.parse_args(argv)
    if args.text is not None and any(getattr(args, k) for k in
                                    ("stop", "toggle", "next", "prev", "quit", "voices", "doctor", "download", "status", "paths", "self_test")):
        parser.error("Use text or an action, not both.")
    try:
        if args.paths:
            print(f"Settings: {runtime.CONF}\nPronunciations: {runtime.LEXICON}\nLog: {runtime.LOG}")
            return 0
        if args.doctor:
            return doctor()
        if args.status:
            print("Model is running." if runtime.running() else "Model is not running.")
            return 0
        for command in ("stop", "toggle", "next", "prev", "quit"):
            if getattr(args, command):
                if runtime.running():
                    runtime.send(command.upper())
                return 0
        if args.voices and runtime.BUNDLE:
            for path in sorted((runtime.BUNDLE / "model/voices").glob("*.pt")):
                print(path.stem)
            return 0
        if args.voices:
            from huggingface_hub import list_repo_files
            for name in sorted(list_repo_files("hexgrad/Kokoro-82M")):
                if name.startswith("voices/") and name.endswith(".pt"):
                    print(Path(name).stem)
            return 0
        cfg = runtime.read_config()
        voice, speed = validate_settings(args.voice or cfg["VOICE"], args.speed or cfg["SPEED"])
        if args.download or args.self_test:
            runtime.configure_espeak()
            print("Checking speech generation. This can take a minute.", flush=True)
            pipeline = runtime.make_pipeline(voice[0])
            samples = 0
            for result in pipeline("Kokoro is ready.", voice=runtime.voice_path(voice), speed=speed):
                samples += len(result.audio)
            if not samples:
                raise RuntimeError("The model produced no audio.")
            if args.self_test:
                from phonemizer.backend import EspeakBackend
                backend = EspeakBackend(language="en-us")
                if not backend.phonemize(["Kokoro"])[0].strip():
                    raise RuntimeError("The bundled pronunciation library produced no phonemes.")
                import sounddevice
                print(f"Speech and audio libraries loaded; generated {samples} samples without playback.")
            print(f"Ready: {voice}. You can now read text aloud.")
            return 0
        if args.text is None and sys.stdin.isatty():
            parser.print_help()
            return 0
        text = args.text if args.text is not None else sys.stdin.read()
        if not text.strip():
            return 0
        message = f"SAY {voice} {speed} {text}"
        if len(message.encode("utf-8")) > runtime.MAX_REQUEST - 128:
            raise ValueError("Text is too large; send less than 4 MB at a time.")
        start_daemon(voice)
        runtime.send(message)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"speak-kokoro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
