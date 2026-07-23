# Rebuild Windows release — onefile（无 _internal、无 .py 源码树）
# Usage:
#   powershell -ExecutionPolicy Bypass -File packing-system\tools\build_release.ps1
#
# Output layout:
#   release\PackingWorkbench\
#     PackingWorkbench.exe
#     config\
#     local_wcs_receiver\config\
#     packing-workspace\
#     启动.bat
#     使用说明.txt

$ErrorActionPreference = "Stop"

$ToolsDir = $PSScriptRoot
$ProjectDir = (Resolve-Path (Split-Path -Parent $ToolsDir)).Path
$RepoRoot = (Resolve-Path (Split-Path -Parent $ProjectDir)).Path
$DistRoot = Join-Path $RepoRoot "release"
$OutDir = Join-Path $DistRoot "PackingWorkbench"
$Drive = "P"
$MappedRoot = "${Drive}:"
$UsedSubst = $false

Write-Host "========== Build PackingWorkbench (onefile) ==========" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"

function Ensure-AsciiMapping {
    if ($RepoRoot -notmatch '[^\x00-\x7F]') {
        return $RepoRoot
    }
    Write-Host "Non-ASCII path detected; mapping repo to ${MappedRoot}\ via subst" -ForegroundColor Yellow
    cmd /c "subst $MappedRoot /d" 2>$null | Out-Null
    cmd /c "subst $MappedRoot `"$RepoRoot`"" | Out-Null
    if (-not (Test-Path "$MappedRoot\packing-system\app_launcher.py")) {
        throw "subst mapping failed for $RepoRoot"
    }
    $script:UsedSubst = $true
    return $MappedRoot
}

try {
    $BuildRoot = Ensure-AsciiMapping
    $BuildProject = Join-Path $BuildRoot "packing-system"
    $Spec = Join-Path $BuildProject "packaging\PackingWorkbench.spec"
    $WorkDir = Join-Path $BuildProject "packaging\build_work"
    $PortablePy = Join-Path $BuildRoot "PackingPortable\python\python.exe"

    if (-not (Test-Path $Spec)) { throw "Missing spec: $Spec" }

    if (Test-Path $PortablePy) {
        $PyExe = $PortablePy
        Write-Host "Using portable Python: $PyExe" -ForegroundColor Green
    } else {
        throw "PackingPortable\python not found."
    }

    function Invoke-Py {
        param([Parameter(ValueFromRemainingArguments = $true)]$Args)
        & $PyExe @Args
        if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Args" }
    }

    Write-Host "Ensuring build deps..." -ForegroundColor Yellow
    Invoke-Py -m pip install -q "pyinstaller>=6.0" pymysql

    New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
    New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
    $pyiDist = Join-Path $WorkDir "dist"
    $pyiBuild = Join-Path $WorkDir "build"
    if (Test-Path $pyiDist) { Remove-Item -Recurse -Force $pyiDist }
    if (Test-Path $pyiBuild) { Remove-Item -Recurse -Force $pyiBuild }

    Write-Host "Running PyInstaller onefile (several minutes)..." -ForegroundColor Yellow

    $rootRunPacking = Join-Path $ProjectDir "run_packing.py"
    $rootRunPackingHide = Join-Path $ProjectDir "run_packing.py.__buildhide"
    $hidRoot = $false
    if (Test-Path $rootRunPacking) {
        Move-Item -Force $rootRunPacking $rootRunPackingHide
        $hidRoot = $true
    }

    Push-Location $BuildProject
    try {
        Invoke-Py -m PyInstaller `
            --noconfirm `
            --clean `
            --distpath $pyiDist `
            --workpath $pyiBuild `
            $Spec
    }
    finally {
        Pop-Location
        if ($hidRoot -and (Test-Path $rootRunPackingHide)) {
            Move-Item -Force $rootRunPackingHide $rootRunPacking
        }
    }

    # onefile: dist\PackingWorkbench.exe
    $builtExe = Join-Path $pyiDist "PackingWorkbench.exe"
    if (-not (Test-Path $builtExe)) {
        # 兼容偶发仍产出目录包的情况
        $alt = Join-Path $pyiDist "PackingWorkbench\PackingWorkbench.exe"
        if (Test-Path $alt) { $builtExe = $alt }
        else { throw "Build finished but exe missing: $builtExe" }
    }

    if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    Copy-Item $builtExe (Join-Path $OutDir "PackingWorkbench.exe")

    # 确保没有把 _internal 带进交付目录
    $internal = Join-Path $OutDir "_internal"
    if (Test-Path $internal) { Remove-Item -Recurse -Force $internal }

    $cfgSrc = Join-Path $ProjectDir "config"
    $cfgDst = Join-Path $OutDir "config"
    Copy-Item -Recurse $cfgSrc $cfgDst

    $recvCfgSrc = Join-Path $ProjectDir "local_wcs_receiver\config"
    $recvCfgDst = Join-Path $OutDir "local_wcs_receiver\config"
    New-Item -ItemType Directory -Force -Path (Split-Path $recvCfgDst) | Out-Null
    Copy-Item -Recurse $recvCfgSrc $recvCfgDst

    @(
        "packing-workspace\data",
        "packing-workspace\input\raw",
        "packing-workspace\output\success",
        "packing-workspace\output\fail",
        "packing-workspace\output\success_case",
        "packing-workspace\runtime\packing-realtime\logs",
        "packing-workspace\runtime\packing-realtime\temp",
        "packing-workspace\runtime\packing-realtime\exports",
        "local_wcs_receiver\logs"
    ) | ForEach-Object {
        New-Item -ItemType Directory -Force -Path (Join-Path $OutDir $_) | Out-Null
    }

    # 清理交付目录里误拷的 .py（防御）
    Get-ChildItem $OutDir -Recurse -Filter "*.py" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\config\\' } |
        Remove-Item -Force -ErrorAction SilentlyContinue

    $readme = @"
