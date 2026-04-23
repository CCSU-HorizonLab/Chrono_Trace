param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RawArgs
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FrontendDir = Join-Path $ProjectRoot "frontend"
$SpecPath = Join-Path $ProjectRoot "packaging\chrono_trace.spec"
$InstallerScript = Join-Path $ProjectRoot "packaging\ChronoTrace.iss"
$PackagingEnvScript = Join-Path $ProjectRoot "packaging\setup_packaging_env.ps1"
$BuildInfoDir = Join-Path $ProjectRoot "packaging\generated"
$BuildInfoPath = Join-Path $BuildInfoDir "build_info.json"
$ReleaseRoot = Join-Path $ProjectRoot "release"

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

function Resolve-ScriptArguments {
    $state = [ordered]@{
        Fast = $false
        IncludeInstaller = $false
        BootstrapPackagingEnv = $false
        RefreshPackagingEnv = $false
        SkipInstaller = $false
        SkipInstallerExplicit = $false
        SkipFrontendInstall = $false
        SkipFrontendInstallExplicit = $false
        Variant = "cpu"
        Version = ""
    }

    $tokens = @($RawArgs)

    for ($i = 0; $i -lt $tokens.Count; $i++) {
        $token = [string]$tokens[$i]
        switch ($token) {
            "-Fast" { $state.Fast = $true; continue }
            "-IncludeInstaller" { $state.IncludeInstaller = $true; continue }
            "-BootstrapPackagingEnv" { $state.BootstrapPackagingEnv = $true; continue }
            "-RefreshPackagingEnv" { $state.RefreshPackagingEnv = $true; continue }
            "-SkipInstaller" { $state.SkipInstaller = $true; $state.SkipInstallerExplicit = $true; continue }
            "-SkipFrontendInstall" { $state.SkipFrontendInstall = $true; $state.SkipFrontendInstallExplicit = $true; continue }
            "-Variant" {
                if ($i + 1 -ge $tokens.Count) { throw "Missing value for -Variant" }
                $i++
                $state.Variant = [string]$tokens[$i]
                continue
            }
            "-Version" {
                if ($i + 1 -ge $tokens.Count) { throw "Missing value for -Version" }
                $i++
                $state.Version = [string]$tokens[$i]
                continue
            }
            default {
                if (-not $state.Version) {
                    $state.Version = $token
                    continue
                }
                throw "Unrecognized argument: $token"
            }
        }
    }

    if ($state.Variant -notin @("cpu", "gpu", "both")) {
        throw "Invalid -Variant value: $($state.Variant)"
    }

    return $state
}

