# Manifest winget

Salinan manifest yang dikirim ke [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs).

Untuk versi baru: salin folder versi terakhir, ganti `PackageVersion`, `InstallerUrl`, `InstallerSha256` (dari catatan rilis), `ReleaseDate`, dan `ReleaseNotesUrl`, lalu cek dengan:

```powershell
winget validate --manifest packaging\winget\manifests\m\mohammadrafly\SpotifyNowPlaying\<versi>
```

Setelah itu kirim sebagai pull request baru ke winget-pkgs.
