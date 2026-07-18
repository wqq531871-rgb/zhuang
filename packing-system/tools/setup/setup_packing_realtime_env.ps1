# -*- coding: utf-8 -*-
# 可选：若希望单独建虚拟环境再装依赖，可运行本脚本。
# 日常用系统 Python 3.12 + pip install -r requirements 即可，不必跑这个。

$ErrorActionPreference = "Stop"

Write-Host "========== Packing Realtime Environment Setup (optional) ==========" -ForegroundColor Cyan
Write-Host "推荐：直接用系统 Python，无需虚拟环境。" -ForegroundColor Yellow
Write-Host "  pip install -r apps\realtime_dashboard\requirements_realtime.txt" -ForegroundColor Yellow
Write-Host "  pip install -r code\requirements.txt" -ForegroundColor Yellow
Write-Host ""

$SetupDir = $PSScriptRoot
$ToolsDir = Split-Path -Parent $SetupDir
$ProjectDir = Split-Path -Parent $ToolsDir
$WorkspaceDir = Split-Path -Parent $ProjectDir

$VenvDir = Join-Path $WorkspaceDir ".venvs\packing-realtime"
$RuntimeDir = Join-Path $WorkspaceDir "runtime\packing-realtime"
$LogsDir = Join-Path $RuntimeDir "logs"
$TempDir = Join-Path $RuntimeDir "temp"
$ExportsDir = Join-Path $RuntimeDir "exports"
$ReqFile = Join-Path $ProjectDir "apps\realtime_dashboard\requirements_realtime.txt"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
New-Item -ItemType Directory -Force -Path $ExportsDir | Out-Null

if (!(Test-Path -LiteralPath $ReqFile)) {
    throw "找不到 requirements 文件：$ReqFile"
}

$confirm = Read-Host "仍要创建 .venvs\packing-realtime 吗？(y/N)"
if ($confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "已取消。请用系统 Python 安装依赖后直接启动 bat。" -ForegroundColor Green
    exit 0
}

$PythonCmd = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $PythonCmd = "py" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $PythonCmd = "python" }
else { throw "没有找到 Python。" }

if (!(Test-Path -LiteralPath $VenvDir)) {
    Write-Host "正在创建虚拟环境..." -ForegroundColor Yellow
    if ($PythonCmd -eq "py") { & py -3 -m venv $VenvDir }
    else { & python -m venv $VenvDir }
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (!(Test-Path -LiteralPath $VenvPython)) {
    throw "虚拟环境创建失败：$VenvPython"
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $ReqFile

Write-Host "完成：$VenvDir" -ForegroundColor Green
Write-Host "注意：当前启动 bat 已改用系统 Python，不会自动使用此 venv。" -ForegroundColor Yellow
