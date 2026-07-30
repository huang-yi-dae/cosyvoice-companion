<#
.SYNOPSIS
    Launch the voice web app using the project .venv Python (absolute path).

.DESCRIPTION
    Runs setup.ps1 first (unless -SkipSetup) to guarantee .venv exists, then
    starts internal/src/web/app.py with the .venv interpreter referenced by an
    ABSOLUTE path. The web host/port come from the app's own config.

.PARAMETER SkipSetup
    Skip the setup.ps1 environment check (use only when .venv is known good).
#>
[CmdletBinding()]
param(
    [switch]$SkipSetup
)

$ErrorActionPreference = 'Stop'

# --- Resolve paths (script directory is the project root) -----------------
$Root       = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Definition)).Path
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$AppPy      = Join-Path $Root 'internal\src\web\app.py'
$SetupPs1   = Join-Path $Root 'setup.ps1'

# --- Ensure the environment is ready --------------------------------------
if (-not $SkipSetup) {
    Write-Host "[run] Checking environment via setup.ps1 ..."
    & $SetupPs1
    if ($LASTEXITCODE -ne 0) {
        throw "[run] setup.ps1 failed; aborting."
    }
}

# --- Sanity checks --------------------------------------------------------
if (-not (Test-Path $VenvPython)) {
    throw "[run] .venv Python not found: $VenvPython (run setup.ps1 first)."
}
if (-not (Test-Path $AppPy)) {
    throw "[run] app.py not found: $AppPy"
}

# --- Launch ---------------------------------------------------------------
Write-Host "[run] Python : $VenvPython"
Write-Host "[run] App    : $AppPy"
Write-Host "[run] Starting web app ..."
& $VenvPython $AppPy
