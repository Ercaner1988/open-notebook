# Yalniz isciyi (commands.ordered_worker) yeniden baslatir; isci kodu degisince kullan.
# Kuyrugu duraklatir, calisan isin bitmesini bekler, isciyi yeniler, kuyrugu eski haline dondurur.
# Her zaman ayri bir kabuktan cagir: Start-Process powershell -WindowStyle Hidden -File yerel-isci-yenile.ps1
$ErrorActionPreference = "Stop"
$D = $PSScriptRoot
Set-Location $D
$UV = "C:\Users\buzbe\AppData\Local\hermes\bin\uv.exe"
$Q = "http://127.0.0.1:5055/api/embedding-queue"

$ozet = Invoke-RestMethod "$Q/summary" -TimeoutSec 60
$duraklamisti = $ozet.paused
if (-not $duraklamisti) { Invoke-RestMethod -Method Post "$Q/pause" | Out-Null }
while ((Invoke-RestMethod "$Q/summary" -TimeoutSec 60).counts.running -gt 0) { Start-Sleep 10 }

$eski = (Get-Content "$D\logs\pids.txt" | Where-Object { $_ -like "worker=*" } | Select-Object -Last 1) -replace "worker=", ""
if ($eski) { cmd /c "taskkill /T /F /PID $eski >nul 2>&1" }  # cmd icinde: PS 5.1 stderr'i hata sayar

Get-Content "$D\.env" | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
}
$env:SURREAL_URL = "ws://127.0.0.1:8000/rpc"
$env:SURREAL_NAMESPACE = "open_notebook"
$env:SURREAL_DATABASE = "open_notebook"
$env:UV_NO_SYNC = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"

$p = Start-Process -FilePath $UV -ArgumentList @("run", "--no-sync", "python", "-m", "commands.ordered_worker") `
    -WorkingDirectory $D -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$D\logs\worker.log" -RedirectStandardError "$D\logs\worker.err.log"
$diger = @(Get-Content "$D\logs\pids.txt" -ErrorAction SilentlyContinue | Where-Object { $_ -notlike "worker=*" })
$diger + "worker=$($p.Id)" | Set-Content "$D\logs\pids.txt"

if (-not $duraklamisti) { Invoke-RestMethod -Method Post "$Q/resume" | Out-Null }
Write-Host "isci yeniden baslatildi (PID $($p.Id))"
