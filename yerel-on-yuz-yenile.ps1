# Yalniz arayuzu (Next standalone, :8502) yeniden baslatir; SurrealDB, API ve isci calismaya devam eder.
# Arayuz yeniden derlenince kullan (bun --bun run build). Gomme isi kesilmez.
# Her zaman ayri bir kabuktan cagir: Start-Process powershell -WindowStyle Hidden -File yerel-on-yuz-yenile.ps1
# 2026-10-01: arayuz Claude'un komut kabugundan dogrudan baslatilinca o kabuk kapaninca (agac olarak) oldu;
# bu betik bitince bun oksuz kalir, kimse onu agaciyla birlikte kapatamaz.
$ErrorActionPreference = "Stop"
$D = $PSScriptRoot
$sa = "$D\frontend\.next\standalone"

$eski = (Get-Content "$D\logs\pids.txt" | Where-Object { $_ -like "frontend=*" } | Select-Object -Last 1) -replace "frontend=", ""
if ($eski) { cmd /c "taskkill /T /F /PID $eski >nul 2>&1" }  # cmd icinde: PS 5.1 stderr'i hata sayar
while (Get-NetTCPConnection -State Listen -LocalPort 8502 -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 300 }

# Derleme standalone'u yeniden yazar; static/public'i Next kendisi kopyalamaz.
Copy-Item -Recurse -Force "$D\frontend\.next\static" "$sa\.next\static"
Copy-Item -Recurse -Force "$D\frontend\public" "$sa\public"

Get-Content "$D\.env" | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
}
$env:PORT = "8502"; $env:HOSTNAME = "127.0.0.1"

$p = Start-Process -FilePath "C:\Users\buzbe\.bun\bin\bun.exe" -ArgumentList @("--bun", "server.js") `
    -WorkingDirectory $sa -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$D\logs\frontend.log" -RedirectStandardError "$D\logs\frontend.err.log"
$diger = @(Get-Content "$D\logs\pids.txt" -ErrorAction SilentlyContinue | Where-Object { $_ -notlike "frontend=*" })
$diger + "frontend=$($p.Id)" | Set-Content "$D\logs\pids.txt"
Write-Host "arayuz yeniden baslatildi (PID $($p.Id))"
