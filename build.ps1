# Build SpotifyNowPlaying.exe (PyInstaller) lalu installer (Inno Setup).
# Pakai: powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$version = (Select-String -Path "spotify_now_playing\__init__.py" -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "== Spotify Now Playing v$version ==" -ForegroundColor Green

# 1. virtualenv bersih supaya bundle kecil
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
$py = ".venv\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r requirements.txt pyinstaller pillow
if ($LASTEXITCODE) { throw "pip install gagal" }

# 2. icon
if (-not (Test-Path "assets\icon.ico")) { & $py scripts\make_icon.py }

# 3. exe (folder, bukan onefile: start lebih cepat & lebih jarang dicurigai antivirus)
& $py -m PyInstaller --noconfirm --clean `
    --name SpotifyNowPlaying `
    --icon assets\icon.ico `
    --add-data "spotify_now_playing\web;spotify_now_playing\web" `
    --collect-submodules winrt `
    --collect-binaries winrt `
    --hidden-import typing_extensions `
    run.py
if ($LASTEXITCODE) { throw "PyInstaller gagal" }

# 4. installer
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Warning "Inno Setup tidak ditemukan (winget install JRSoftware.InnoSetup). Exe ada di dist\SpotifyNowPlaying\"
    exit 0
}
& $iscc /Q "/DAppVersion=$version" installer.iss
if ($LASTEXITCODE) { throw "Inno Setup gagal" }

Write-Host "`nSelesai: dist\SpotifyNowPlaying-Setup-$version.exe" -ForegroundColor Green
