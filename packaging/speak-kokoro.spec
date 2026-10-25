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
for package in ["kokoro", "misaki", "espeakng_loader", "en_core_web_sm", "phonemizer"]:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += [m for m in h if m not in ("misaki.ja", "misaki.zh", "misaki.zh_frontend")]
for package in ["en-core-web-sm", "spacy", "kokoro", "misaki", "phonemizer-fork", "espeakng-loader"]:
    datas += copy_metadata(package)
hiddenimports += collect_submodules("transformers.models.albert")
a = Analysis([str(root / "src/kokoro_entry.py")], pathex=[str(root / "src")],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["tkinter", "matplotlib", "IPython", "jupyter", "pytest", "tensorboard",
                       "tensorflow", "torchaudio", "torchvision", "misaki.ja", "misaki.zh"],
             module_collection_mode={"kokoro": "pyz+py", "transformers": "pyz+py"})
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="speak-kokoro", console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="speak-kokoro", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Speak Kokoro.app", bundle_identifier="com.tatecarson.speak-kokoro",
                 info_plist={"CFBundleShortVersionString": "0.2.0", "LSUIElement": True,
                             "NSHighResolutionCapable": True})
