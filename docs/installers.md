# Build desktop installers

The `Desktop installers` GitHub Actions workflow builds three packages from the same source:

- Apple Silicon Mac, `.pkg` using PyInstaller and Apple's `pkgbuild`.
- Windows x64, setup `.exe` using PyInstaller and Inno Setup 6.
- Linux x64, `.deb` using PyInstaller and `dpkg-deb` on Ubuntu 22.04.

Each job relocates its frozen application into a directory containing spaces, sets an empty Hugging Face cache and offline mode, generates real speech without audio playback, and checks daemon startup/shutdown. It then installs the native package on the runner and tests the installed executable. Windows and Linux also test uninstall. CI has no physical speakers, so audible playback and Mac Accessibility still need manual checks.

Windows and Linux also open real Tk windows and exercise their buttons, preference saving, Unicode highlighting, error state, and close behavior. Linux uses Xvfb for these checks. The Windows check covers both the console executable and the windowed launcher. Controller integration tests use the real daemon with fake audio hardware to test read, pause, resume, settings, cancellation, and failure reporting.

## Build locally

Build on the target OS with 64-bit Python 3.12 and a clean virtual environment. Windows needs Inno Setup 6. Linux needs `libportaudio2`, `tk8.6`, `dpkg-deb`, and a Python build with Tkinter. Headless GUI tests need `xvfb` and `xauth`; use `xvfb-run -a python packaging/smoke.py`. On Linux and Windows, install CPU PyTorch first:

```sh
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

On all platforms:

```sh
python -m pip install . -r packaging/requirements.txt
python packaging/prepare.py
python -m PyInstaller --noconfirm packaging/speak-kokoro.spec
python packaging/smoke.py
python packaging/package.py
```

Installers appear in `installers/`. The model and voice files are fetched at a fixed Hugging Face revision during the build and read directly from the installed bundle at runtime. The English spaCy model is included as a package with its metadata, preventing spaCy from attempting a runtime pip installation. The bundled eSpeak library and its pronunciation data come from `espeakng-loader`.

The executable dispatches `--daemon` to the background server rather than treating itself as a Python interpreter. Mac app launch opens the existing menu bar; terminal commands use the same executable. macOS Services are installed for the current user on first app launch, and the login item points at the packaged executable.

Windows has a separate `Speak Kokoro.exe` windowed launcher sharing the console executable's libraries. Its daemon uses `speak-kokoro.exe` with a hidden console, preserving logging without flashing terminal windows. Linux installs a `.desktop` application-menu entry and icon. Tk and Tcl are bundled by PyInstaller; their license notices are included.

## Distribution

Successful CI runs attach the native installers as downloadable workflow artifacts. Pull-request builds are previews and expire after 30 days. Keep release artifacts separately before sharing long-lived download links. The workflow also runs for version tags, but does not automatically publish a GitHub Release.

These builds do not include publisher signing credentials. PyInstaller creates local signatures where required on Mac; the resulting package is not Developer ID signed or notarized. Windows setup is not Authenticode signed. Signing and notarization require the maintainer's certificates and credentials before a trusted public release can be produced.

The installers include third-party notices, package version metadata, eSpeak NG 1.52.0 source and its build script, and phonemizer source. Keep these with redistributed binaries. Changes to bundled dependency versions need a corresponding review of the included notices and source archives.

## Selection workflow checks

`tests/check_selection.py` runs only on an isolated CI desktop. It opens a separate WPF text document on Windows or a Tk document on Linux, selects a passage, clicks the floating reader button, and checks that only the selected passage reaches the speech controller. It checks that the clipboard and optional text editor remain unchanged and that Stop rejects a late capture. Windows also checks that the real mouse click keeps the document foreground. Native installer checks invoke the packaged selection helper. These automated checks do not establish compatibility with every application or Wayland compositor.

Windows selection capture runs UI Automation in a separate MTA helper process with a timeout. Its generated COM interfaces are included in the frozen app. Linux uses bounded `xclip` or `wl-paste --primary` calls. Selection errors never fall back to the ordinary clipboard.
