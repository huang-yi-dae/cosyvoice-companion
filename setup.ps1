<#
.SYNOPSIS
    Ensure the project virtual environment (.venv) exists and has dependencies.

.DESCRIPTION
    On first run this detects whether the project-root virtual environment
    (.venv) exists. If missing, it creates it and installs requirements.txt.
    All later code invokes this .venv Python by ABSOLUTE path so that the
    working directory never affects which interpreter is used.

.PARAMETER Force
    Delete an existing .venv and recreate it from scratch.

.PARAMETER Reinstall
    Reinstall dependencies from requirements.txt even if .venv already exists.
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Reinstall
)

$ErrorActionPreference = 'Stop'

# --- Resolve paths (script directory is the project root) -----------------
$Root         = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Definition)).Path
$VenvDir      = Join-Path $Root '.venv'
$VenvPython   = Join-Path $VenvDir 'Scripts\python.exe'
$Requirements = Join-Path $Root 'requirements.txt'

Write-Host "[setup] Project root : $Root"
Write-Host "[setup] Virtualenv   : $VenvDir"

# --- Optional: force recreate --------------------------------------------
if ($Force -and (Test-Path $VenvDir)) {
    Write-Host "[setup] -Force: removing existing .venv ..."
    Remove-Item -Recurse -Force $VenvDir
}

# --- Create the venv if the interpreter is missing ------------------------
$freshlyCreated = $false
if (-not (Test-Path $VenvPython)) {
    Write-Host "[setup] .venv not found, creating ..."

    $creator = $null
    if (Get-Command 'py' -ErrorAction SilentlyContinue) {
        $creator = @('py', '-3.11')
    } elseif (Get-Command 'python' -ErrorAction SilentlyContinue) {
        $creator = @('python')
    } else {
        throw "[setup] No base Python found (need 'py -3.11' or 'python' on PATH)."
    }

    & $creator[0] $creator[1..($creator.Length - 1)] -m venv $VenvDir
    if (-not (Test-Path $VenvPython)) {
        throw "[setup] Failed to create .venv at $VenvDir"
    }
    $freshlyCreated = $true
    Write-Host "[setup] .venv created."
} else {
    Write-Host "[setup] .venv already present."
}

# --- Install dependencies -------------------------------------------------
if ($freshlyCreated -or $Reinstall) {
    if (Test-Path $Requirements) {
        Write-Host "[setup] Installing dependencies from requirements.txt ..."
        & $VenvPython -m pip install --upgrade pip
        & $VenvPython -m pip install -r $Requirements
    } else {
        Write-Host "[setup] requirements.txt not found, skipping dependency install."
    }
} else {
    Write-Host "[setup] Dependencies assumed present (use -Reinstall to force)."
}

# --- Self-check -----------------------------------------------------------
Write-Host "[setup] Verifying core imports ..."
& $VenvPython -c "import fastapi, uvicorn, yaml; print('[setup] OK:', fastapi.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "[setup] Self-check failed. Run again with -Reinstall."
}

Write-Host "[setup] Done. Python: $VenvPython"
