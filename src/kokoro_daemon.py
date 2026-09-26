#!/usr/bin/env python3
"""Resident Kokoro TTS server. Keeps the model in memory so a hotkey feels instant.

Protocol over a unix socket, one message per request:
    SAY <voice> <speed> <text>
    STOP
    TOGGLE          pause or resume; replays the last text if nothing is playing
    NEXT / PREV     skip to the next sentence, or back to the previous one
    WATCH           keep the connection open and receive playback events as
                    JSON lines (see publish())
Exits after IDLE_TIMEOUT seconds with no requests.
"""
import atexit
import fcntl
import json
import os
import re
import signal
import socket
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore")

SOCKET = "/tmp/kokoro-tts.sock"
SPEAKING_FLAG = "/tmp/kokoro-speaking"
LEXICON = os.path.expanduser("~/.config/kokoro-lexicon.json")
LOCKFILE = "/tmp/kokoro-daemon.lock"
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

    Returns (start, end) spans into the original text rather than strings, so
    a listener can map what is being spoken back onto the user's selection.
    """
    spans, start = [], 0
    for m in re.finditer(r"(?<=[.!?;:])\s+", text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    spans = [strip_span(text, s, e) for s, e in spans]
    spans = [(s, e) for s, e in spans if e > s]
    if spans and len(clean(text[slice(*spans[0])])) > 90:
        s, e = spans[0]
        comma = re.search(r"(?<=,)\s+", text[s:e])
        if comma and len(clean(text[s:s + comma.start()])) >= 25:
            spans[0:1] = [(s, s + comma.start()), (s + comma.end(), e)]
    return spans


def strip_span(text, s, e):
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def trim(audio):
    """Strip the model's leading and trailing silence, leaving a small margin.

    Also returns how many samples were cut from the front, which the word
    timestamps have to be shifted by.
    """
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    loud = np.nonzero(np.abs(audio) > SILENCE_THRESHOLD)[0]
    if len(loud) == 0:
        return audio[:0], 0
    margin = int(KEEP_MARGIN * SR)
    start = max(0, loud[0] - margin)
    return audio[start:min(len(audio), loud[-1] + margin)], start


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


_stream = None
_stream_device = None
_stream_lock = threading.Lock()


def default_output():
    """Name of the current default output device, or None if unknown.

    Deliberately does NOT call sd._terminate()/_initialize() to refresh
    PortAudio's device cache: that invalidates every open stream, including
    the one we are about to write to.
    """
    try:
        return sd.query_devices(kind="output")["name"]
    except Exception:
        return None


def reset_stream():
    """Drop the shared stream so the next use reopens on the current device."""
    global _stream, _stream_device
    with _stream_lock:
        if _stream is not None:
            try:
                _stream.stop()
                _stream.close()
            except Exception:
                pass
        _stream = None
        _stream_device = None


def get_stream():
    """One output stream, reopened only when the output device changes.

    Opening and closing a CoreAudio device produces an audible pop, so cycling
    it per utterance made every sentence end with a click. While nothing is
    written the stream simply underflows, which is silent and harmless.

    A stream stays bound to the device it opened on, so plugging in headphones
    would otherwise keep sending audio to the speakers.
    """
    global _stream, _stream_device
    with _stream_lock:
        device = default_output()
        if _stream is not None and device != _stream_device:
            try:
                _stream.stop()
                _stream.close()
            except Exception:
                pass
            _stream = None
        if _stream is None:
            _stream = sd.OutputStream(samplerate=SR, channels=1,
                                      dtype="float32")
            _stream.start()
            _stream_device = device
        return _stream


def fade(audio, ms=5):
    """Ramp the edges so a chunk never starts or ends on a step."""
    n = min(int(ms * SR / 1000), len(audio) // 2)
    if n <= 0:
        return audio
    audio = audio.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    audio[:n] *= ramp
    audio[-n:] *= ramp[::-1]
    return audio


pipelines = {}
state_lock = threading.Lock()
current = None            # the Session being spoken, if any
last = None               # most recent Session, kept so TOGGLE can replay it
session_ids = 0
last_used = time.time()

AHEAD = 2                 # sentences synthesized ahead of the one playing
KEEP_BEHIND = 20          # sentences of audio kept for rewinding
RESTART_AFTER = 1.5       # seconds in; PREV before this goes back a sentence

watchers = []
watch_lock = threading.Lock()


def get_pipeline(lang):
    if lang not in pipelines:
        pipelines[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
    return pipelines[lang]


def publish(event):
    """Send one playback event to every WATCH connection, as a JSON line.

    Events, all tagged with the session "id":
        start     text, spans (sentence [start, end] offsets into text)
        sentence  i, the index into spans now playing
        word      s, e, offsets into text of the word being heard
        state     paused
        end
    A watcher that stops reading is dropped rather than stalling playback.
    """
    line = (json.dumps(event) + "\n").encode()
    with watch_lock:
        for conn in list(watchers):
            try:
                conn.sendall(line)
            except OSError:
                watchers.remove(conn)
                conn.close()


class Session:
    """One utterance: its text, sentence spans, synthesized audio and play head.

    Audio is cached per sentence, so rewinding replays instantly rather than
    running the model again, and skipping ahead only waits for the one
    sentence it lands on.
    """

    def __init__(self, voice, speed, text):
        global session_ids
        with state_lock:
            session_ids += 1
            self.id = session_ids
        self.voice, self.speed, self.text = voice, speed, text
        self.spans = segment(text)
        self.audio = {}           # sentence index -> (samples, words)
        self.pos = 0              # sentence playing
        self.offset = 0           # samples of it written so far
        self.jumps = 0            # bumped by NEXT/PREV to interrupt playback
        self.paused = False
        self.done = False
        self.word = None
        self.cond = threading.Condition()

    def event(self, ev, **fields):
        publish({"ev": ev, "id": self.id, **fields})

    def snapshot(self):
        """Events that bring a newly connected watcher up to date."""
        events = [{"ev": "start", "id": self.id, "text": self.text,
                   "spans": self.spans},
                  {"ev": "sentence", "id": self.id, "i": self.pos},
                  {"ev": "state", "id": self.id, "paused": self.paused}]
        if self.word:
            events.append({"ev": "word", "id": self.id,
                           "s": self.word[0], "e": self.word[1]})
        return events

    # --- control, called from other connections' threads --------------
    def end(self):
        with self.cond:
            self.done = True
            self.cond.notify_all()

    def toggle(self):
        with self.cond:
            self.paused = not self.paused
            paused = self.paused
            self.cond.notify_all()
        self.event("state", paused=paused)

    def seek(self, delta):
        with self.cond:
            heard = self.offset / SR - BLOCK
            if delta < 0 and heard > RESTART_AFTER:
                delta = 0                   # rewind to this sentence's start
            self.pos = max(0, min(len(self.spans), self.pos + delta))
            self.jumps += 1
            was_paused, self.paused = self.paused, False
            self.cond.notify_all()
        if was_paused:
            self.event("state", paused=False)

    # --- synthesis ------------------------------------------------------
    def synthesize(self, pipeline, i):
        """Audio for sentence i, with word timings in samples.

        Returns (samples, words) where each word is (at, s, e): the sample
        it starts on and its span in self.text.
        """
        s, e = self.spans[i]
        raw = self.text[s:e]
        pieces, words, length, cursor = [], [], 0, 0
        pause = PAUSE.get(raw[-1:], DEFAULT_PAUSE)
        if i == len(self.spans) - 1:
            pause = 0.0
        for result in pipeline(clean(raw), voice=self.voice, speed=self.speed):
            audio, cut = trim(result.audio)
            for tok in result.tokens or ():
                if tok.start_ts is None or not any(c.isalnum() for c in tok.text):
                    continue
                # Tokens carry text but no offsets, so find each one in turn.
                # Anything misaki rewrote simply goes unhighlighted.
                at = raw.find(tok.text, cursor)
                if at < 0:
                    continue
                cursor = at + len(tok.text)
                start = length + max(0, int(tok.start_ts * SR) - cut)
                words.append((start, s + at, s + cursor))
            audio = fade(audio)
            if pause:
                audio = np.concatenate([audio, np.zeros(int(pause * SR), np.float32)])
            pieces.append(audio)
            length += len(audio)
        if not words:
            words = [(0, s, e)]     # no timings (non-English): whole sentence
        samples = np.concatenate(pieces) if pieces else np.zeros(0, np.float32)
        return samples, words

    def produce(self, pipeline, mark):
        """Keep the next few sentences from the play head synthesized."""
        while True:
            with self.cond:
                while True:
                    if self.done:
                        return
                    todo = next((i for i in range(self.pos, min(
                        self.pos + AHEAD + 1, len(self.spans)))
                        if i not in self.audio), None)
                    if todo is not None:
                        break
                    self.cond.wait()
            audio = self.synthesize(pipeline, todo)
            mark(f"chunk {todo} synthesized")
            with self.cond:
                self.audio[todo] = audio
                for old in [k for k in self.audio if k < self.pos - KEEP_BEHIND]:
                    del self.audio[old]
                self.cond.notify_all()

    # --- playback -------------------------------------------------------
    def run(self, mark):
        self.event("start", text=self.text, spans=self.spans)
        pipeline = get_pipeline(self.voice[0])
        apply_lexicon(pipeline)
        threading.Thread(target=self.produce, args=(pipeline, mark),
                         daemon=True).start()
        stream = get_stream()
        open(SPEAKING_FLAG, "w").close()      # menu bar reads this for its icon
        first = True
        try:
            while True:
                with self.cond:
                    while not self.done and self.pos < len(self.spans) and (
                            self.paused or self.pos not in self.audio):
                        self.cond.wait()
                    if self.done or self.pos >= len(self.spans):
                        return
                    i, jumps = self.pos, self.jumps
                    audio, words = self.audio[i]
                    self.offset = 0
                self.event("sentence", i=i)
                if first:
                    mark("first audio out")
                    first = False
                stream = self.play(stream, audio, words, jumps)
                with self.cond:
                    if self.jumps == jumps and self.pos == i:
                        self.pos += 1
                        self.cond.notify_all()      # wake the producer
        finally:
            with self.cond:
                self.done = True
                self.cond.notify_all()
            with state_lock:
                if current is self:
                    try:
                        os.unlink(SPEAKING_FLAG)
                    except OSError:
                        pass
            self.event("end")

    def play(self, stream, audio, words, jumps):
        """Write one sentence, reporting the word being heard as it goes.

        Returns the stream, which is replaced if the device disappeared.
        """
        step = int(BLOCK * SR)
        latency = int(stream.latency * SR)
        heard_word = -1
        while True:
            with self.cond:
                while self.paused and not self.done and self.jumps == jumps:
                    self.cond.wait()
                if self.done or self.jumps != jumps or self.offset >= len(audio):
                    return stream
                off = self.offset
            block = audio[off:off + step].reshape(-1, 1)
            try:
                stream.write(block)
            except sd.PortAudioError:
                # The device went away, e.g. headphones unplugged.
                # Reopen on whatever is current and keep going.
                reset_stream()
                stream = get_stream()
                latency = int(stream.latency * SR)
                stream.write(block)
            self.offset = off + len(block)
            # What is audible now lags what was written by the buffer.
            heard = self.offset - latency
            w = heard_word
            while w + 1 < len(words) and words[w + 1][0] <= heard:
                w += 1
            if w != heard_word and w >= 0:
                heard_word = w
                self.word = words[w][1:]
                self.event("word", s=self.word[0], e=self.word[1])


def speak(voice, speed, text):
    global current, last
    t0 = time.time()

    def mark(label):
        if TIMING:
            sys.stderr.write(f"  [{(time.time() - t0) * 1000:7.0f}ms] {label}\n")
            sys.stderr.flush()

    mark("request received")
    session = Session(voice, speed, text)
    with state_lock:
        old, current = current, session
        try:
            os.unlink(SPEAKING_FLAG)
        except OSError:
            pass
    if old:
        old.end()
    if not session.spans:
        session.done = True
        return
    last = session
    session.run(mark)


def stop():
    with state_lock:
        session = current
    if session:
        session.end()


def handle(conn):
    global last_used
    data = b""
    while chunk := conn.recv(65536):
        data += chunk
    msg = data.decode("utf-8", "replace")
    last_used = time.time()
    if msg.startswith("WATCH"):
        with state_lock:
            session = current if current and not current.done else None
        conn.settimeout(1.0)
        with watch_lock:
            try:
                for event in session.snapshot() if session else ():
                    conn.sendall((json.dumps(event) + "\n").encode())
            except OSError:
                conn.close()
                return
            watchers.append(conn)
        return
    conn.close()
    with state_lock:
        session = current if current and not current.done else None
    if msg.startswith("STOP"):
        stop()
    elif msg.startswith("TOGGLE"):
        if session:
            session.toggle()
        elif last:
            speak(last.voice, last.speed, last.text)
    elif msg.startswith("NEXT") and session:
        session.seek(1)
    elif msg.startswith("PREV") and session:
        session.seek(-1)
    elif msg.startswith("SAY "):
        _, voice, speed, text = msg.split(" ", 3)
        speak(voice, float(speed), text)


def reaper():
    while True:
        time.sleep(60)
        if time.time() - last_used > IDLE_TIMEOUT:
            cleanup()
            os._exit(0)


def single_instance():
    """Refuse to start if another daemon holds the lock.

    Without this, a second daemon would unlink the first one's socket, bind its
    own, and leave two copies of a 1.5 GB model resident with the first
    orphaned. flock is released by the kernel on death, so there is no stale
    lock to clear even after a force quit.
    """
    lock = open(LOCKFILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit("kokoro daemon already running")
    return lock


def cleanup():
    global _stream
    if _stream is not None:
        try:
            _stream.stop()
            _stream.close()
        except Exception:
            pass
        _stream = None
    for path in (SOCKET, SPEAKING_FLAG):
        try:
            os.unlink(path)
        except OSError:
            pass


def main():
    lock = single_instance()          # noqa: F841  (held for process lifetime)
    atexit.register(cleanup)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: (cleanup(), os._exit(0)))
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
