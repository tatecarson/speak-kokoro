"""Download fixed speech assets and preserve dependency notices/source archives."""
from importlib import metadata
import json
from pathlib import Path
import shutil
import ssl
import certifi
import urllib.request
from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "build-assets"
TLS = ssl.create_default_context(cafile=certifi.where())
MODEL_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"


def download(url, dest):
    if not dest.exists():
        with urllib.request.urlopen(url, timeout=120, context=TLS) as response, dest.open("wb") as output:
            shutil.copyfileobj(response, output)


def main():
    model = ASSETS / "model"
    model.mkdir(parents=True, exist_ok=True)
    snapshot_download("hexgrad/Kokoro-82M", revision=MODEL_REVISION, local_dir=model,
                      allow_patterns=["config.json", "kokoro-v1_0.pth", "voices/*.pt", "LICENSE*", "README.md"])
    cache = model / ".cache"
    if cache.exists():
        shutil.rmtree(cache)
    notices = ASSETS / "licenses"
    notices.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", notices / "speak-kokoro-LICENSE.txt")
    manifest = []
    for dist in metadata.distributions():
        name = dist.metadata['Name']
        manifest.append({"name": name, "version": dist.version,
                         "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
                         "urls": dist.metadata.get_all("Project-URL")})
        for file in dist.files or []:
            if any(part.lower().startswith(("license", "copying", "notice", "authors")) for part in file.parts):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = notices / name / str(file).replace("../", "").replace("..\\", "")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (notices / "dependencies.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    sources = notices / "sources"
    sources.mkdir(exist_ok=True)
    # espeakng-loader 0.2.4 builds unmodified eSpeak NG 1.52.0. Include its
    # corresponding source and the loader's build instructions with the binary.
    download("https://github.com/espeak-ng/espeak-ng/archive/refs/tags/1.52.0.tar.gz", sources / "espeak-ng-1.52.0.tar.gz")
    download("https://raw.githubusercontent.com/thewh1teagle/espeakng-loader/main/build.sh", sources / "espeakng-loader-build.sh")
    for package in ("phonemizer-fork", "espeakng-loader"):
        version = metadata.version(package)
        with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/{version}/json", timeout=60, context=TLS) as response:
            release = json.load(response)
        distributions = [x for x in release['urls'] if x['packagetype'] == 'sdist']
        if distributions:
            item = distributions[0]
            download(item['url'], sources / item['filename'])
        elif package == 'espeakng-loader':
            download("https://github.com/thewh1teagle/espeakng-loader/archive/refs/heads/main.tar.gz", sources / "espeakng-loader-source.tar.gz")
        else:
            raise RuntimeError(f"Missing corresponding source for {package} {version}")
    (notices / "README.txt").write_text(
        "Speak Kokoro includes third-party software with separate licenses.\n"
        "See the notices in this folder and dependencies.json for versions.\n"
        "The sources folder includes eSpeak NG and phonemizer source archives.\n"
        f"Kokoro-82M model revision: {MODEL_REVISION}; model license: Apache-2.0.\n", encoding="utf-8")
    print(f"Prepared model, {len(list((model / 'voices').glob('*.pt')))} voices, and dependency notices.")


if __name__ == '__main__':
    main()
