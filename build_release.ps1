param(
    [switch]$SkipInstaller,
    [switch]$SkipFrontendInstall,
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InnerScript = Join-Path $ProjectRoot "packaging\build_release.ps1"

if (-not (Test-Path -LiteralPath $InnerScript)) {
    throw "Packaging script not found: $InnerScript"
}

$invokeArgs = @()
if ($SkipInstaller) {
    $invokeArgs += "-SkipInstaller"
}
if ($SkipFrontendInstall) {
    $invokeArgs += "-SkipFrontendInstall"
}
if ($Version) {
    $invokeArgs += @("-Version", $Version)
}

Write-Host "==> Chrono Trace one-click packaging" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"
Write-Host "Using script: $InnerScript"
Write-Host ""

& $InnerScript @invokeArgs