function Resolve-IsccPath {
    $candidates = @()

    $fromPath = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($fromPath) { $candidates += $fromPath.Source }

    $localAppData = $env:LOCALAPPDATA
    if ($localAppData) { $candidates += (Join-Path $localAppData "Programs\Inno Setup 6\ISCC.exe") }

    $programFilesX86 = ${env:ProgramFiles(x86)}
    if ($programFilesX86) { $candidates += (Join-Path $programFilesX86 "Inno Setup 6\ISCC.exe") }

    $candidates += (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    return $null
}

function Get-ProjectVersion {
    param([string]$FrontendPackageJsonPath, [string]$RequestedVersion)

    if ($RequestedVersion) {
        return $RequestedVersion
    }

    $packageJson = Get-Content -Path $FrontendPackageJsonPath -Raw | ConvertFrom-Json
    if ($packageJson.version) {
        return [string]$packageJson.version
    }

    return "0.1.0"
}

function Get-VariantList {
    param([string]$RequestedVariant)

    if ($RequestedVariant -eq "both") {
        return @("cpu", "gpu")
    }
    return @($RequestedVariant)
}

function Get-VariantSettings {
    param([string]$TargetVariant)

    if ($TargetVariant -eq "gpu") {
        return [ordered]@{
            Variant = "gpu"
            VariantLabel = "GPU"
            PackagingVenvDir = Join-Path $ProjectRoot ".venv-packaging-gpu"
            PackagingPython = Join-Path $ProjectRoot ".venv-packaging-gpu\Scripts\python.exe"
            BuildRoot = Join-Path $ReleaseRoot "build-gpu"
            DistRoot = Join-Path $ReleaseRoot "pyinstaller-gpu"
            AppDistDir = Join-Path $ReleaseRoot "pyinstaller-gpu\Chrono Trace"
            InstallerSuffix = "-GPU"
        }
    }

    return [ordered]@{
        Variant = "cpu"
        VariantLabel = "CPU"
        PackagingVenvDir = Join-Path $ProjectRoot ".venv-packaging"
        PackagingPython = Join-Path $ProjectRoot ".venv-packaging\Scripts\python.exe"
        BuildRoot = Join-Path $ReleaseRoot "build"
        DistRoot = Join-Path $ReleaseRoot "pyinstaller"
        AppDistDir = Join-Path $ReleaseRoot "pyinstaller\Chrono Trace"
        InstallerSuffix = ""
    }
}

function Write-BuildInfo {
    param(
        [string]$TargetVariant,
        [string]$BuildMode
    )

    New-Item -ItemType Directory -Path $BuildInfoDir -Force | Out-Null
    $payload = @{
        variant = $TargetVariant
        build_mode = $BuildMode
        generated_at = (Get-Date).ToString("s")
    }
    $payload | ConvertTo-Json | Set-Content -LiteralPath $BuildInfoPath -Encoding UTF8
}

Require-Command "npm" | Out-Null
if (-not (Test-Path -LiteralPath $PackagingEnvScript)) {
    throw "Packaging environment script not found: $PackagingEnvScript"
}

$resolvedArgs = Resolve-ScriptArguments
$variantList = Get-VariantList -RequestedVariant $resolvedArgs.Variant

$effectiveSkipFrontendInstall = [bool]$resolvedArgs.SkipFrontendInstall
$effectiveSkipInstaller = [bool]$resolvedArgs.SkipInstaller
$cleanBuild = $true
$buildMode = "release"

if ($resolvedArgs.Fast) {
    $buildMode = "test-fast"
    $cleanBuild = $false
    if (-not $resolvedArgs.SkipFrontendInstallExplicit) {
        $effectiveSkipFrontendInstall = $true
    }
    if ($resolvedArgs.IncludeInstaller) {
        $effectiveSkipInstaller = $false
    } elseif (-not $resolvedArgs.SkipInstallerExplicit) {
        $effectiveSkipInstaller = $true
    }
}

Write-Host "==> Build mode: $buildMode" -ForegroundColor Cyan
Write-Host "Variants: $($variantList -join ', ')"
Write-Host "PyInstaller clean: $cleanBuild"
Write-Host "Generate installer: $(-not $effectiveSkipInstaller)"
Write-Host "Skip frontend install: $effectiveSkipFrontendInstall"
Write-Host ""

foreach ($targetVariant in $variantList) {
    if ($resolvedArgs.RefreshPackagingEnv) {
        & $PackagingEnvScript -Variant $targetVariant -ForceReinstall
    } else {
        & $PackagingEnvScript -Variant $targetVariant
    }
    Assert-LastExitCode "Packaging environment setup ($targetVariant)"
}

if ($resolvedArgs.BootstrapPackagingEnv) {
    Write-Host ""
    Write-Host "Packaging environment is ready." -ForegroundColor Green
    foreach ($targetVariant in $variantList) {
        $settings = Get-VariantSettings -TargetVariant $targetVariant
        Write-Host "Variant $targetVariant -> $($settings.PackagingPython)"
    }
    return
}

$packageVersion = Get-ProjectVersion -FrontendPackageJsonPath (Join-Path $FrontendDir "package.json") -RequestedVersion $resolvedArgs.Version

Write-Host "==> Frontend build" -ForegroundColor Cyan
Push-Location $FrontendDir
try {
    if (-not $effectiveSkipFrontendInstall) {
        npm ci
        Assert-LastExitCode "npm ci"
    }
    npm run build
    Assert-LastExitCode "npm run build"
}
finally {
    Pop-Location
}

$results = @()

foreach ($targetVariant in $variantList) {
    $settings = Get-VariantSettings -TargetVariant $targetVariant
    Write-Host ""
    Write-Host "==> Packaging variant: $($settings.VariantLabel)" -ForegroundColor Cyan
    Write-Host "Packaging Python: $($settings.PackagingPython)"
    Write-Host "Packaging venv: $($settings.PackagingVenvDir)"

    if (-not (Test-Path -LiteralPath $settings.PackagingPython)) {
        throw "Packaging Python not found: $($settings.PackagingPython)"
    }

    Write-BuildInfo -TargetVariant $targetVariant -BuildMode $buildMode

    New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
    if ($cleanBuild) {
        if (Test-Path -LiteralPath $settings.BuildRoot) {
            Remove-Item -LiteralPath $settings.BuildRoot -Recurse -Force
        }
        if (Test-Path -LiteralPath $settings.DistRoot) {
            Remove-Item -LiteralPath $settings.DistRoot -Recurse -Force
        }
    }
    New-Item -ItemType Directory -Path $settings.BuildRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $settings.DistRoot -Force | Out-Null

    Write-Host "==> PyInstaller build ($targetVariant)" -ForegroundColor Cyan
    $pyInstallerArgs = @(
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--workpath",
        $settings.BuildRoot,
        "--distpath",
        $settings.DistRoot
    )
    if ($cleanBuild) {
        $pyInstallerArgs += "--clean"
    }
    $pyInstallerArgs += $SpecPath
    & $settings.PackagingPython @pyInstallerArgs
    Assert-LastExitCode "PyInstaller build ($targetVariant)"

    if (-not (Test-Path -LiteralPath $settings.AppDistDir)) {
        throw "PyInstaller output not found: $($settings.AppDistDir)"
    }

    if (-not $effectiveSkipInstaller) {
        Write-Host "==> Inno Setup build ($targetVariant)" -ForegroundColor Cyan
        $iscc = Resolve-IsccPath
        if (-not $iscc) {
            throw "ISCC.exe not found. Install Inno Setup 6 first."
        }

        $installerArgs = @(
            "/DBuildRoot=$($settings.AppDistDir)",
            "/DProjectVersion=$packageVersion",
            "/DInstallerSuffix=$($settings.InstallerSuffix)",
            $InstallerScript
        )
        & $iscc @installerArgs
        Assert-LastExitCode "Inno Setup build ($targetVariant)"
    }

    $results += [pscustomobject]@{
        Variant = $targetVariant
        AppDistDir = $settings.AppDistDir
    }
}

Write-Host ""
Write-Host "Release build complete." -ForegroundColor Green
Write-Host "Build mode: $buildMode"
foreach ($result in $results) {
    Write-Host "[$($result.Variant)] PyInstaller output: $($result.AppDistDir)"
}
if (-not $effectiveSkipInstaller) {
    $installerOutputDir = Join-Path $ReleaseRoot "installer"
    Write-Host "Installer output: $installerOutputDir"
}
