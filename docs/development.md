# Development notes

The timings and memory figures below are observations from the original Apple Silicon implementation, not guarantees for every computer.

## How it is put together

Three pieces, split by how much memory they need to hold.

| Component | Resident | Lifetime |
|---|---|---|
| Menu bar app | 80 MB | Always, from login |
| Model daemon | 1.5 GB | On demand, exits after 3 h idle |
| Client script | none | Per invocation |

A cold load of torch plus Kokoro costs about 5 seconds, which is unusable on a
hotkey. So the model lives in a daemon behind a local connection and the hotkey runs
a thin client that returns in about 50 ms. The daemon releases its memory after
three hours of silence, which on a 16 GB machine matters.

The menu bar app deliberately never imports torch. It only talks to the socket,
which is why it costs 80 MB rather than 1.5 GB and can sit in your bar all day.

## Audio processing notes

Both cost real debugging time, and neither is documented prominently upstream.

**Kokoro's default `split_pattern` is `\n+`.** It splits on newlines and nothing
else. A selected paragraph has no newlines, so the naive implementation
synthesizes your entire selection before playing a single word. Latency scales
with how much text you picked. The daemon segments on sentence boundaries
itself, and clips the opening chunk at a comma, which puts first audio at about
560 ms regardless of selection length.

**Kokoro bakes roughly 0.78 s of silence into every chunk**, about 0.31 s
leading and 0.47 s trailing. This is invisible when the whole passage is one
chunk. The moment you segment for latency, that padding lands at every
punctuation mark and the result sounds broken. The daemon trims to a 20 ms
margin and inserts its own pause sized to the punctuation. On a three-sentence
paragraph this removes 2.47 s of dead air, 26% of total length, without clipping
any speech.

The two interact: fixing latency creates the gap problem, and the obvious fix
for gaps recreates the latency problem. You need both.

Playback is a single continuous `sounddevice` stream written in 80 ms blocks,
rather than one `afplay` per chunk. This removes process-spawn gaps between
chunks and lets a stop request land in under 50 ms.

Each sentence's audio is kept after it plays, so rewinding replays it at once
instead of running the model again. The daemon synthesizes two sentences
ahead of the one playing, so skipping forward usually lands on audio that is
already there. The menu bar app follows playback over the same socket: it
sends `WATCH` and gets a JSON line for each sentence, word and pause.


## Local checks

Use Python 3.10 to 3.12 in a virtual environment.

```sh
python -m pip install . build packaging
python -m unittest discover -s tests -v
python -m build
```

Tests use fake model and audio dependencies for daemon lifecycle checks. They exercise real local connections without downloading weights or playing sound. CI runs these checks on macOS, Windows, and Linux, and separately installs the full dependencies on Python 3.12. Audio hardware and Mac Accessibility need manual testing.

The client and daemon share paths and transport in `src/kokoro_runtime.py`. Unix systems use a socket in a private user directory. Windows uses a random loopback TCP port and a per-launch access token. Neither listens on the network. A file lock prevents duplicate daemon instances. `PING` checks readiness without extending the model idle timeout. Set `KOKORO_RUNTIME_DIR` to isolate a test instance.

## Packaging

`pyproject.toml` defines the package and console entry points. The source setup scripts install from the downloaded repository; no PyPI release is assumed. Distribute the complete repository ZIP for the guided setup, including Quick Actions and the pronunciation file. Wheels provide the command-line app; Mac integration is installed by `install.py`. Model weights stay in the Hugging Face cache and are not included in builds.

Standalone installers are documented in [Build desktop installers](installers.md).
