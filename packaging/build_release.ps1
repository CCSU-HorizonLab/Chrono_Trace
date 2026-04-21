param(
    [switch]$SkipInstaller,
    [switch]$SkipFrontendInstall,
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FrontendDir = Join-Path $ProjectRoot "frontend"
$SpecPath = Join-Path $ProjectRoot "packaging\chrono_trace.spec"
$InstallerScript = Join-Path $ProjectRoot "packaging\ChronoTrace.iss"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$BuildRoot = Join-Path $ReleaseRoot "build"
$DistRoot = Join-Path $ReleaseRoot "pyinstaller"
$AppDistDir = Join-Path $DistRoot "Chrono Trace"

function Require-Command {
    param([string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Missing required command: $Name"
    }
    return $command
}

function Resolve-IsccPath {
    $candidates = @()

    $fromPath = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($fromPath) {
        $candidates += $fromPath.Source
    }

    $programFilesX86 = ${env:ProgramFiles(x86)}
    if ($programFilesX86) {
        $candidates += (Join-Path $programFilesX86 "Inno Setup 6\ISCC.exe")
    }

    $candidates += (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    return $null
}

function Get-ProjectVersion {
    param([string]$FrontendPackageJsonPath)

    if ($Version) {
        return $Version
    }

    $packageJson = Get-Content -Path $FrontendPackageJsonPath -Raw | ConvertFrom-Json
    if ($packageJson.version) {
        return [string]$packageJson.version
    }

    return "0.1.0"
}

Require-Command "python" | Out-Null
Require-Command "npm" | Out-Null

$PackageVersion = Get-ProjectVersion -FrontendPackageJsonPath (Join-Path $FrontendDir "package.json")

Write-Host "==> Frontend build" -ForegroundColor Cyan
Push-Location $FrontendDir
try {
    if (-not $SkipFrontendInstall) {
        npm ci
    }
    npm run build
}
finally {
    Pop-Location
}

Write-Host "==> Install/refresh PyInstaller" -ForegroundColor Cyan
python -m pip install --upgrade pyinstaller

if (Test-Path -LiteralPath $BuildRoot) {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force
}
if (Test-Path -LiteralPath $DistRoot) {
    Remove-Item -LiteralPath $DistRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null

Write-Host "==> PyInstaller build" -ForegroundColor Cyan
python -m PyInstaller `
    --noconfirm `
    --clean `
    --workpath $BuildRoot `
    --distpath $DistRoot `
    $SpecPath

if (-not (Test-Path -LiteralPath $AppDistDir)) {
    throw "PyInstaller output not found: $AppDistDir"
}

if (-not $SkipInstaller) {
    Write-Host "==> Inno Setup build" -ForegroundColor Cyan
    $iscc = Resolve-IsccPath
    if (-not $iscc) {
        throw "ISCC.exe not found. Install Inno Setup 6 first."
    }

    $installerArgs = @(
        "/DBuildRoot=$AppDistDir",
        "/DProjectVersion=$PackageVersion",
        $InstallerScript
    )
    & $iscc @installerArgs
}

Write-Host ""
Write-Host "Release build complete." -ForegroundColor Green
Write-Host "PyInstaller output: $AppDistDir"
if (-not $SkipInstaller) {
    $installerOutputDir = Join-Path $ReleaseRoot "installer"
    Write-Host "Installer output: $installerOutputDir"
}
