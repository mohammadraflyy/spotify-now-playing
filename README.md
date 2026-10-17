# Spotify Now Playing untuk OBS

**[Download installer (Windows)](https://github.com/mohammadraflyy/spotify-now-playing/releases/latest)**

Menampilkan lagu yang sedang diputar dan lirik tersinkron dari Spotify di OBS.

![Contoh scene OBS dengan overlay now playing dan lirik](docs/screenshots/hero.png)

## Screenshot

| Kartu Now Playing | Lirik: latar warna lagu |
|---|---|
| ![Overlay now playing](docs/screenshots/overlay.png) | ![Overlay lirik dengan latar warna cover](docs/screenshots/lyrics.png) |

**Kartu bisa diatur ukuran dan latarnya**

![Variasi kartu now playing](docs/screenshots/card-variants.png)

**Lirik mode satu baris**

![Overlay lirik satu baris](docs/screenshots/lyrics-single.png)

**Halaman pengaturan** (`http://127.0.0.1:8765/settings`): panduan 3 langkah, dengan setiap pengaturan di tab terpisah dan preview langsung

| Beranda | Atur kartu |
|---|---|
| ![Halaman pengaturan: beranda](docs/screenshots/settings.png) | ![Halaman pengaturan: kartu](docs/screenshots/settings-card.png) |

- **Overlay now playing**: cover, judul, artis, dan progress bar
- **Overlay lirik**: tampil seperti di Spotify, dengan latar mengikuti warna cover lagu. Liriknya dari [LRCLIB](https://lrclib.net)
- **File teks dan cover** untuk OBS Text/Image source
- **Halaman pengaturan** di browser

---

## Cara pakai

### 1. Install dan jalankan

1. Download installer terbaru dari halaman **[Releases](https://github.com/mohammadraflyy/spotify-now-playing/releases/latest)**: file `SpotifyNowPlaying-Setup-x.y.z.exe` di bagian *Assets*. Lalu jalankan.
   - Kalau muncul peringatan Windows SmartScreen, klik **More info → Run anyway**.
   - Installer tidak butuh admin. Centang **Jalankan otomatis saat Windows menyala** kalau mau aplikasinya selalu siap.
2. Buka **Spotify Now Playing** dari Start Menu atau desktop. Jendela console akan muncul dan menampilkan lagu yang sedang diputar.
3. **Biarkan jendela itu terbuka** selama streaming. Boleh di-minimize, tapi jangan ditutup.
4. Pada pemakaian pertama, halaman pengaturan terbuka otomatis. Setelahnya, buka lewat Start Menu → **Pengaturan (browser)**, atau ketik `http://127.0.0.1:8765/settings` di browser.
5. Di tab **Beranda**, ikuti **3 langkah** yang ditampilkan. Langkah yang sudah selesai otomatis tercentang, dan tombol **Salin URL** tinggal ditempel di OBS.

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
   - **Width** dan **Height**: ikuti angka yang tertera di halaman pengaturan. Untuk ukuran default, `480` × `132`.
4. Klik **OK**, lalu atur posisinya di scene.

**Atur tampilan kartu** di halaman pengaturan, bagian **3. Tambahkan ke OBS**. Perubahannya langsung terlihat di OBS tanpa ganti URL:
- **Ukuran**:
  - Preset: *Kecil*, *Sedang*, *Besar*, *Lebar*
  - Atau atur sendiri **lebar**, **tinggi**, dan **sudut lengkung**, lewat slider atau dengan mengetik angka px secara manual. Cover dan teks ikut menyesuaikan tinggi kartu.
- **Latar**:
  - *Gelap*
  - *Warna lagu*: diambil otomatis dari cover
  - *Warna tetap*
  - *Transparan*
  - Ditambah pengaturan **opasitas**
- **Lainnya**: warna aksen, sembunyikan saat pause, tanpa progress bar, dan tanpa cover

> Setelah mengubah ukuran kartu, sesuaikan juga Width/Height Browser Source di OBS (klik kanan → Properties) dengan angka yang tertera di halaman pengaturan.

Semua opsi juga bisa ditimpa lewat parameter URL, misalnya untuk beberapa scene dengan gaya berbeda:

| Parameter | Fungsi |
|---|---|
| `width=460` `height=112` | ukuran kartu (px) |
| `radius=16` | sudut lengkung (px) |
| `bg=dark\|cover\|color\|none` | jenis latar |
| `color=282828` | warna latar untuk `bg=color` (hex tanpa `#`) |
| `opacity=82` | opasitas latar (0–100) |
| `accent=1db954` | warna aksen |
| `hidePaused=1` `noProgress=1` `noCover=1` | sembunyikan kartu saat pause, sembunyikan progress bar, sembunyikan cover |

Contoh: `http://127.0.0.1:8765/overlay?bg=cover&width=600&height=150`

#### b. Overlay Lirik (seperti di Spotify)

1. OBS → **Sources** → **+** → **Browser** → beri nama `Spotify Lyrics`.
2. Isi **URL** `http://127.0.0.1:8765/lyrics`, **Width** `800`, **Height** `300` → OK.
3. Atur tampilannya di halaman pengaturan bagian **4. Lirik ke OBS**. Perubahannya langsung terlihat di OBS tanpa ganti URL:
   - **Gaya**: *Daftar bergulir* (beberapa baris) atau *Satu baris* (pakai Height sekitar `120`)
   - **Latar**:
     - *Warna lagu*: diambil otomatis dari cover album. Bagian bawahnya menggelap lalu memudar halus menjadi transparan, sehingga menyatu dengan latar scene
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
