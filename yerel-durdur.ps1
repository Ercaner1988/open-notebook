# yerel-baslat.ps1 ile acilan surecleri (alt surecleriyle birlikte) kapatir. Once worker/API, en son veritabani.
$f = "$PSScriptRoot\logs\pids.txt"
if (-not (Test-Path $f)) { Write-Host "calisan kayit yok"; exit }
$pids = Get-Content $f | ForEach-Object { $k, $v = $_ -split '='; [pscustomobject]@{ ad = $k; id = $v } }
foreach ($ad in "frontend", "worker", "api", "surrealdb") {
    # Ayni adda birden cok satir olabilir (orn. yerel-api-yenile.ps1'in eski surumu ekliyordu);
    # hepsini tek tek kapat - tek taskkill'e dizi verince hicbirini kapatmiyordu.
    $p = @($pids | Where-Object ad -eq $ad)
    foreach ($x in $p) { taskkill /T /F /PID $x.id 2>$null | Out-Null }
    if ($p) { Write-Host "$ad durduruldu" }
}
Remove-Item $f
