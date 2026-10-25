"""Wrap the tested PyInstaller bundle in the native desktop installer."""
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.2.0'
OUT = ROOT / 'installers'


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)


def main():
    OUT.mkdir(exist_ok=True)
    stage = ROOT / 'build/native-root'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    if sys.platform == 'darwin':
        apps = stage / 'Applications'
        apps.mkdir()
        shutil.copytree(ROOT / 'dist/Speak Kokoro.app', apps / 'Speak Kokoro.app', symlinks=True)
        bin_dir = stage / 'usr/local/bin'
        bin_dir.mkdir(parents=True)
        (bin_dir / 'speak-kokoro').symlink_to('/Applications/Speak Kokoro.app/Contents/MacOS/speak-kokoro')
        # Without this, Installer may find the build copy of the app (or a
        # system Python.framework) and relocate our payload there instead.
        components = ROOT / 'build/components.plist'
        run('pkgbuild', '--analyze', '--root', stage, components)
        bundles = plistlib.loads(components.read_bytes())
        for bundle in bundles:
            bundle['BundleIsRelocatable'] = False
            bundle['BundleIsVersionChecked'] = False
        components.write_bytes(plistlib.dumps(bundles))
        run('pkgbuild', '--root', stage, '--identifier', 'com.tatecarson.speak-kokoro',
            '--component-plist', components,
            '--version', VERSION, '--install-location', '/',
            OUT / f'speak-kokoro-{VERSION}-macos-{platform.machine()}.pkg')
    elif sys.platform == 'win32':
        compiler = shutil.which('ISCC') or r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
        run(compiler, ROOT / 'packaging/windows.iss')
    else:
        app = stage / 'opt/speak-kokoro'
        shutil.copytree(ROOT / 'dist/speak-kokoro', app, symlinks=True)
        bin_dir = stage / 'usr/bin'
        bin_dir.mkdir(parents=True)
        (bin_dir / 'speak-kokoro').symlink_to('/opt/speak-kokoro/speak-kokoro')
        control = stage / 'DEBIAN'
        control.mkdir()
        installed_kib = (sum(path.lstat().st_size for path in app.rglob('*')) + 1023) // 1024
        (control / 'control').write_text(
            f'Package: speak-kokoro\nVersion: {VERSION}\nArchitecture: amd64\n'
            f'Installed-Size: {installed_kib}\n'
            'Maintainer: Tate Carson <tatecarson@gmail.com>\n'
            'Section: sound\nPriority: optional\n'
            'Depends: libc6 (>= 2.35), libstdc++6, libgcc-s1, libasound2\n'
            'Description: Local text-to-speech with bundled Python and Kokoro model\n', encoding='utf-8')
        run('dpkg-deb', '-Zgzip', '-z6', '--root-owner-group', '--build', stage,
            OUT / f'speak-kokoro-{VERSION}-linux-amd64.deb')
    print('Installers:', *OUT.iterdir(), sep='\n')


if __name__ == '__main__':
    main()
