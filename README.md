# Spotify Now Playing untuk OBS

Menampilkan lagu yang sedang diputar dan lirik tersinkron dari Spotify di OBS.

- **Overlay now playing**: cover, judul, artis, dan progress bar
- **Overlay lirik**: tampil seperti di Spotify, dengan latar mengikuti warna cover lagu. Liriknya dari [LRCLIB](https://lrclib.net)
- **File teks dan cover** untuk OBS Text/Image source
- **Halaman pengaturan** di browser

---

## Cara pakai

### 1. Install dan jalankan

1. Jalankan `SpotifyNowPlaying-Setup-1.1.0.exe`.
   - Kalau muncul peringatan Windows SmartScreen, klik **More info → Run anyway**.
   - Installer tidak butuh admin. Centang **Jalankan otomatis saat Windows menyala** kalau mau aplikasinya selalu siap.
2. Buka **Spotify Now Playing** dari Start Menu atau desktop. Jendela console akan muncul dan menampilkan lagu yang sedang diputar.
3. **Biarkan jendela itu terbuka** selama streaming. Boleh di-minimize, tapi jangan ditutup.
4. Pada pemakaian pertama, halaman pengaturan terbuka otomatis. Setelahnya, buka lewat Start Menu → **Pengaturan (browser)**, atau ketik `http://127.0.0.1:8765/settings` di browser.

### 2. Pilih sumber data

Atur di halaman pengaturan, bagian **2. Akun & Sumber Data**.

| Mode | Kapan dipakai | Butuh |
|---|---|---|
| **Lokal** *(paling gampang)* | Spotify diputar di PC yang sama dengan OBS | Spotify Desktop terbuka dan sedang memutar lagu |
| **Akun Spotify** | Musik diputar dari HP, speaker, atau PC lain | Client ID dan login. Pemilik app harus **Premium** |
| **Otomatis** | Memakai akun kalau bisa, kalau tidak pindah ke Lokal | — |

> Mode **Lokal** langsung jalan tanpa setup apa pun. Lanjutkan ke langkah 3.

<details>
<summary><b>Setup mode Akun Spotify (opsional)</b></summary>

1. Buka https://developer.spotify.com/dashboard → **Create app**. Login dengan akun **Premium**.
2. Isi nama dan deskripsi app bebas, lalu centang **Web API**.
3. Di **Redirect URIs**, isi persis `http://127.0.0.1:8765/callback` → **Add** → **Save**.
4. Buka **Settings → User Management**, lalu tambahkan nama dan email akun Spotify kamu.
5. Copy **Client ID**, paste ke halaman pengaturan bagian **1. Spotify App**, lalu klik **Simpan**. Client Secret boleh dikosongkan.
6. Klik **Login dengan Spotify**, lalu **Agree**.

Kalau muncul error:

| Error | Solusi |
|---|---|
| `redirect_uri: Not matching configuration` | Redirect URI di dashboard belum persis `http://127.0.0.1:8765/callback`, atau belum di-**Save** |
| `403 user is not registered` | Tambahkan email kamu di **User Management** |
| `403 premium subscription required for the owner` | Akun pembuat app di dashboard bukan Premium, atau statusnya belum terbaca oleh Spotify (tunggu beberapa jam) |

</details>

### 3. Tambahkan ke OBS

#### a. Overlay Now Playing (kartu lagu)

**Cara cepat:** buka halaman pengaturan, lalu **seret kotak hijau** di bagian *3. Tambahkan ke OBS* ke jendela preview OBS.

**Cara manual:**
1. Di OBS, buka panel **Sources** → klik **+** → **Browser**.
2. Beri nama, misalnya `Spotify Now Playing` → OK.
3. Isi:
   - **URL**: `http://127.0.0.1:8765/overlay`
   - **Width**: `480`, **Height**: `130`
4. Klik **OK**, lalu atur posisinya di scene.

Pilihan tampilan bisa diatur di halaman pengaturan, atau langsung lewat parameter URL:

| Parameter | Fungsi |
|---|---|
| `?hidePaused=1` | sembunyikan kartu saat lagu di-pause |
| `?noProgress=1` | sembunyikan progress bar |
| `?accent=ff0066` | ganti warna aksen (hex tanpa `#`) |

Contoh: `http://127.0.0.1:8765/overlay?hidePaused=1&accent=ff0066`

#### b. Overlay Lirik (seperti di Spotify)

1. OBS → **Sources** → **+** → **Browser** → beri nama `Spotify Lyrics`.
2. Isi **URL** `http://127.0.0.1:8765/lyrics`, **Width** `800`, **Height** `300` → OK.
3. Atur tampilannya di halaman pengaturan bagian **4. Lirik ke OBS**. Perubahannya langsung terlihat di OBS tanpa ganti URL:
   - **Gaya**: *Daftar bergulir* (beberapa baris) atau *Satu baris* (pakai Height sekitar `120`)
   - **Latar**:
     - *Warna lagu*: diambil otomatis dari cover album, dengan gradien yang menggelap ke bawah, seperti di Spotify
     - *Warna tetap*: warna pilihan kamu
     - *Gelap*
     - *Transparan*: hanya teks
   - **Ukuran** dan **rata teks**
   - Baris yang sedang dinyanyikan berwarna putih, yang sudah lewat putih redup, dan yang berikutnya gelap
   - **Offset waktu**: geser ke **+** kalau lirik telat, ke **−** kalau terlalu cepat

Tidak semua lagu punya lirik tersinkron. Status lirik untuk lagu yang sedang diputar ditampilkan di halaman pengaturan.

#### c. Teks dan cover biasa (opsional)

Semua file ada di `Documents\Spotify Now Playing`. Tombol **Buka folder** ada di halaman pengaturan bagian 5.

| File | Isi | Source OBS |
|---|---|---|
| `nowplaying.txt` | `Artis - Judul` (format bisa diubah) | **Text (GDI+)** → centang *Read from file* |
| `title.txt` / `artist.txt` / `album.txt` | judul / artis / album | Text (GDI+) |
| `progress.txt` | `1:23 / 3:45` | Text (GDI+) |
| `lyrics.txt` | baris lirik yang sedang dinyanyikan | Text (GDI+) |
| `cover.jpg` | cover album | **Image** |

> Tips: untuk teks berjalan, klik kanan source Text → **Filters** → **+** → **Scroll**.

### 4. Kalau overlay tidak muncul atau tidak berubah

1. Pastikan jendela **Spotify Now Playing** masih terbuka.
2. Buka `http://127.0.0.1:8765/settings` dan lihat bagian **Status**. Kalau di sana lagunya muncul, berarti aplikasinya jalan.
3. Di OBS, klik kanan source Browser → **Properties** → **Refresh cache of current page**.
4. Untuk mode Lokal, lagu harus diputar di **Spotify Desktop di PC ini**, bukan di HP atau web player.

---

## Lokasi file

| Apa | Lokasi |
|---|---|
| Aplikasi | `%LOCALAPPDATA%\Programs\Spotify Now Playing` |
| Pengaturan dan login | `%APPDATA%\SpotifyNowPlaying\config.json`. Jangan dibagikan, karena berisi token login |
| File teks dan cover | `Documents\Spotify Now Playing` |

Uninstall lewat **Settings → Apps → Spotify Now Playing**, atau Start Menu → *Uninstall Spotify Now Playing*.

---

## Development

```powershell
pip install -r requirements.txt
python -m spotify_now_playing                         # jalankan dari source
powershell -ExecutionPolicy Bypass -File build.ps1    # build exe dan installer -> dist\
```

Build butuh Python 3.10+ dan [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`). Versi aplikasi diatur di `spotify_now_playing/__init__.py`.

Opsi command line: `--port 8766` untuk ganti port, `--no-browser` supaya halaman pengaturan tidak dibuka, dan `--version`.

### Struktur

```
spotify_now_playing/
  __main__.py     entry point, single-instance
  app.py          loop polling, state, file output
  spotify_api.py  OAuth (PKCE / secret) dan Web API
  local_media.py  Spotify Desktop lewat Windows Media Controls
  lyrics.py       lirik dari LRCLIB
  server.py       web server lokal dan API JSON
  config.py       lokasi file dan penyimpanan config
  web/            overlay.html, lyrics.html, settings.html
installer.iss     script Inno Setup
build.ps1         build PyInstaller dan installer
```
