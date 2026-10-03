# Open Notebook'u Docker'siz baslatir: surreal.exe (Rust) + uvicorn API + worker + Next.js (Bun).
# Durdurmak: .\yerel-durdur.ps1   Loglar: .\logs\*.log
$ErrorActionPreference = "Stop"
$D = $PSScriptRoot
Set-Location $D
New-Item -ItemType Directory -Force "$D\logs" | Out-Null
if (Get-NetTCPConnection -State Listen -LocalPort 5055 -ErrorAction SilentlyContinue) { Write-Host "zaten calisiyor"; exit }
$UV = "C:\Users\buzbe\AppData\Local\hermes\bin\uv.exe"  # oturum acilisinda PATH'e guvenilmiyor (bkz. OmniRoute.vbs)
$BUN = "C:\Users\buzbe\.bun\bin\bun.exe"

# .env'deki degerleri ortam degiskeni yap (gizli degerler ekrana basilmaz)
Get-Content "$D\.env" | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
}
$env:SURREAL_URL = "ws://127.0.0.1:8000/rpc"
$env:SURREAL_NAMESPACE = "open_notebook"
$env:SURREAL_DATABASE = "open_notebook"
$env:UV_NO_SYNC = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"

# ./data -> notebook_data (config.py DATA_FOLDER="./data")
if (-not (Test-Path "$D\data")) { New-Item -ItemType Junction -Path "$D\data" -Target "$D\notebook_data" | Out-Null }

# Next standalone ciktisi static/public'i kendisi kopyalamaz (Dockerfile'daki COPY adimlari)
$sa = "$D\frontend\.next\standalone"
if (-not (Test-Path "$sa\.next\static")) {
    Copy-Item -Recurse "$D\frontend\.next\static" "$sa\.next\static"
    Copy-Item -Recurse "$D\frontend\public" "$sa\public"
}

function Basla($ad, $exe, $argv, $dir = $D) {
    $argv = $argv | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }  # Start-Process bosluklu argumani tirnaklamaz
    $p = Start-Process -FilePath $exe -ArgumentList $argv -WorkingDirectory $dir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput "$D\logs\$ad.log" -RedirectStandardError "$D\logs\$ad.err.log"
    "$ad=$($p.Id)" | Add-Content "$D\logs\pids.txt"
    Write-Host "$ad baslatildi (PID $($p.Id))"
    $p
}

Remove-Item "$D\logs\pids.txt" -ErrorAction SilentlyContinue
Basla "surrealdb" "C:\Users\buzbe\.surrealdb\surreal.exe" @("start", "--log", "info", "--bind", "127.0.0.1:8000",
    "--user", $env:SURREAL_USER, "--pass", $env:SURREAL_PASSWORD, "rocksdb:$D\surreal_data\mydatabase.db") | Out-Null
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; $ok = $true; break } catch { Start-Sleep 1 }
}
if (-not $ok) { throw "SurrealDB ayaga kalkmadi, bkz. logs\surrealdb.err.log" }

# Beklenmedik kapanista 'running' kalan isler worker'ca hic alinmaz (yalniz 'new' okur); worker henuz yokken geri kuyruga koy.
$auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$($env:SURREAL_USER):$($env:SURREAL_PASSWORD)"))
Invoke-RestMethod "http://127.0.0.1:8000/sql" -Method Post -Body "UPDATE command SET status='new' WHERE status='running';" `
    -Headers @{ Authorization = "Basic $auth"; "surreal-ns" = "open_notebook"; "surreal-db" = "open_notebook"; Accept = "application/json" } | Out-Null

$env:PORT = "8502"; $env:HOSTNAME = "127.0.0.1"
Basla "api" $UV @("run", "--no-sync", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "5055") | Out-Null
# 2026-09-29: stok surreal-commands-worker yerine sirali isci (feat/embedding-queue dali):
# isleri tek tek alir, Advanced > Gomme kuyrugu'ndan duraklatilir/siralanir.
# Geri donus: asagidaki satiri eski haline getir:
#   Basla "worker" $UV @("run","--no-sync","surreal-commands-worker","--import-modules","commands","--max-tasks","1")
Basla "worker" $UV @("run", "--no-sync", "python", "-m", "commands.ordered_worker") | Out-Null
Basla "frontend" $BUN @("--bun", "server.js") $sa | Out-Null
Write-Host "Arayuz: http://127.0.0.1:8502  API: http://127.0.0.1:5055"
