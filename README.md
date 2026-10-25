# speak-kokoro

Read text aloud on your own computer with Kokoro. No account, API key, subscription, or separate Python installation is needed when you use a packaged installer. The speech model, all 54 voice files, English language data, and audio libraries are included. Your text stays on your computer, and the included voices work offline.

Mac includes a menu bar app, reading panel, and selection shortcuts. Windows and Linux currently use terminal commands. A graphical interface for those systems is separate work.

## Download an installer

Preview installers are built by the [Desktop installers workflow](https://github.com/tatecarson/speak-kokoro/actions/workflows/installers.yml). Open a successful run, scroll to **Artifacts**, download the package matching your computer, and extract the downloaded ZIP. GitHub requires you to sign in to download workflow artifacts. Builds are kept for 30 days.

| Computer | Installer | Requirements |
|---|---|---|
| Mac with Apple Silicon | `speak-kokoro-0.2.0-macos-arm64.pkg` | macOS 14 or later |
| Windows PC | `speak-kokoro-0.2.0-windows-x64-setup.exe` | Windows 10 or 11, x64 |
| Ubuntu or Debian PC | `speak-kokoro-0.2.0-linux-amd64.deb` | Ubuntu 22.04 or later, Debian 12 or later, x64 |

Intel Macs, Windows ARM, and other Linux package formats do not have installer builds yet. [Source installation](docs/source-install.md) remains available where the dependencies support your system.

Allow a few GB of free disk space. These downloads include Python, PyTorch, and the speech model, so they are much larger than the source-code ZIP. A GPU is not required.

These are **unsigned preview installers**. Mac and Windows may ask you to approve an unrecognized developer. Mac builds have local code signatures but are not signed with an Apple Developer ID or notarized. Public releases with verified publisher signatures need signing certificates.

## Install and hear your first sentence

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
2. Open **Speak Kokoro terminal** from the Start menu. This opens a command window in the installed app's folder and displays help.
3. Type:

   ```text
   speak-kokoro "Hello! Kokoro is ready."
   ```

4. To stop reading, type:

   ```text
   speak-kokoro --stop
   ```

Use the Start menu terminal for these commands. The installer does not change your global PATH. The default app location is `%LOCALAPPDATA%\Programs\Speak Kokoro`.

If Windows shows an unrecognized-app warning, check that this is the preview installer you intended to download before approving it.

### Linux

Open a terminal in the folder containing the downloaded `.deb`, then run:

```sh
sudo apt install ./speak-kokoro-0.2.0-linux-amd64.deb
speak-kokoro "Hello! Kokoro is ready."
```

`apt` may download standard system audio dependencies if they are missing. Speech itself works offline after installation. Use a desktop session with working speakers or headphones.

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
```

Put the reading text in quotes. A new reading interrupts the previous one. The terminal command returns while speech continues in the background.

`--toggle` pauses or resumes, or replays the previous reading if it has ended. `--next` and `--prev` navigate sentences. `--quit` stops the background model and frees its memory. The next reading loads it again. By default, it unloads after three hours without a playback command.

The default voice is `af_heart`. Try `am_michael` for another American English voice, or `bf_emma` and `bm_george` for British English. Speeds from `0.5` to `2.0` are accepted. Run `--paths` to locate your saved settings and pronunciation corrections. Mac users can save voice and speed in the reading panel.

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

Install a newer package over the existing version to update. Stop speech and quit the Mac menu bar app first. Your voice settings and pronunciation corrections are kept.

- **Windows:** use **Settings > Apps > Installed apps > Speak Kokoro > Uninstall**, or its Start menu uninstaller.
- **Linux:** run `speak-kokoro --quit`, then `sudo apt remove speak-kokoro`.
- **Mac:** turn off **Start at Login**, stop the model, and quit the app. Delete **Speak Kokoro** from Applications. Remove the command link with `sudo rm /usr/local/bin/speak-kokoro`. You can remove the two Kokoro workflows from `~/Library/Services` and clear their keyboard shortcuts.

Settings and pronunciation corrections remain in your account after removal. `--paths` shows their locations before you uninstall.

## For developers

[Install from source](docs/source-install.md), [build installers](docs/installers.md), or read the [architecture notes](docs/development.md).

The project's code is [MIT licensed](LICENSE). Kokoro-82M's weights use Apache-2.0. Included dependencies have their own licenses. The packaged app includes a `licenses` folder with dependency notices and source archives for eSpeak NG and phonemizer.
