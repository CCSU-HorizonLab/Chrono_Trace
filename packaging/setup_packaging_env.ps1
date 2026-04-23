param(
    [switch]$ForceReinstall,
    [string]$Variant = "cpu"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvName = if ($Variant -eq "gpu") { ".venv-packaging-gpu" } else { ".venv-packaging" }
$VenvDir = Join-Path $ProjectRoot $VenvName
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$RequirementsPath = Join-Path $PSScriptRoot "requirements-packaging.txt"
$HashPath = Join-Path $VenvDir ".requirements-packaging.sha256"
$GpuTorchIndexUrl = "https://download.pytorch.org/whl/cu121"

function Require-Command {
    param([string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Missing required command: $Name"
    }
    return $command
}

function Assert-LastExitCode {
    param([string]$StepName)

    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE"
    }
}

function Get-TorchVersion {
    param([string]$RequirementsFile)

    $torchLine = Get-Content -LiteralPath $RequirementsFile | Where-Object { $_ -match '^torch==' } | Select-Object -First 1
    if (-not $torchLine) {
        throw "requirements-packaging.txt must pin torch with torch==<version>"
    }
    return ($torchLine -replace '^torch==', '').Trim()
}

if (-not (Test-Path -LiteralPath $RequirementsPath)) {
    throw "Packaging requirements not found: $RequirementsPath"
}
if ($Variant -notin @("cpu", "gpu")) {
    throw "Invalid -Variant value: $Variant"
}

$systemPython = (Require-Command "python").Source
$requirementsHash = (Get-FileHash -LiteralPath $RequirementsPath -Algorithm SHA256).Hash
$torchVersion = Get-TorchVersion -RequirementsFile $RequirementsPath
$variantHashSeed = "$requirementsHash|$Variant|$torchVersion|$GpuTorchIndexUrl"
$venvExists = Test-Path -LiteralPath $VenvPython

if (-not $venvExists) {
    Write-Host "==> Create packaging venv ($Variant)" -ForegroundColor Cyan
    & $systemPython -m venv $VenvDir
    Assert-LastExitCode "Create packaging venv"
}

$storedHash = ""
if (Test-Path -LiteralPath $HashPath) {
    $storedHash = [string](Get-Content -LiteralPath $HashPath -Raw).Trim()
}

$needsInstall = $ForceReinstall -or (-not $venvExists) -or ($storedHash -ne $variantHashSeed)
if (-not $needsInstall) {
    try {
        & $VenvPython -m PyInstaller --version | Out-Null
    } catch {
        $needsInstall = $true
    }
}

if ($needsInstall) {
    Write-Host "==> Sync packaging dependencies ($Variant)" -ForegroundColor Cyan
    & $VenvPython -m pip install -r $RequirementsPath
    Assert-LastExitCode "Packaging dependency install"

    if ($Variant -eq "gpu") {
        Write-Host "==> Replace CPU torch with CUDA torch ($torchVersion)" -ForegroundColor Cyan
        & $VenvPython -m pip install --upgrade --force-reinstall --no-cache-dir --index-url $GpuTorchIndexUrl "torch==$torchVersion"
        Assert-LastExitCode "GPU torch install"
    }

    Set-Content -LiteralPath $HashPath -Value $variantHashSeed -NoNewline
}

Write-Host "==> Packaging environment ready" -ForegroundColor Green
Write-Host "Variant: $Variant"
Write-Host "Venv: $VenvDir"
Write-Host "Python: $VenvPython"
