#!/usr/bin/env python3
"""Resident Kokoro TTS server. Keeps the model in memory so a hotkey feels instant.

Protocol over a unix socket, one message per request:
    SAY <voice> <speed> <text>
    STOP
Exits after IDLE_TIMEOUT seconds with no requests.
"""
import json
import os
import queue
import re
import socket
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore")

SOCKET = "/tmp/kokoro-tts.sock"
SPEAKING_FLAG = "/tmp/kokoro-speaking"
LEXICON = os.path.expanduser("~/.config/kokoro-lexicon.json")
IDLE_TIMEOUT = float(os.environ.get("KOKORO_IDLE_TIMEOUT", 10800))
SR = 24000
TIMING = bool(os.environ.get("KOKORO_TIMING"))

import numpy as np
import sounddevice as sd
from kokoro import KPipeline

# Pause inserted after a chunk, by the punctuation that ended it. Kokoro bakes
# ~0.78s of silence into every chunk; we strip that and put back something
# closer to natural speech.
PAUSE = {".": 0.26, "!": 0.26, "?": 0.26, ";": 0.20, ":": 0.20, ",": 0.09}
DEFAULT_PAUSE = 0.14
SILENCE_THRESHOLD = 0.01
KEEP_MARGIN = 0.02        # seconds of silence to leave on each side
BLOCK = 0.08              # seconds per write, bounds how fast STOP responds


def segment(text):
    """Split text into short chunks, first one shortest.

    Kokoro only splits on newlines, so a selected paragraph would otherwise be
    synthesized in full before any audio plays. We break at sentence ends, and
    clip only the opening chunk at a comma so speech starts sooner without
    peppering the rest of the text with comma breaks.
    """
    text = re.sub(r"\s+", " ", text).strip()
    parts = [p for p in re.split(r"(?<=[.!?;:])\s+", text) if p]
    if parts and len(parts[0]) > 90:
        head = re.split(r"(?<=,)\s+", parts[0], maxsplit=1)
        if len(head) == 2 and len(head[0]) >= 25:
            parts = head + parts[1:]
    return parts


def trim(audio):
    """Strip the model's leading and trailing silence, leaving a small margin."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    loud = np.nonzero(np.abs(audio) > SILENCE_THRESHOLD)[0]
    if len(loud) == 0:
        return audio[:0]
    margin = int(KEEP_MARGIN * SR)
    return audio[max(0, loud[0] - margin):min(len(audio), loud[-1] + margin)]


_lexicon = {"mtime": None, "data": {}}


def user_lexicon():
    """Pronunciation overrides, reloaded whenever the file changes.

    misaki ships some wrong entries (e.g. "imagines" as the Latin plural
    "-ineez"), and they are stored as golds so nothing else overrides them.
    A bad JSON edit keeps the last good copy rather than breaking speech.
    """
    try:
        mtime = os.path.getmtime(LEXICON)
    except OSError:
        return _lexicon["data"]
    if _lexicon["mtime"] != mtime:
        try:
            with open(LEXICON) as fh:
                loaded = json.load(fh)
            _lexicon["data"] = {k: v for k, v in loaded.items()
                                if not k.startswith("_")}
            _lexicon["mtime"] = mtime
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"lexicon ignored ({exc})\n")
            sys.stderr.flush()
    return _lexicon["data"]


def apply_lexicon(pipeline):
    golds = pipeline.g2p.lexicon.golds
    for word, phonemes in user_lexicon().items():
        # misaki looks up case variants separately, so a sentence-initial
        # capital would otherwise still hit the entry we are overriding.
        for variant in {word, word.lower(), word.capitalize(), word.upper()}:
            golds[variant] = phonemes


pipelines = {}
state_lock = threading.Lock()
generation = 0
last_used = time.time()


def get_pipeline(lang):
    if lang not in pipelines:
        pipelines[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
    return pipelines[lang]


def new_generation():
    """Invalidate any in-flight speech and return the new generation id."""
    global generation
    with state_lock:
        generation += 1
        try:
            os.unlink(SPEAKING_FLAG)
        except OSError:
            pass
        return generation


def current_generation():
    with state_lock:
        return generation


def speak(voice, speed, text):
    gen = new_generation()
    t0 = time.time()

    def mark(label):
        if TIMING:
            sys.stderr.write(f"  [{(time.time() - t0) * 1000:7.0f}ms] {label}\n")
            sys.stderr.flush()

    mark("request received")
    chunks = segment(text)
    if not chunks:
        return
    pipeline = get_pipeline(voice[0])
    apply_lexicon(pipeline)
    audio_q = queue.Queue(maxsize=4)

    def produce():
        try:
            for i, chunk in enumerate(chunks):
                if current_generation() != gen:
                    break
                for _, _, audio in pipeline(chunk, voice=voice, speed=speed):
                    mark(f"chunk {i} synthesized")
                    pause = PAUSE.get(chunk.strip()[-1:], DEFAULT_PAUSE)
                    if i == len(chunks) - 1:
                        pause = 0.0
                    audio_q.put((trim(audio), pause))
        finally:
            audio_q.put(None)

    threading.Thread(target=produce, daemon=True).start()

    stream = sd.OutputStream(samplerate=SR, channels=1, dtype="float32")
    stream.start()
    open(SPEAKING_FLAG, "w").close()      # menu bar reads this for its icon
    first = True
    try:
        while True:
            item = audio_q.get()
            if item is None or current_generation() != gen:
                break
            audio, pause = item
            if pause:
                audio = np.concatenate([audio, np.zeros(int(pause * SR), np.float32)])
            if first:
                mark("first audio out")
                first = False
            step = int(BLOCK * SR)
            for off in range(0, len(audio), step):
                if current_generation() != gen:
                    return
                stream.write(audio[off:off + step].reshape(-1, 1))
    finally:
        if current_generation() == gen:
            stream.stop()
        else:
            stream.abort()
        stream.close()
        if current_generation() == gen:
            try:
                os.unlink(SPEAKING_FLAG)
            except OSError:
                pass


def handle(conn):
    global last_used
    with conn:
        data = b""
        while chunk := conn.recv(65536):
            data += chunk
        msg = data.decode("utf-8", "replace")
    last_used = time.time()
    if msg.startswith("STOP"):
        new_generation()
        return
    if not msg.startswith("SAY "):
        return
    _, voice, speed, text = msg.split(" ", 3)
    speak(voice, float(speed), text)


def reaper():
    while True:
        time.sleep(60)
        if time.time() - last_used > IDLE_TIMEOUT:
            try:
                os.unlink(SOCKET)
            except OSError:
                pass
            os._exit(0)


def main():
    if os.path.exists(SOCKET):
        os.unlink(SOCKET)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET)
    srv.listen(8)
    warm = os.environ.get("VOICE", "af_heart")
    pl = get_pipeline(warm[0])
    for _ in pl("Ready.", voice=warm, speed=1.0):     # force first inference
        break
    sys.stderr.write("kokoro daemon ready\n")
    sys.stderr.flush()
    threading.Thread(target=reaper, daemon=True).start()
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
