param(
    [switch]$ForceReinstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
# 单一打包环境：ONNX/DirectML 免 CUDA 免 torch，一个 venv 通吃（torch 时代
# 的 cpu/gpu 双 venv 已随 GPU 变体移除）
$VenvDir = Join-Path $ProjectRoot ".venv-packaging"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$RequirementsPath = Join-Path $PSScriptRoot "requirements-packaging.txt"
$HashPath = Join-Path $VenvDir ".requirements-packaging.sha256"

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

if (-not (Test-Path -LiteralPath $RequirementsPath)) {
    throw "Packaging requirements not found: $RequirementsPath"
}
$systemPython = (Require-Command "python").Source
$requirementsHash = (Get-FileHash -LiteralPath $RequirementsPath -Algorithm SHA256).Hash
$requirementsFingerprint = $requirementsHash
$venvExists = Test-Path -LiteralPath $VenvPython

if (-not $venvExists) {
    Write-Host "==> Create packaging venv" -ForegroundColor Cyan
    & $systemPython -m venv $VenvDir
    Assert-LastExitCode "Create packaging venv"
}

$storedHash = ""
if (Test-Path -LiteralPath $HashPath) {
    $storedHash = [string](Get-Content -LiteralPath $HashPath -Raw).Trim()
}

$needsInstall = $ForceReinstall -or (-not $venvExists) -or ($storedHash -ne $requirementsFingerprint)
if (-not $needsInstall) {
    try {
        & $VenvPython -m PyInstaller --version | Out-Null
        # Native commands do not throw on non-zero exit, so check the exit code
        # explicitly (e.g. venv exists but PyInstaller is missing/broken).
        if ($LASTEXITCODE -ne 0) {
            $needsInstall = $true
        }
    } catch {
        $needsInstall = $true
    }
}

if ($needsInstall) {
    Write-Host "==> Sync packaging dependencies" -ForegroundColor Cyan
    # requirements-packaging.txt references the vendored wheel with a path
    # relative to the repository root, and pip resolves it against the current
    # working directory. Run pip from the repository root no matter where this
    # script was invoked from.
    Push-Location $ProjectRoot
    try {
        & $VenvPython -m pip install -r $RequirementsPath
        Assert-LastExitCode "Packaging dependency install"
    }
    finally {
        Pop-Location
    }

    Set-Content -LiteralPath $HashPath -Value $requirementsFingerprint -NoNewline
}

Write-Host "==> Packaging environment ready" -ForegroundColor Green
Write-Host "Venv: $VenvDir"
Write-Host "Python: $VenvPython"
