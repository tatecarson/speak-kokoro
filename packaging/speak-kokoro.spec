# Build with: python -m PyInstaller --noconfirm packaging/speak-kokoro.spec
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all, copy_metadata, collect_submodules

root = Path(SPECPATH).parent
assets = root / "build-assets"
datas = [(str(assets / "model"), "model"),
         (str(assets / "licenses"), "licenses"),
         (str(root / "quickactions"), "quickactions"),
         (str(root / "config"), "config")]
binaries = []
if sys.platform.startswith("linux"):
    binaries.append(("/usr/lib/x86_64-linux-gnu/libportaudio.so.2", "."))
hiddenimports = ["kokoro_daemon", "kokoro_cli", "kokoro_runtime", "kokoro_desktop"]
if sys.platform == "darwin":
    hiddenimports += ["kokoro_menubar", "kokoro_player"]
else:
    hiddenimports += ["kokoro_gui", "kokoro_controller", "kokoro_selection"]
    datas.append((str(root / "packaging/speak-kokoro.png"), "desktop"))
if sys.platform == "win32":
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    hiddenimports += collect_submodules("comtypes.gen")
for package in ["kokoro", "misaki", "espeakng_loader", "en_core_web_sm", "phonemizer", "language_tags"]:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += [m for m in h if m not in ("misaki.ja", "misaki.zh", "misaki.zh_frontend")]
for package in ["en-core-web-sm", "spacy", "kokoro", "misaki", "phonemizer-fork", "espeakng-loader"]:
    datas += copy_metadata(package)
hiddenimports += collect_submodules("transformers.models.albert")
a = Analysis([str(root / "src/kokoro_entry.py")], pathex=[str(root / "src")],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["matplotlib", "IPython", "jupyter", "pytest", "tensorboard",
                       "tensorflow", "torchaudio", "torchvision", "misaki.ja", "misaki.zh"]
                      + (["tkinter", "kokoro_gui", "kokoro_controller", "kokoro_selection"] if sys.platform == "darwin" else []),
             module_collection_mode={"kokoro": "pyz+py", "transformers": "pyz+py"})
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="speak-kokoro", console=True, upx=False)
executables = [exe]
if sys.platform == "win32":
    executables.append(EXE(pyz, a.scripts, [], exclude_binaries=True,
                           name="Speak Kokoro", console=False, upx=False,
                           icon=str(root / "packaging/speak-kokoro.ico")))
coll = COLLECT(*executables, a.binaries, a.datas, name="speak-kokoro", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Speak Kokoro.app", bundle_identifier="com.tatecarson.speak-kokoro",
                 info_plist={"CFBundleShortVersionString": "0.4.0", "LSUIElement": True,
                             "NSHighResolutionCapable": True})
