# Run from PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
param([string]$Python = "")
$ErrorActionPreference = "Stop"
if ($Python) {
    & $Python "$PSScriptRoot\install.py"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 "$PSScriptRoot\install.py"
} else {
    Write-Error "Install 64-bit Python 3.12 from python.org, including the Python launcher, then reopen PowerShell."
    exit 1
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
