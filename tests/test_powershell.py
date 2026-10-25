"""Run actual Windows PowerShell 5.1 and PowerShell 7 with a fake native launcher."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = r'''@echo off
echo %~1 %~2>> "%KOKORO_TEST_LOG%"
if "%~2"=="-c" (
    if "%~1"=="-%KOKORO_TEST_PYTHON%" exit /b 0
    echo Requested Python is not installed 1>&2
    exit /b 1
)
exit /b %KOKORO_TEST_EXIT%
'''


@unittest.skipUnless(sys.platform == 'win32', 'PowerShell launcher behavior is tested on Windows')
class PowerShellTests(unittest.TestCase):
    def test_supported_versions_missing_versions_and_exit_codes(self):
        shells = [shutil.which(name) for name in ('powershell.exe', 'pwsh.exe')]
        self.assertTrue(all(shells), 'CI must exercise Windows PowerShell and PowerShell 7')
        with tempfile.TemporaryDirectory(prefix='kokoro powershell ') as temporary:
            # PowerShell expands Windows 8.3 aliases such as RUNNER~1.
            folder = Path(temporary).resolve()
            (folder/'py.cmd').write_text(LAUNCHER)
            for name in ('install.ps1', 'uninstall.ps1'):
                shutil.copy2(ROOT/name, folder/name)
            log = folder/'calls.txt'
            env = dict(os.environ, PATH=str(folder)+os.pathsep+os.environ['PATH'],
                       KOKORO_TEST_LOG=str(log), KOKORO_TEST_EXIT='0')
            for shell in shells:
                for version in ('3.12', '3.11', '3.10', 'missing'):
                    with self.subTest(shell=shell, version=version):
                        log.unlink(missing_ok=True)
                        result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                                 '-File', str(folder/'install.ps1')],
                                                env=dict(env, KOKORO_TEST_PYTHON=version),
                                                capture_output=True, text=True, timeout=30)
                        self.assertEqual(result.returncode, 1 if version=='missing' else 0, result.stderr)
                        calls = log.read_text().splitlines()
                        expected = ['-3.12 -c', '-3.11 -c', '-3.10 -c']
                        count = 3 if version=='missing' else ('3.12','3.11','3.10').index(version)+1
                        self.assertEqual(calls[:count], expected[:count])
                        if version=='missing':
                            self.assertEqual(len(calls), 3)
                        else:
                            self.assertEqual(calls[-1], f'-{version} {folder / "install.py"}')
                log.unlink(missing_ok=True)
                result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                         '-File', str(folder/'uninstall.ps1')],
                                        env=dict(env, KOKORO_TEST_EXIT='7'), capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 7, result.stderr)
                self.assertEqual(log.read_text().strip(), f'-3 {folder / "install.py"}')
                result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                         '-File', str(folder/'install.ps1')],
                                        env=dict(env, KOKORO_TEST_PYTHON='3.11', KOKORO_TEST_EXIT='9'),
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 9, result.stderr)
