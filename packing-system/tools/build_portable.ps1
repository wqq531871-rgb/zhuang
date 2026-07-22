# 重建便携包（在开发机上运行；需要网络下载 embeddable Python / pip 包）
# 用法（在仓库 zhuang 根目录）:
#   powershell -ExecutionPolicy Bypass -File packing-system\tools\build_portable.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path (Join-Path $RepoRoot "packing-system\run_packing.py"))) {
    throw "无法定位仓库根目录：$RepoRoot"
}

$PortableRoot = Join-Path $RepoRoot "PackingPortable"
$PyDir = Join-Path $PortableRoot "python"
$AppSrc = Join-Path $RepoRoot "packing-system"
$AppDst = Join-Path $PortableRoot "packing-system"
$ReqFile = Join-Path $PortableRoot "requirements-portable.txt"
$PyVer = "3.12.7"
$EmbedUrl = "https://www.python.org/ftp/python/$PyVer/python-3.12.7-embed-amd64.zip"

Write-Host "Portable root: $PortableRoot" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path $PortableRoot | Out-Null
@(
    "packing-workspace\data",
    "packing-workspace\input\raw",
    "packing-workspace\output\success",
    "packing-workspace\output\fail",
    "packing-workspace\runtime\packing-realtime\logs",
    "packing-workspace\runtime\packing-realtime\temp",
    "packing-workspace\runtime\packing-realtime\exports"
) | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path $PortableRoot $_) | Out-Null
}

if (-not (Test-Path $ReqFile)) {
    @"
ortools==9.12.4544
pandas==2.2.2
numpy==1.26.4
openpyxl==3.1.5
PyYAML==6.0.2
PyQt5==5.15.10
pyqtgraph==0.13.7
PyOpenGL==3.1.7
requests>=2.28.0
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.0
typing_extensions>=4.8.0
"@ | Set-Content -Path $ReqFile -Encoding UTF8
}

if (-not (Test-Path (Join-Path $PyDir "python.exe"))) {
    Write-Host "Downloading embeddable Python $PyVer ..." -ForegroundColor Yellow
    $zip = Join-Path $PortableRoot "_python_embed.zip"
    Invoke-WebRequest -Uri $EmbedUrl -OutFile $zip -UseBasicParsing
    if (Test-Path $PyDir) { Remove-Item -Recurse -Force $PyDir }
    New-Item -ItemType Directory -Force -Path $PyDir | Out-Null
    Expand-Archive -Path $zip -DestinationPath $PyDir -Force
    Remove-Item $zip -Force
    @"
python312.zip
.
Lib\site-packages

import site
"@ | Set-Content -Path (Join-Path $PyDir "python312._pth") -Encoding ASCII
}

$PyExe = Join-Path $PyDir "python.exe"
$env:PYTHONNOUSERSITE = "1"

& $PyExe -c "import pip" 2>$null
if ($LASTEXITCODE -ne 0) {
    $getpip = Join-Path $PortableRoot "_get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip -UseBasicParsing
    & $PyExe $getpip --no-warn-script-location
    Remove-Item $getpip -Force -ErrorAction SilentlyContinue
}

Write-Host "Installing requirements ..." -ForegroundColor Yellow
& $PyExe -m pip install --no-warn-script-location -r $ReqFile

Write-Host "Syncing packing-system ..." -ForegroundColor Yellow
if (Test-Path $AppDst) { Remove-Item -Recurse -Force $AppDst }
$xd = @("__pycache__", ".pytest_cache", ".git", "tests", "htmlcov", "analysis-output", "temp")
$xf = @("*.pyc", "*.pyo", "*.log", "*.zip", ".coverage")
$xdArgs = foreach ($d in $xd) { @("/XD", $d) }
$xfArgs = foreach ($f in $xf) { @("/XF", $f) }
& robocopy $AppSrc $AppDst /E /NFL /NDL /NJH /NJS /nc /ns /np @xdArgs @xfArgs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $LASTEXITCODE" }

Write-Host "Done. Launch: $PortableRoot\启动装箱界面.bat" -ForegroundColor Green
