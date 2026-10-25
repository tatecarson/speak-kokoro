# Run from PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
param([string]$Python = "")
$ErrorActionPreference = "Stop"
if ($Python) {
    & $Python "$PSScriptRoot\install.py"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $selected = $null
    $previousPreference = $ErrorActionPreference
    try {
        # Missing versions write to stderr. PowerShell 5.1 must not turn a
        # failed probe into a terminating NativeCommandError.
        $ErrorActionPreference = "Continue"
        foreach ($version in '3.12', '3.11', '3.10') {
            & py "-$version" -c "import sys; sys.exit(sys.maxsize <= 2**32)" 2>$null
            if ($LASTEXITCODE -eq 0) { $selected = $version; break }
        }
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if (-not $selected) {
        Write-Error "Install 64-bit Python 3.10, 3.11, or 3.12 (recommended) from python.org."
        exit 1
    }
    & py "-$selected" "$PSScriptRoot\install.py"
} else {
    Write-Error "Install 64-bit Python 3.12 from python.org, including the Python launcher, then reopen PowerShell."
    exit 1
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
