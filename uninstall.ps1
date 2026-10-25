param([switch]$Purge, [string]$Python = "")
$ErrorActionPreference = "Stop"
$SetupArgs = @("$PSScriptRoot\install.py", "--uninstall")
if ($Purge) { $SetupArgs += "--purge" }
if ($Python) {
    & $Python @SetupArgs
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 @SetupArgs
} else {
    Write-Error "Python launcher not found. Use -Python with the path to your system Python executable."
    exit 1
}
exit $LASTEXITCODE