装箱工作台 — 交付说明（单 exe）
====================

目录应只有：
  PackingWorkbench.exe
  config\
  local_wcs_receiver\config\
  packing-workspace\
  启动.bat
  使用说明.txt

没有 _internal，也没有 .py 源码。

1. 双击 PackingWorkbench.exe 或 启动.bat
2. 生产：运行方式选接口模式，再一键装箱
3. 可改：config\packing_config.yaml
4. 结果：packing-workspace\output\ （下传成功托盘在 output\success_case\）
5. 首次启动会稍慢（解压到本机 AppData），之后会快一些

开发侧重新打包：
  powershell -ExecutionPolicy Bypass -File packing-system\tools\build_release.ps1
"@
    Set-Content -Path (Join-Path $OutDir "使用说明.txt") -Value $readme -Encoding UTF8

    $bat = @"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PACKING_WORKSPACE=%~dp0packing-workspace
start "" "%~dp0PackingWorkbench.exe"
"@
    Set-Content -Path (Join-Path $OutDir "启动.bat") -Value $bat -Encoding ASCII

    $gi = Join-Path $RepoRoot ".gitignore"
    if (Test-Path $gi) {
        $text = Get-Content $gi -Raw
        if ($text -notmatch '(?m)^release/') {
            Add-Content $gi "`n# PyInstaller release output`nrelease/`n"
        }
    }

    $size = [math]::Round(((Get-ChildItem $OutDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
    Write-Host "DONE: $OutDir ($size MB)" -ForegroundColor Green
    Write-Host "Contents:" -ForegroundColor Green
    Get-ChildItem $OutDir | ForEach-Object { Write-Host ("  " + $_.Name) }
}
finally {
    if ($UsedSubst) {
        cmd /c "subst $MappedRoot /d" 2>$null | Out-Null
    }
}
