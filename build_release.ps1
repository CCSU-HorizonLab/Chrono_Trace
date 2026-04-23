param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RawArgs
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InnerScript = Join-Path $ProjectRoot "packaging\build_release.ps1"

if (-not (Test-Path -LiteralPath $InnerScript)) {
    throw "Packaging script not found: $InnerScript"
}

function Resolve-ScriptArguments {
    $state = [ordered]@{
        Fast = $false
        IncludeInstaller = $false
        BootstrapPackagingEnv = $false
        RefreshPackagingEnv = $false
        SkipInstaller = $false
        SkipFrontendInstall = $false
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
            "-SkipInstaller" { $state.SkipInstaller = $true; continue }
            "-SkipFrontendInstall" { $state.SkipFrontendInstall = $true; continue }
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

$resolvedArgs = Resolve-ScriptArguments

$invokeArgs = @()
if ($resolvedArgs.Fast) { $invokeArgs += "-Fast" }
if ($resolvedArgs.IncludeInstaller) { $invokeArgs += "-IncludeInstaller" }
if ($resolvedArgs.BootstrapPackagingEnv) { $invokeArgs += "-BootstrapPackagingEnv" }
if ($resolvedArgs.RefreshPackagingEnv) { $invokeArgs += "-RefreshPackagingEnv" }
if ($resolvedArgs.SkipInstaller) { $invokeArgs += "-SkipInstaller" }
if ($resolvedArgs.SkipFrontendInstall) { $invokeArgs += "-SkipFrontendInstall" }
if ($resolvedArgs.Variant) { $invokeArgs += @("-Variant", [string]$resolvedArgs.Variant) }
if ($resolvedArgs.Version) { $invokeArgs += @("-Version", [string]$resolvedArgs.Version) }

Write-Host "==> Chrono Trace one-click packaging" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"
Write-Host "Using script: $InnerScript"
Write-Host ""

& $InnerScript @invokeArgs
