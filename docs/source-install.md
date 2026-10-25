# Install from source

For the packaged installers, start with the [main README](../README.md). These instructions are for developers and people who prefer a Python environment.

Read text aloud on your own computer with [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M). No account, API key, or subscription is needed. Speech is generated locally. Installation and the first use of a voice need internet access to download software and model files; your reading text is not sent to a speech service.

The command-line app runs on **macOS, Windows, and Linux**. On Mac, it also includes selection shortcuts, a menu bar app, and a floating reading panel.

| What you can do | Mac | Windows | Linux |
|---|---|---|---|
| Read quoted text or piped input aloud | Yes | Yes | Yes |
| Choose a voice and reading speed | Yes | Yes | Yes |
| Stop, pause, resume, and skip sentences | Yes | Yes | Yes |
| Keep the model loaded for faster repeat use | Yes | Yes | Yes |
| Use the included selection shortcuts and reading panel | Yes | No | No |
| Highlight words in another app | With Accessibility permission | No | No |

Windows and Linux can open the floating selection toolbar with `speak-kokoro --gui` after source installation. Your Python installation needs Tkinter; on Ubuntu/Debian, install the matching `python3-tk` package. The packaged installers include the window and its dependencies. There is no Windows or Linux tray app or automatic selection hotkey.

## Before you start

- Use a 64-bit computer and **Python 3.12**. Python 3.10 and 3.11 are also accepted. The installer rejects other versions so you do not get an incompatible dependency setup.
- Have working speakers or headphones. A GPU is not required; speech runs on the CPU.
- Allow several GB of free disk space for Python dependencies and model files. The main model is about 327 MB, with additional language and voice downloads. The loaded model can use roughly 1.5 GB of memory; usage varies.
- Allow several minutes for the first installation. Keep internet access available until the first voice finishes downloading.

On Windows and Linux, setup chooses CPU-only PyTorch packages to avoid downloading unused GPU libraries.

The scripts install into your user account. They do not require you to activate a Python environment each time you use the app. System prerequisites may ask for administrator access.

## Download the project

