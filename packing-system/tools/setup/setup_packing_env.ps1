# Setup conda env packing-zhuang (Python 3.11) for packing-system UI + algorithm.
# Usage:
#   cd packing-system\tools\setup
#   .\setup_packing_env.ps1

$ErrorActionPreference = "Stop"

$EnvName = "packing-zhuang"
$PythonVersion = "3.11"

$SetupDir = $PSScriptRoot
$ProjectDir = Split-Path -Parent (Split-Path -Parent $SetupDir)
$ReqFile = Join-Path $ProjectDir "requirements-all.txt"
$UiEntry = Join-Path $ProjectDir "ui\realtime_dashboard_v3_clean.py"

Write-Host "========== Packing env setup ==========" -ForegroundColor Cyan
Write-Host "Project: $ProjectDir"
Write-Host "Env:     $EnvName (Python $PythonVersion)"
Write-Host ""

if (!(Test-Path -LiteralPath $ReqFile)) {
    throw "Missing requirements file: $ReqFile"
}

function Find-Conda {
    if (Get-Command conda -ErrorAction SilentlyContinue) { return "conda" }
    $guess = "D:\ProgramData\anaconda3\Scripts\conda.exe"
    if (Test-Path -LiteralPath $guess) { return $guess }
    throw "conda not found. Install Anaconda/Miniconda first."
}

$Conda = Find-Conda
$envPattern = '^(\s*)' + [regex]::Escape($EnvName) + '(\s|$)'
$existing = & $Conda env list | Select-String -Pattern $envPattern

$EnvPython = Join-Path (Split-Path (Split-Path $Conda)) "envs\$EnvName\python.exe"
if ($Conda -eq "conda") {
    $condaBase = (& conda info --base 2>$null)
    if ($condaBase) { $EnvPython = Join-Path $condaBase "envs\$EnvName\python.exe" }
}

if ($existing) {
    Write-Host "Env $EnvName exists; reinstalling/upgrading packages." -ForegroundColor Yellow
} else {
    Write-Host "Creating conda env (may take 1-3 min)..." -ForegroundColor Yellow
    & $Conda create -n $EnvName "python=$PythonVersion" -y
}

if (!(Test-Path -LiteralPath $EnvPython)) {
    throw "Env python not found: $EnvPython"
}

Write-Host "Installing Python packages..." -ForegroundColor Yellow
& $EnvPython -m pip install --upgrade pip
& $EnvPython -m pip install -r $ReqFile

Write-Host ""
Write-Host "Verifying imports..." -ForegroundColor Yellow
$verifyCmd = "from ortools.sat.python import cp_model; import numpy, pandas, yaml, openpyxl; from PyQt5 import QtWidgets; import pyqtgraph; print('numpy', numpy.__version__); print('pandas', pandas.__version__); print('all OK')"
& $EnvPython -c $verifyCmd

Write-Host ""
Write-Host "========== Done ==========" -ForegroundColor Green
Write-Host "Activate: conda activate $EnvName"
Write-Host "Python:   $EnvPython"
Write-Host "Run V3:   & `"$EnvPython`" `"$UiEntry`""
Write-Host "Or:       $(Join-Path $SetupDir 'run_dashboard_v3.ps1')"
