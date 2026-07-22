$ErrorActionPreference = "Continue"
$env:PYTHONNOUSERSITE = "1"
$proj = "P:\packing-system"
$py = "P:\PackingPortable\python\python.exe"
$log = "P:\packing-system\packaging\build_detached.log"
$outLog = "P:\packing-system\packaging\build_pyi_stdout.log"
$errLog = "P:\packing-system\packaging\build_pyi_stderr.log"
function Log($m){ Add-Content -Path $log -Value $m -Encoding UTF8 }
cmd /c "subst P: /d" | Out-Null
cmd /c "subst P: E:\Homework\AA装箱\A装箱和可视化\zhuang" | Out-Null
Set-Content -Path $log -Value ("START " + (Get-Date)) -Encoding UTF8
if (-not (Test-Path "P:\packing-system\packing\freeze_entry.py")) { Log "SUBST_FAIL"; exit 1 }
if (Test-Path "$proj\run_packing.py") { Move-Item -Force "$proj\run_packing.py" "$proj\run_packing.py.__buildhide" }
$exit = 1
try {
  Set-Location $proj
  Log "Running PyInstaller..."
  $p = Start-Process -FilePath $py -ArgumentList @("-m","PyInstaller","--noconfirm","--clean","--distpath","$proj\packaging\build_work\dist","--workpath","$proj\packaging\build_work\build","$proj\packaging\PackingWorkbench.spec") -Wait -PassThru -NoNewWindow -RedirectStandardOutput $outLog -RedirectStandardError $errLog
  $exit = $p.ExitCode
  Log ("PYI_EXIT=" + $exit)
  if ($exit -eq 0) {
    $built = "$proj\packaging\build_work\dist\PackingWorkbench"
    $out = "P:\release\PackingWorkbench"
    if (Test-Path $out) { Remove-Item -Recurse -Force $out }
    Copy-Item -Recurse $built $out
    Copy-Item -Recurse "$proj\config" "$out\config" -Force
    New-Item -Force -ItemType Directory "$out\local_wcs_receiver" | Out-Null
    Copy-Item -Recurse "$proj\local_wcs_receiver\config" "$out\local_wcs_receiver\config" -Force
    foreach ($d in @("packing-workspace\data","packing-workspace\input\raw","packing-workspace\output\success","packing-workspace\output\fail","packing-workspace\runtime\packing-realtime\logs","packing-workspace\runtime\packing-realtime\temp","packing-workspace\runtime\packing-realtime\exports","local_wcs_receiver\logs")) {
      New-Item -Force -ItemType Directory "$out\$d" | Out-Null
    }
    Set-Content "$out\启动.bat" "@echo off`r`ncd /d `"%~dp0`"`r`nset PACKING_WORKSPACE=%~dp0packing-workspace`r`nstart `"`" `"%~dp0PackingWorkbench.exe`"`r`n" -Encoding ASCII
    Log "RELEASE_READY"
    $p2 = Start-Process -FilePath "$out\PackingWorkbench.exe" -ArgumentList @("--mode","packing") -Wait -PassThru -NoNewWindow -RedirectStandardOutput "$proj\packaging\pack_mode_out.log" -RedirectStandardError "$proj\packaging\pack_mode_err.log"
    Log ("pack_exit=" + $p2.ExitCode)
  }
} catch {
  Log ("EXCEPTION: " + $_.Exception.Message)
} finally {
  if (Test-Path "$proj\run_packing.py.__buildhide") { Move-Item -Force "$proj\run_packing.py.__buildhide" "$proj\run_packing.py"; Log "restored root run_packing" }
  Log ("END " + (Get-Date))
}
exit $exit
