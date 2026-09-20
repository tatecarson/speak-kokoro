# speak-kokoro

Local neural text-to-speech on a macOS hotkey. Select text in any application,
press a key, hear it read aloud. Nothing leaves your machine.

Built on [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0),
which gives 54 voices across 8 languages and runs comfortably on CPU.

## Why this exists

Most "read this aloud" options are either the built-in system voice, which is
robotic, or a cloud API, which means your documents leave your machine and you
pay per character. Kokoro is good enough to listen to for a long stretch, small
enough to run locally, and permissively licensed.

The wiring around it is the actual work, and that is what this repo is.

## Install

```bash
git clone https://github.com/tatecarson/speak-kokoro.git
cd speak-kokoro
./install.sh
```

Then assign hotkeys in System Settings > Keyboard > Keyboard Shortcuts >
Services > Text. Suggested: Control-Option-S to speak, Control-Option-X to stop.

## Usage

Select text anywhere, press your shortcut. Press it again on a new selection and
it interrupts the current reading rather than talking over it.

The menu bar app gives you voice and speed pickers, a clipboard reader, and a
live view of whether the model is loaded. It shows your real key bindings, read
from macOS at runtime, so it can never advertise a shortcut you have not set.

From a terminal:

```bash
speak-kokoro "hello"              # speak an argument
pbpaste | speak-kokoro            # speak stdin
speak-kokoro --stop               # stop playback
speak-kokoro --quit               # unload the model, freeing its memory
speak-kokoro --voices             # list all 54 voices
```

Voice and speed live in `~/.config/kokoro-tts.conf` and are read fresh on every
press, so changes take effect without restarting anything.

## Fixing a mispronounced word

misaki, the grapheme-to-phoneme layer Kokoro uses, ships a handful of wrong
entries. "imagines" is one: it is stored as the Latin plural, so it comes out
"im-ah-ji-neez". These live in misaki's gold dictionary, so nothing downstream
overrides them.

Add a correction to `~/.config/kokoro-lexicon.json`:

```json
{
  "imagines": "ɪmˈæʤənz"
}
```

The daemon reloads the file on save, so the next press uses it. Case variants
are handled, which matters because misaki looks up a sentence-initial capital
separately. Malformed JSON is ignored in favour of the last good version rather
than breaking speech.

The quickest way to find the right phonemes is to print what a similar word
already produces and adapt it:

```bash
~/.local/share/kokoro-venv/bin/python -c "
from kokoro import KPipeline
g = KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M').g2p
for w in ['imagine', 'engines']: print(w, g(w)[0])
"
```

## How it is put together

Three pieces, split by how much memory they need to hold.

| Component | Resident | Lifetime |
|---|---|---|
| Menu bar app | 80 MB | Always, from login |
| Model daemon | 1.5 GB | On demand, exits after 3 h idle |
| Client script | none | Per invocation |

A cold load of torch plus Kokoro costs about 5 seconds, which is unusable on a
hotkey. So the model lives in a daemon behind a unix socket and the hotkey runs
a thin client that returns in about 50 ms. The daemon releases its memory after
three hours of silence, which on a 16 GB machine matters.

The menu bar app deliberately never imports torch. It only talks to the socket,
which is why it costs 80 MB rather than 1.5 GB and can sit in your bar all day.

## Two things worth knowing if you build something similar

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

## Uninstall

```bash
./uninstall.sh
```

Leaves Homebrew's `espeak-ng` and the cached model weights alone. Both are
listed in the script output if you want them gone.

## Requirements

macOS, Homebrew, Python 3. Tested on Apple Silicon.

## License

MIT for this wiring. Kokoro-82M itself is Apache-2.0.
