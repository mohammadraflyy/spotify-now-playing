# Jalankan exe hasil build sebentar dan cek bahwa server, halaman, dan API merespons.
# Menangkap masalah khusus PyInstaller (modul/file yang tidak ikut ter-bundle) sebelum rilis.
# Pakai: powershell -ExecutionPolicy Bypass -File scripts\smoke_test.ps1
param(
    [string]$Exe = "dist\SpotifyNowPlaying\SpotifyNowPlaying.exe",
    [int]$Port = 8799
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$expected = (Select-String -Path "spotify_now_playing\__init__.py" -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
$data = Join-Path $env:TEMP "snp-smoke-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory $data | Out-Null
$oldAppData = $env:APPDATA
$env:APPDATA = $data  # pengaturan terpisah: tidak menyentuh config.json asli

$proc = Start-Process $Exe -ArgumentList "--port", $Port, "--no-browser" -PassThru
try {
    $base = "http://127.0.0.1:$Port"
    $cfg = $null
    for ($i = 0; $i -lt 60 -and -not $cfg; $i++) {
        Start-Sleep -Milliseconds 500
        if ($proc.HasExited) { throw "Exe berhenti dengan kode $($proc.ExitCode)" }
        try { $cfg = Invoke-RestMethod "$base/api/config" -TimeoutSec 2 } catch {}
    }
    if (-not $cfg) { throw "Server tidak merespons dalam 30 detik" }
    if ($cfg.version -ne $expected) { throw "Versi $($cfg.version), seharusnya $expected" }

    $paths = "/settings", "/overlay", "/lyrics", "/requests", "/api/now", "/api/lyrics", "/api/requests",
             "/api/chat", "/api/history", "/api/diagnostics", "/static/fonts/inter-latin.woff2", "/static/i18n.js"
    foreach ($path in $paths) {
        $r = Invoke-WebRequest "$base$path" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -ne 200) { throw "$path -> $($r.StatusCode)" }
    }

    Start-Sleep -Seconds 2  # beberapa tick loop utama
    if ($proc.HasExited) { throw "Exe berhenti dengan kode $($proc.ExitCode)" }
    $log = Join-Path $data "SpotifyNowPlaying\app.log"
    if ((Test-Path $log) -and (Select-String -Path $log -Pattern " ERROR " -Quiet)) {
        Get-Content $log | Write-Host
        throw "Ada error di app.log"
    }
    Write-Host "Smoke test OK: v$($cfg.version), $($paths.Count) halaman/API merespons" -ForegroundColor Green
}
finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    $env:APPDATA = $oldAppData
    Start-Sleep -Milliseconds 500
    Remove-Item -Recurse -Force $data -ErrorAction SilentlyContinue
}
