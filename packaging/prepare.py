"""Download fixed speech assets and preserve dependency notices/source archives."""
from importlib import metadata
import json
import sys
from pathlib import Path
import shutil
import ssl
import tempfile
import certifi
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "build-assets"
TLS = ssl.create_default_context(cafile=certifi.where())
MODEL_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
ESPEAK_LOADER_VERSION = "0.2.4"
# The upstream 0.2.4 version commit; its build workflow uses eSpeak NG 1.52.0.
ESPEAK_LOADER_REVISION = "146599e29be31bf17d99f0bcb7dbb2f92aef3d95"


def download(url, dest):
    if dest.exists():
        return
    partial = None
    try:
        with tempfile.NamedTemporaryFile(dir=dest.parent, prefix=f".{dest.name}.",
                                         suffix=".part", delete=False) as output:
            partial = Path(output.name)
            with urllib.request.urlopen(url, timeout=120, context=TLS) as response:
                shutil.copyfileobj(response, output)
        partial.replace(dest)
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


def main():
    from huggingface_hub import snapshot_download
    if metadata.version("espeakng-loader") != ESPEAK_LOADER_VERSION:
        raise RuntimeError("Update the pinned eSpeak loader source revision for this dependency version.")
    model = ASSETS / "model"
    model.mkdir(parents=True, exist_ok=True)
    snapshot_download("hexgrad/Kokoro-82M", revision=MODEL_REVISION, local_dir=model,
                      allow_patterns=["config.json", "kokoro-v1_0.pth", "voices/*.pt", "LICENSE*", "README.md"])
    cache = model / ".cache"
    if cache.exists():
        shutil.rmtree(cache)
    notices = ASSETS / "licenses"
    notices.mkdir(parents=True, exist_ok=True)
    # Remove previously collected notices, retaining downloaded source archives.
    for old in notices.iterdir():
        if old.name != "sources":
            shutil.rmtree(old) if old.is_dir() else old.unlink()
    shutil.copy2(ROOT / "LICENSE", notices / "speak-kokoro-LICENSE.txt")
    manifest = []
    for dist in metadata.distributions():
        name = dist.metadata['Name']
        manifest.append({"name": name, "version": dist.version,
                         "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
                         "urls": dist.metadata.get_all("Project-URL")})
        for file in dist.files or []:
            if file.name.upper().split(".")[0] in {"LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS", "COPYRIGHT"}:
                source = Path(dist.locate_file(file))
                if source.is_file() and source.suffix.lower() not in {".so", ".dll", ".dylib", ".pyd", ".py", ".pyc"}:
                    target = notices / name / str(file).replace("../", "").replace("..\\", "")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (notices / "dependencies.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    download(f"https://raw.githubusercontent.com/python/cpython/v{sys.version.split()[0]}/LICENSE",
             notices / "Python-LICENSE.txt")
    if sys.platform != 'darwin':
        import tkinter
        version = tkinter.Tcl().call('info', 'patchlevel')
        for library in ('tcl', 'tk'):
            download(f"https://raw.githubusercontent.com/tcltk/{library}/core-{version.replace('.', '-')}/license.terms",
                     notices / f"{library}-LICENSE.txt")
    if sys.platform.startswith("linux"):
        for name in ("libportaudio2", "libasound2", "libjack-jackd2-0", "libstdc++6", "libgcc-s1",
                     "libtcl8.6", "libtk8.6", "libx11-6", "libxft2", "libxrender1", "libfontconfig1", "libfreetype6"):
            copyright_file = Path("/usr/share/doc") / name / "copyright"
            if copyright_file.is_file():
                shutil.copy2(copyright_file, notices / f"{name}-copyright.txt")
    sources = notices / "sources"
    sources.mkdir(exist_ok=True)
    # espeakng-loader 0.2.4 builds unmodified eSpeak NG 1.52.0. Include its
    # corresponding source and the loader's build instructions with the binary.
    download("https://github.com/espeak-ng/espeak-ng/archive/refs/tags/1.52.0.tar.gz", sources / "espeak-ng-1.52.0.tar.gz")
    # Discard caches from the old, moving-main URLs.
    for legacy in ("espeakng-loader-build.sh", "espeakng-loader-source.tar.gz"):
        (sources / legacy).unlink(missing_ok=True)
    download(f"https://raw.githubusercontent.com/thewh1teagle/espeakng-loader/{ESPEAK_LOADER_REVISION}/build.sh",
             sources / f"espeakng-loader-{ESPEAK_LOADER_REVISION}-build.sh")
    for package in ("phonemizer-fork", "espeakng-loader"):
        version = metadata.version(package)
        with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/{version}/json", timeout=60, context=TLS) as response:
            release = json.load(response)
        distributions = [x for x in release['urls'] if x['packagetype'] == 'sdist']
        if distributions:
            item = distributions[0]
            download(item['url'], sources / item['filename'])
        elif package == 'espeakng-loader':
            download(f"https://github.com/thewh1teagle/espeakng-loader/archive/{ESPEAK_LOADER_REVISION}.tar.gz",
                     sources / f"espeakng-loader-{ESPEAK_LOADER_REVISION}-source.tar.gz")
        else:
            raise RuntimeError(f"Missing corresponding source for {package} {version}")
    (notices / "README.txt").write_text(
        "Speak Kokoro includes third-party software with separate licenses.\n"
        "See the notices in this folder and dependencies.json for versions.\n"
        "The sources folder includes eSpeak NG and phonemizer source archives.\n"
        f"Kokoro-82M model revision: {MODEL_REVISION}; model license: Apache-2.0.\n"
        f"eSpeak loader {ESPEAK_LOADER_VERSION} source revision: {ESPEAK_LOADER_REVISION}.\n", encoding="utf-8")
    print(f"Prepared model, {len(list((model / 'voices').glob('*.pt')))} voices, and dependency notices.")


if __name__ == '__main__':
    main()
