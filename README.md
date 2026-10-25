# speak-kokoro

Read text aloud on your own computer with Kokoro. No account, API key, subscription, or separate Python installation is needed when you use a packaged installer. The speech model, all 54 voice files, English language data, and audio libraries are included. Your text stays on your computer, and English speech works offline.

Windows and Linux open a small floating toolbar. Select text in your document, browser, or other supported app, then click **Read selection**. The original document stays in view while you listen. An optional reading window handles pasted text and files. Mac includes its menu bar app, reading panel, and selection shortcuts.

## Download an installer

Preview installers are built by the [Desktop installers workflow](https://github.com/tatecarson/speak-kokoro/actions/workflows/installers.yml). Open a successful run, scroll to **Artifacts**, download the package matching your computer, and extract the downloaded ZIP. GitHub requires you to sign in to download workflow artifacts. Builds are kept for 30 days.

| Computer | Installer | Requirements |
|---|---|---|
| Mac with Apple Silicon | `speak-kokoro-0.4.1-macos-arm64.pkg` | macOS 14 or later |
| Windows PC | `speak-kokoro-0.4.1-windows-x64-setup.exe` | Windows 10 or 11, x64 |
| Ubuntu or Debian PC | `speak-kokoro-0.4.1-linux-amd64.deb` | Ubuntu 22.04 or later, Debian 12 or later, x64 |

Intel Macs, Windows ARM, and other Linux package formats do not have installer builds yet. [Source installation](docs/source-install.md) remains available where the dependencies support your system.

Allow a few GB of free disk space. These downloads include Python, PyTorch, and the speech model, so they are much larger than the source-code ZIP. A GPU is not required.

These are **unsigned preview installers**. Mac and Windows may ask you to approve an unrecognized developer. Mac builds have local code signatures but are not signed with an Apple Developer ID or notarized. Public releases with verified publisher signatures need signing certificates.

## Install and hear your first sentence

If you previously installed from source, [uninstall that copy first](docs/source-install.md#update-or-uninstall) so an older command does not take priority over the packaged app. Your settings are kept.

### Mac

1. Open the `.pkg` and follow the installer. It installs **Speak Kokoro** in Applications and a terminal command in `/usr/local/bin`.
2. Open **Speak Kokoro** from Applications. Its icon appears in the menu bar. The first opening also installs the two text-selection Services for your account.
3. Copy a sentence, then choose **Speak Clipboard** from the menu. The first reading takes longer while the model loads.
4. To use a keyboard shortcut, open **System Settings > Keyboard > Keyboard Shortcuts > Services > Text**. Assign keys to **Speak with Kokoro** and **Stop Kokoro Speech**. Suggested keys are Control-Option-S and Control-Option-X.
5. Select some text in TextEdit and press your Speak shortcut.

Use **Start at Login** in the menu if you want the app to open when you sign in. The reading panel offers voice, speed, pause, and sentence controls. [Mac reading panel and highlighting](docs/macos.md) explains optional Accessibility permissions.

If macOS blocks an unsigned preview after you try to open it, review **System Settings > Privacy & Security** for the approval option. Only approve installers obtained from this repository or a distributor you trust.

### Windows

1. Open the setup `.exe` and follow the installer. It installs for your user account; a separate Python or eSpeak installation is unnecessary.
2. Open **Speak Kokoro** from the Start menu. A small floating toolbar opens without a terminal.
3. Return to your document and select a sentence.
4. Click **Read selection** on the toolbar. Keep reading your original document while Kokoro speaks. Use **Pause**, **Resume**, and **Stop** on the toolbar.

The default app location is `%LOCALAPPDATA%\Programs\Speak Kokoro`. **Speak Kokoro terminal** remains available in the Start menu for optional command-line use; the installer does not change your global PATH.

If Windows shows an unrecognized-app warning, check that this is the preview installer you intended to download before approving it.

### Linux

Open a terminal in the folder containing the downloaded `.deb`, then run:

```sh
sudo apt install ./speak-kokoro-0.4.1-linux-amd64.deb
```

Open **Speak Kokoro** from your applications menu. Select text in your document, then click **Read selection** on the floating toolbar. You can also open the toolbar with `speak-kokoro --gui`.

`apt` may download standard system audio and display dependencies if they are missing. Speech itself works offline after installation. Use a graphical desktop session with working speakers or headphones. On Wayland desktops, the Tk window uses XWayland.

## Read selected text while staying in your document

1. Open Speak Kokoro once. Its small toolbar stays above other windows. Drag its title bar to a convenient spot.
2. Select text where you are working.
3. Click **Read selection**. No copy or paste step is needed, and your clipboard is unchanged.
4. Use **Pause / Resume** or **Stop** while keeping the original document visible.

The app reads the selected passage, not the whole document. It does not move the selection or add word highlighting inside another app. Changing the selection while speech plays does not change the reading until you click **Read selection** again.

**Windows:** the source app must expose its text selection through Windows UI Automation. Support varies by app and document format. Password fields, image-only PDFs, and apps running with higher privileges may be unavailable. The toolbar does not take focus from the source document when you click Read selection.

**Linux:** X11 sessions use the primary selection provided by text apps. On Wayland, the desktop and app must expose a primary selection to `wl-clipboard`. Some Wayland environments restrict this. If it is unavailable, use an X11 desktop session or the optional pasted-text reader. The `.deb` installs `xclip` and `wl-clipboard` as system dependencies. Primary selection can persist after you leave an app, so select the intended passage immediately before clicking Read selection.

If a selection cannot be read, the toolbar explains why. It never substitutes ordinary clipboard contents. There are no global keyboard shortcuts on Windows or Linux yet.

Choose **Settings & text** to change voice or speed, open a file, or explicitly paste text when an app cannot share its selection. Close that larger window or choose **Back to document toolbar** to return. Close the floating toolbar to quit and stop speech.

## Optional Windows or Linux reading window

- **Paste text** replaces the text area with your clipboard text. **Open text file** loads a plain UTF-8 `.txt` or `.md` file.
- **Read aloud** starts a new reading. The first reading takes longer while the voice loads; **Stop** also cancels loading.
- **Pause / Resume**, **Previous**, and **Next** control playback. Words are highlighted as they are read. If you edit the text while listening, highlighting stops until you read the edited text.
- **Voice** and **Speed** are saved automatically. Changing them during playback restarts the current sentence with the new settings.
- **Help** shows keyboard shortcuts, audio troubleshooting, and the diagnostic log.

Press **Ctrl+Enter** to read, **Esc** to stop, or **Ctrl+O** to open a text file. Closing the floating toolbar stops playback and unloads the model. Closing the optional text window returns to the toolbar. The app does not save the text you paste or type.

The desktop voice picker includes English, Spanish, French, Hindi, Italian, and Portuguese voices. The floating toolbar provides selection reading; it does not add a system tray icon.

## Everyday commands

These commands work in the Windows Start menu terminal, Mac Terminal, or a Linux terminal:

```text
speak-kokoro "Read this sentence aloud."
speak-kokoro --voice bm_george --speed 1.1 "Try a different voice."
speak-kokoro --stop
speak-kokoro --toggle
speak-kokoro --next
speak-kokoro --prev
speak-kokoro --quit
speak-kokoro --voices
speak-kokoro --help
speak-kokoro --gui
```

Put the reading text in quotes. A new reading interrupts the previous one. The terminal command returns while speech continues in the background.

`--toggle` pauses or resumes, or replays the previous reading if it has ended. `--next` and `--prev` navigate sentences. `--quit` stops the background model and frees its memory. The next reading loads it again. By default, it unloads after three hours without a playback command.

The default voice is `af_heart`. Try `am_michael` for another American English voice, or `bf_emma` and `bm_george` for British English. Speeds from `0.5` to `2.0` are accepted. Run `--paths` to locate your saved settings and pronunciation corrections. You can also save voice and speed in the desktop window or Mac reading panel.

The installers include the English and eSpeak pronunciation engines. Although all voice files are present, Japanese and Mandarin need additional language engines and currently require a [source installation](docs/source-install.md#voice-speed-and-languages).

## Check or fix your setup

```text
speak-kokoro --doctor
speak-kokoro --self-test
speak-kokoro --paths
```

- `--doctor` checks the pronunciation library and your default audio output.
- `--self-test` generates a short sentence without playing it. This verifies the included model and libraries.
- `--paths` shows where settings and logs are stored.

If speech is silent, check volume and the default output device, then run `--doctor`. After changing headphones or audio devices, try `--quit` and read again. If a Mac shortcut fails, test it in TextEdit and check its Services key binding.

If the model fails to start, open the log shown by `--paths`. [Report a problem](https://github.com/tatecarson/speak-kokoro/issues) with your OS, installer filename, and relevant error. Remove private reading text before sharing logs.

## Update and uninstall

Install a newer package over the existing version to update. Close the floating toolbar, stop speech, and quit the Mac menu bar app first. Your voice settings and pronunciation corrections are kept.

- **Windows:** use **Settings > Apps > Installed apps > Speak Kokoro > Uninstall**, or its Start menu uninstaller.
- **Linux:** run `speak-kokoro --quit`, then `sudo apt remove speak-kokoro`.
- **Mac:** turn off **Start at Login**, stop the model, and quit the app. Delete **Speak Kokoro** from Applications. Remove the command link with `sudo rm /usr/local/bin/speak-kokoro`. You can remove the two Kokoro workflows from `~/Library/Services` and clear their keyboard shortcuts.

Settings and pronunciation corrections remain in your account after removal. `--paths` shows their locations before you uninstall.

## For developers

[Install from source](docs/source-install.md), [build installers](docs/installers.md), or read the [architecture notes](docs/development.md).

The project's code is [MIT licensed](LICENSE). Kokoro-82M's weights use Apache-2.0. Included dependencies have their own licenses. The packaged app includes a `licenses` folder with dependency notices and source archives for eSpeak NG and phonemizer.
