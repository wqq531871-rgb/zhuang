# Run V3 dashboard inside conda env packing-zhuang

$ErrorActionPreference = "Stop"
$EnvName = "packing-zhuang"

$SetupDir = $PSScriptRoot
$ProjectDir = Split-Path -Parent (Split-Path -Parent $SetupDir)
$UiEntry = Join-Path $ProjectDir "ui\realtime_dashboard_v3_clean.py"

function Find-Conda {
    if (Get-Command conda -ErrorAction SilentlyContinue) { return "conda" }
    $guess = "D:\ProgramData\anaconda3\Scripts\conda.exe"
    if (Test-Path -LiteralPath $guess) { return $guess }
    throw "conda not found. Run setup_packing_env.ps1 first."
}

$Conda = Find-Conda
$envPattern = '^(\s*)' + [regex]::Escape($EnvName) + '(\s|$)'
$existing = & $Conda env list | Select-String -Pattern $envPattern
if (-not $existing) {
    throw "Env $EnvName not found. Run: .\setup_packing_env.ps1"
}

$EnvPython = "D:\ProgramData\anaconda3\envs\$EnvName\python.exe"
$condaBase = (& conda info --base 2>$null)
if ($condaBase) { $EnvPython = Join-Path $condaBase "envs\$EnvName\python.exe" }
if (!(Test-Path -LiteralPath $EnvPython)) {
    throw "Env python not found: $EnvPython"
}

Set-Location $ProjectDir
& $EnvPython $UiEntry @args
