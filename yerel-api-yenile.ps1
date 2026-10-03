# Yalniz API'yi (uvicorn :5055) yeniden baslatir; SurrealDB, isci ve arayuz calismaya devam eder.
# API kodu degisince kullan: gomme isi kesilmez. Migration da API acilisinda kosar.
# Her zaman ayri bir kabuktan cagir (Start-Process powershell -WindowStyle Hidden -File ...):
# dogrudan uzun omurlu bir kabuktan baslatilan hizmet, o kabuk kapaninca onunla birlikte oluyor.
$ErrorActionPreference = "Stop"
$D = $PSScriptRoot
Set-Location $D
$UV = "C:\Users\buzbe\AppData\Local\hermes\bin\uv.exe"

$eski = (Get-Content "$D\logs\pids.txt" | Where-Object { $_ -like "api=*" } | Select-Object -Last 1) -replace "api=", ""
# taskkill cmd icinde: PS 5.1 "Stop" altinda stderr satirini (orn. "not found") hata sayip betigi keser, yeni api hic baslamaz.
if ($eski) { cmd /c "taskkill /T /F /PID $eski >nul 2>&1" }
while (Get-NetTCPConnection -State Listen -LocalPort 5055 -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 300 }

Get-Content "$D\.env" | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
}
$env:SURREAL_URL = "ws://127.0.0.1:8000/rpc"
$env:SURREAL_NAMESPACE = "open_notebook"
$env:SURREAL_DATABASE = "open_notebook"
$env:UV_NO_SYNC = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"

$p = Start-Process -FilePath $UV -ArgumentList @("run", "--no-sync", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "5055") `
    -WorkingDirectory $D -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$D\logs\api.log" -RedirectStandardError "$D\logs\api.err.log"
# Eski api= satirini degistir (eklemek, yerel-durdur.ps1'de ayni adda iki satir birakiyordu).
$diger = @(Get-Content "$D\logs\pids.txt" -ErrorAction SilentlyContinue | Where-Object { $_ -notlike "api=*" })
$diger + "api=$($p.Id)" | Set-Content "$D\logs\pids.txt"
Write-Host "api yeniden baslatildi (PID $($p.Id))"