1. On [this repository's GitHub page](https://github.com/tatecarson/speak-kokoro), choose **Code > Download ZIP**.
2. Extract the ZIP to a folder you can find, such as Downloads. Do not run setup from inside the ZIP.
3. Open a terminal in that extracted folder, then follow the instructions for your system below. On Windows, right-click inside the folder and choose **Open in Terminal**. On Mac, open Terminal, type `cd ` with a trailing space, drag the folder into the window, and press Return. On Linux, your file manager may offer **Open in Terminal**.

If you already use Git, you can download the project this way instead:

```sh
git clone https://github.com/tatecarson/speak-kokoro.git
cd speak-kokoro
```

## Install

Choose [macOS](#macos), [Windows](#windows), or [Linux](#linux). Copy commands one line at a time and wait for each to finish.

### macOS

1. Install [Homebrew](https://brew.sh) if you do not already have it. Complete the "Next steps" it prints so `brew` works in Terminal.
2. Install Python 3.12:

   ```sh
   brew install python@3.12
   ```

3. In the extracted speak-kokoro folder, run:

   ```sh
   bash install.sh
   ```

   Setup installs eSpeak NG through Homebrew, then installs the app and Mac Quick Actions. It preserves existing voice settings and pronunciation corrections.

4. Check your audio setup, download the default voice, and try a sentence:

   ```sh
   "$HOME/.local/bin/speak-kokoro" --doctor
   "$HOME/.local/bin/speak-kokoro" --download
   "$HOME/.local/bin/speak-kokoro" "Hello! Kokoro is ready."
   ```

   `--doctor` should list an eSpeak library and your audio output. `--download` tests speech generation without playing sound. Wait for `Ready: af_heart` before continuing. The last command should read the sentence aloud.

5. To enable the short `speak-kokoro` command, add this line to `~/.zshrc`, then open a new Terminal window. If you use Bash, put it in `~/.bashrc` instead.

   ```sh
   export PATH="$HOME/.local/bin:$PATH"
   ```

#### Add Mac shortcuts and the reading panel

1. Open **System Settings > Keyboard > Keyboard Shortcuts > Services > Text**.
2. Assign shortcuts to **Speak with Kokoro** and **Stop Kokoro Speech**. Suggested keys are Control-Option-S and Control-Option-X.
3. Select a sentence in TextEdit and press your Speak shortcut. Some apps do not expose selected text to macOS Services.
4. Start the menu bar app:

   ```sh
   "$HOME/.local/share/kokoro-venv/bin/python" -m kokoro_menubar
   ```

5. In its menu, turn on **Start at Login** if you want it available after restarting your Mac. It also offers **Speak Clipboard** and **Open Reading Panel**.

The panel has play/pause, sentence navigation, voice, and speed controls. Document highlighting is optional and needs Accessibility permission. See [Mac reading panel and highlighting](macos.md) for details and permission instructions.

### Windows

Use Windows 10 or 11 with 64-bit Python. These steps use **PowerShell**, not Command Prompt or WSL.

1. Install [Python 3.12 for Windows](https://www.python.org/downloads/windows/). Choose the 64-bit installer and include the Python launcher. Open a new PowerShell window and check:

   ```powershell
   py -3.12 --version
   ```

2. Install the **x64 MSI** from the [official eSpeak NG releases](https://github.com/espeak-ng/espeak-ng/releases). Keep its default installation folder, usually `C:\Program Files\eSpeak NG`. The app checks that folder for `libespeak-ng.dll` automatically. This is the [Windows setup recommended by Kokoro](https://github.com/hexgrad/kokoro#windows-installation).
3. In the extracted speak-kokoro folder, run:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
   ```

   The execution-policy setting applies only to this setup process. It does not change your permanent PowerShell policy. Setup installs the app under your user account and adds its launcher folder to your user PATH.

4. Check setup and try speech. These full-path commands work immediately in the same window:

   ```powershell
   & "$env:LOCALAPPDATA\speak-kokoro\bin\speak-kokoro.cmd" --doctor
   & "$env:LOCALAPPDATA\speak-kokoro\bin\speak-kokoro.cmd" --download
   & "$env:LOCALAPPDATA\speak-kokoro\bin\speak-kokoro.cmd" "Hello! Kokoro is ready."
   ```

   Wait for `Ready: af_heart` after the download. You should hear the sentence after the last command.

5. Close and reopen your terminal to use `speak-kokoro` without the full path. If it is still not found, sign out and back in, or keep using the full-path command.

For a Python installation without the `py` launcher, supply its full path:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Python "C:\path\to\python.exe"
```

### Linux

The following commands cover Ubuntu 24.04 and Fedora with Python 3.12 available. Other distributions need Python 3.10 to 3.12, Python's `venv` support, eSpeak NG, and PortAudio. [sounddevice requires a system PortAudio library on Linux](https://python-sounddevice.readthedocs.io/en/latest/installation.html).

1. Install prerequisites for your distribution.

   Ubuntu 24.04:

   ```sh
   sudo apt update
   sudo apt install python3.12 python3.12-venv espeak-ng libportaudio2
   ```

   Fedora:

   ```sh
   sudo dnf install python3.12 espeak-ng portaudio
   ```

   On Debian or another Ubuntu release, package names depend on the Python version available. For example, use `python3.11` and `python3.11-venv` if that is the supported version your distribution provides. A newer system Python alone is not enough; install a supported version alongside it.

2. In the extracted speak-kokoro folder, run as your normal user:

   ```sh
   bash install.sh
   ```

   If setup cannot find your Python, select it explicitly:

   ```sh
   KOKORO_PYTHON=/path/to/python3.12 bash install.sh
   ```

3. Check setup, download the voice, and try speech:

   ```sh
   "$HOME/.local/bin/speak-kokoro" --doctor
   "$HOME/.local/bin/speak-kokoro" --download
   "$HOME/.local/bin/speak-kokoro" "Hello! Kokoro is ready."
   ```

4. If `speak-kokoro` is not found by itself, add this line to your shell's startup file, usually `~/.bashrc` or `~/.zshrc`, then open a new terminal:

   ```sh
   export PATH="$HOME/.local/bin:$PATH"
   ```

Use a desktop session with a working audio output. A headless server or container may need separate audio configuration.

## Everyday use

The following commands work on all three systems once the launcher is on your PATH:

```sh
speak-kokoro "Read this sentence aloud."
speak-kokoro --voice bm_george --speed 1.1 "Try a different voice."
speak-kokoro --stop
speak-kokoro --toggle
speak-kokoro --next
speak-kokoro --prev
speak-kokoro --quit
speak-kokoro --help
```

- A new reading interrupts the previous one. Put text in quotes so the terminal treats it as a single argument.
- `--toggle` pauses or resumes. If playback has ended, it replays the last reading.
- `--prev` restarts the current sentence, or goes back one sentence if playback has just started it.
- `--quit` stops the background model and frees its memory. The next reading starts it again.
- The command returns after sending the text; speech continues in the background. Use `--stop` to stop it. Closing the terminal does not stop the model.

Loading the model takes longer than sending later readings. By default it unloads after three hours without a playback command. Use `speak-kokoro --status` to check whether it is running.

### Read a file or the clipboard

Mac:

```sh
cat article.txt | speak-kokoro
pbpaste | speak-kokoro
```

Windows PowerShell:

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new()
Get-Content -Raw -Encoding UTF8 .\article.txt | speak-kokoro
Get-Clipboard -Raw | speak-kokoro
```

The encoding line preserves non-ASCII text when piping from older Windows PowerShell. The Windows launcher tells Python to read UTF-8 input.

Linux:

```sh
cat article.txt | speak-kokoro
```

If you already use a clipboard tool, pipe it into the command, for example `wl-paste | speak-kokoro` on Wayland or `xclip -selection clipboard -o | speak-kokoro` on X11. Those tools are separate optional packages.

### Voice, speed, and languages

The default is `af_heart`, an American English voice, at speed `1.0`. Try `am_michael` for another American voice or `bf_emma` and `bm_george` for British English. Speeds from `0.5` to `2.0` are accepted.

Run `speak-kokoro --voices` to fetch the current voice list. This command needs internet access. A new voice may also need a download before it works offline.

To change defaults, run `speak-kokoro --paths` and open the settings file it lists in a text editor:

```ini
VOICE=af_heart
SPEED=1.0
```

Command-line `--voice` and `--speed` override environment variables, which override saved settings. Mac users can also save settings through the panel.

Kokoro supports multiple languages; use a voice matching the language of your text. Japanese and Mandarin require extra language packages. See [Kokoro's language guide](https://github.com/hexgrad/kokoro#advanced-usage). Install the corresponding optional package into the app environment, for example:

```sh
# Mac/Linux, from the extracted project folder:
"$HOME/.local/share/kokoro-venv/bin/python" -m pip install '.[japanese]'
# Use '.[chinese]' for Mandarin.
```

```powershell
# Windows, from the extracted project folder:
& "$env:LOCALAPPDATA\speak-kokoro\venv\Scripts\python.exe" -m pip install '.[japanese]'
```

### Correct an English pronunciation

Run `speak-kokoro --paths` to find `kokoro-lexicon.json`. It maps words to phonemes, not ordinary spelling. For example:

```json
{
  "imagines": "ɪmˈæʤənz"
}
```

Keep any existing corrections you want. The next reading loads your changes. Invalid JSON keeps the last valid version until you fix it. These overrides apply to the English pronunciation dictionary.

## Troubleshooting

| Problem | What to try |
|---|---|
| `speak-kokoro` is not found | Use the full-path command in your system's install section. Follow its PATH step, then reopen your terminal. |
| Python version or dependency installation error | Use 64-bit Python 3.12 and rerun setup. Do not use `sudo pip`. If you previously installed with a different Python version, uninstall the app first, then reinstall; settings are kept. |
| `venv` or `ensurepip` is missing on Linux | Install the `python3.12-venv` package, or the matching package for your chosen Python. |
| eSpeak is missing | Run `--doctor`. Install eSpeak NG as described above. For a custom Windows location, set `$env:PHONEMIZER_ESPEAK_LIBRARY = 'C:\your\folder\libespeak-ng.dll'` before running the app. |
| No sound or a PortAudio error | Check volume and your default output device, then run `--doctor`. On Linux, check that PortAudio is installed. After switching audio devices, run `--quit` and try again. |
| First run seems stuck | Run `--download` to see download progress and errors in the terminal. Check internet access and disk space. Initial startup allows up to ten minutes. |
| Model cannot start or reading fails | Run `--paths`, then open the daemon log it lists. Run `--quit` and retry after correcting the reported error. |
| Mac shortcut does nothing | Try it in TextEdit. Verify both Services are enabled and assigned keys, then restart the app you were reading from. |
| Mac panel does not highlight a document | Follow the [Accessibility instructions](macos.md). Some apps cannot report word positions; the panel can still show the reading text. |
| Windows PowerShell blocks setup on a managed PC | Your organization may enforce script policy. Use `py -3.12 .\install.py` from the project folder if permitted, or contact your administrator. |

For help, [open an issue](https://github.com/tatecarson/speak-kokoro/issues) with your operating system, Python version, `--doctor` output, and the relevant error. Remove any private text from logs before sharing them.

## Update or uninstall

To update, download and extract a fresh copy, then run the installer again. If you used Git, run `git pull` first. Settings and pronunciation corrections are kept. Quit and reopen the Mac menu bar app after an update; a configured login item restarts automatically.

To uninstall, run from the extracted project folder:

Mac or Linux:

```sh
bash uninstall.sh
```

Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1
```

Uninstall keeps your settings, pronunciation corrections, logs, and downloaded models. To also remove settings, add `--purge` on Mac/Linux or `-Purge` on Windows. Python, eSpeak NG, and system audio libraries are left installed. On Mac, clear any assigned Services shortcuts yourself.

Model files normally live in `~/.cache/huggingface`, or `%USERPROFILE%\.cache\huggingface` on Windows, unless you set `HF_HOME`. That cache may be shared with other apps; remove only model files you no longer need.

## Development and license

See [development notes](development.md) for architecture, packaging, and test commands. Automated checks cover packaging and local communication across macOS, Windows, and Linux. They do not replace testing audio hardware or Mac Accessibility on real machines.

This project's code is [MIT licensed](../LICENSE). Kokoro-82M's weights use Apache-2.0. Dependencies have their own licenses.

## Selection toolbar on Windows and Linux

Run `speak-kokoro --gui`, select text in another app, then click **Read selection**. Windows installs the `comtypes` accessibility client automatically. Linux needs `xclip` for X11 or `wl-clipboard` for supported Wayland desktops, for example `sudo apt install xclip wl-clipboard`. Wayland access depends on the desktop compositor. See the README for selection limitations and the optional text reader.
