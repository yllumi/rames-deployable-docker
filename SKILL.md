---
name: rames-deployable-docker
description: Membuat docker-compose.yml (dan Dockerfile hanya bila benar-benar perlu) untuk project apa pun agar kompatibel dideploy di dashboard Rames. Selalu mengaudit codebase lebih dulu untuk menemukan environment variable yang benar-benar dipakai (bukan menyalin .env.example), lalu menuangkannya ke docker-compose dan .env.example. Prioritaskan image resmi Docker Hub tanpa membuat Dockerfile. Gunakan ketika user meminta "buatkan compose untuk Rames", "dockerize project ini", "pilih image Docker Hub", "audit env untuk docker", atau "Dockerfile + docker-compose untuk Rames".
---

# Rames Deployable Docker

Tujuan skill ini: menghasilkan app yang **langsung bisa dideploy** di dashboard Rames — compose valid, port benar, data persisten, environment aman, dan tidak bentrok dengan hal-hal yang dikelola Rames (nama project, nama container, host port, reverse proxy, SSL).

**Prinsip utama: image-first.** Selalu cari image resmi/tepercaya di Docker Hub lebih dulu. Buat Dockerfile **hanya** jika image yang tersedia tidak bisa menjalankan project tanpa kustomisasi build.

## Langkah 0 — Inventaris project

Sebelum menulis file, kumpulkan:

1. **Runtime & versi** — Node/PHP/Python/Ruby/Java/Go/.NET/static site.
2. **Entrypoint** — perintah start, port HTTP yang didengarkan (bukan port host).
3. **State persisten** — direktori database, upload, cache, SQLite, berkas konfigurasi yang ditulis saat runtime.
4. **Dependensi eksternal** — database, Redis, queue, object storage.
5. **Env wajib** — nama variabel + contoh nilai (jangan nilai rahasia nyata). **Jangan** ambil dari `.env.example` saja; turunkan dari pemakaian di kode lewat [Langkah 1](#langkah-1--audit-environment-variable-dari-codebase).
6. **Proses latar** — worker/cron. Compose dapat memuat beberapa service; jangan menaruh worker di dalam container web jika image resmi tidak mendukung.
7. **Arsitektur target** — server Rames bisa `x86_64` atau `aarch64`; pastikan image multi-arch.

Jika project sudah punya `Dockerfile`/compose, **audit dulu** terhadap kontrak di bawah; jangan langsung menulis ulang.

## Langkah 1 — Audit environment variable dari codebase

**Aturan keras: isi `environment:` di compose diturunkan dari pemanggilan env di kode aplikasi, bukan dari menyalin `.env.example`.** Berkas contoh env hampir selalu basi — var baru ditambahkan di kode tanpa didokumentasikan, dan var lama tetap tertinggal setelah fiturnya dihapus. Compose yang menyalin contoh env akan (a) kehilangan var yang benar-benar dibaca kode, dan (b) meneruskan var mati yang menyesatkan operator.

### 1.1 Jalankan scanner

```bash
# Ringkasan 4 kategori (lihat 1.2): A dipakai-tapi-belum-didokumentasi,
# B didokumentasi-tapi-tak-dipakai, C interpolasi saja, D belum masuk compose
python3 .github/skills/rames-deployable-docker/scripts/scan-env-usage.py .

# Gagal (exit 1) bila ada var kategori A
python3 .github/skills/rames-deployable-docker/scripts/scan-env-usage.py . --strict

# Untuk diolah lebih lanjut
python3 .github/skills/rames-deployable-docker/scripts/scan-env-usage.py . --json
```

Scanner mendeteksi akses env di PHP (`getenv`, `$_ENV`, `$_SERVER`, `env()`, `Env::get`), JS/TS (`process.env`, `import.meta.env`, `Deno.env`, `Bun.env`), Python (`os.environ`, `os.getenv`), Go, Ruby, Java/Kotlin, .NET, Rust, Elixir, shell, serta interpolasi `${...}` di compose/Dockerfile. Ia juga membaca blok `environment:` pada compose di root project untuk kategori D. Yang dilewati otomatis: `vendor/`, `node_modules/`, `dist/`, `build/`, `runtime/`, `cache/`, `tests/`, direktori tooling (`.git`, `.github`, `.idea`), komentar YAML/shell, dan var sistem/base image (`PATH`, `HOME`, `TZ`, `PHP_INI_DIR`, `PHPIZE_DEPS`, …).

Jika scanner tidak bisa dipakai, lakukan manual:

```bash
grep -rhoE "(getenv|env)\(\s*['\"][A-Z0-9_]+" --include="*.php" . | grep -v '/vendor/'
grep -rhoE "(process\.env\.|import\.meta\.env\.)[A-Za-z0-9_]+" --include="*.{js,ts,mjs,cjs}" .
grep -rhoE "os\.(environ\[|getenv\()['\"][A-Z0-9_]+" --include="*.py" .
```

### 1.2 Verifikasi setiap temuan (jangan percaya hasil scan mentah)

| Kategori | Temuan scanner | Tindakan |
|---|---|---|
| A | Dibaca kode, belum ada di contoh env | **Wajib** masuk `.env.example` **dan** `environment:` compose |
| B | Ada di contoh env, tidak ditemukan di kode | Cari pemakaian tak langsung (config framework, pembacaan dinamis `getenv($name)`, CLI/deploy). Hapus **hanya** jika yakin mati |
| C | Hanya interpolasi `${...}` di compose/Dockerfile | Sediakan nilainya, tapi **jangan** dimasukkan ke `environment:` bila memang hanya dipakai saat deploy |
| D | Dibaca kode, tidak ada di `environment:` compose | Tuangkan ke compose sebagai `${VAR}`. Bukan kegagalan bila compose memakai `env_file:` (scanner otomatis bungkam) atau bila var diisi lewat UI Rames — tapi tetap dianjurkan agar lokal dan produksi konsisten |
| — | Diwarisi base image / tooling (`PATH`, `TZ`, `PHP_INI_DIR`) | Jangan ditulis — bukan konfigurasi aplikasi |
| — | Hanya dibaca saat build (argumen build) | `ARG` di Dockerfile, bukan `environment:` runtime. Jangan pernah taruh secret di `ARG`/`ENV` |
| — | Nama generik dari komentar/dokumentasi (mis. `VAR`, `X`) | Abaikan |

`--strict` hanya menggagalkan kategori **A**; kategori B/C/D bersifat laporan agar tidak menghasilkan false positive.

### 1.3 Petakan ke compose

- Setiap var kategori "dipakai kode" muncul di `environment:` sebagai `${VAR}`; pakai `${VAR:-default}` hanya bila default-nya aman untuk produksi, dan `${VAR}` polos untuk secret.
- **Path di dalam container, bukan path host.** Contoh: kode menggabungkan `UPLOAD_DIR_LOCATION` dengan path relatif `/uploads/...`, jadi nilainya `/app/public` — bukan `/home/user/project/public` yang biasa ditulis developer di `.env.example`.
- **Service internal yang selalu ada di compose** (DB, Redis, queue): host/port-nya di-hardcode ke nama service (`DB_HOST: db`, `REDIS_HOST: redis`), bukan dibiarkan sebagai `${VAR}` yang bisa salah isi. Kecualikan bila project memang memakai DB eksternal — beri default ke `host.docker.internal` dan dokumentasikan.
- Var yang sudah di-hardcode di compose harus dihapus dari `.env.example` atau diberi catatan "diabaikan saat dijalankan lewat compose" agar tidak menimbulkan kebingungan.
- Var yang hanya dipakai skrip dev/deploy (bukan container) tidak masuk `environment:`.
- Var yang di-inline **saat build** (`VITE_*`, `NEXT_PUBLIC_*`, `REACT_APP_*`) tidak bisa disuntik lewat `environment:` runtime pada image statis — sediakan lewat `ARG`/build arg, dan jangan pernah menaruh secret di sana.
- Password pada service pihak ketiga (mis. Redis) harus dibaca **di dalam container** (`$${VAR}` di `command` + `environment:`), karena Rames menyuntikkan env ke container, bukan ke interpolasi `${...}` compose.

### 1.4 Definition of done

- [ ] Scanner dijalankan (atau grep manual), hasilnya diverifikasi butir per butir.
- [ ] Kategori A kosong (`--strict` lulus) — semua var yang dibaca kode ada di `.env.example` **dan** compose.
- [ ] Kategori D ditinjau: var yang belum masuk `environment:` compose sudah ditambahkan atau alasannya dicatat.
- [ ] Var mati dihapus atau dijelaskan alasannya di komentar.
- [ ] Semua path bernilai container path, bukan path host.
- [ ] `.env.example` sinkron dengan compose (nama sama, tanpa nilai rahasia).

## Langkah 2 — Cari image Docker Hub yang mencukupi

Urutan preferensi:

1. **Official image** (`library/*`, mis. `postgres`, `mysql`, `redis`, `nginx`, `node`, `php`, `python`).
2. **Verified publisher / vendor resmi** (mis. `gitea/gitea`, `louislam/uptime-kuma`, `minio/minio`).
3. **Image komunitas** hanya jika tidak ada pilihan resmi — periksa maintainer, tag, dan dokumentasi env/volume.

Untuk setiap kandidat, pastikan:

- tag **spesifik** tersedia (hindari `latest` untuk produksi; pin minimal versi minor),
- image **multi-arch** (`amd64` + `arm64`) atau sesuai arsitektur server,
- semua konfigurasi bisa lewat **environment variable** atau file config yang di-mount,
- data persisten berada di **satu direktori** yang bisa dijadikan named volume,
- port HTTP terdokumentasi,
- image menyediakan healthcheck, atau healthcheck bisa ditulis di compose.

Katalog awal: [`references/image-catalog.md`](references/image-catalog.md). Verifikasi tag terbaru di Docker Hub sebelum memakai.

## Langkah 3 — Pilih strategi

| Situasi | Strategi | Dockerfile? |
|---|---|---|
| Project adalah aplikasi siap pakai (CMS, automation, database, dashboard) | Pakai image resmi + env + named volume | **Tidak** |
| Project berisi kode aplikasi yang tidak perlu dikompilasi, dan runtime resmi tersedia | Image runtime resmi + bind source repo + `command` | **Tidak** (trade-off startup lebih lambat) |
| Project perlu build (asset frontend, kompilasi, ekstensi PHP, dependency native), atau image resmi tidak menyediakan runtime yang cocok | Multi-stage Dockerfile | **Ya** |
| Project adalah template Rames (`templates/<slug>/`) | Image prebuilt saja | **Tidak** (mode template menolak `build:`) |

**Strategi A — image siap pakai.** Contoh: WordPress, Ghost, n8n, Gitea, Uptime Kuma, Postgres. Compose hanya berisi `image:`, env, volume, healthcheck. Ini pilihan pertama.

**Strategi B — runtime resmi + source di-bind.** Contoh: aplikasi Node/PHP/Python kecil. Compose memakai `image: node:22-alpine`, `working_dir`, bind `./:/app`, dan `command` yang meng-install dependensi lalu menjalankan app. Tidak ada Dockerfile, tetapi setiap start bisa lebih lambat dan `node_modules`/`vendor` sebaiknya named volume. Gunakan hanya jika build image tidak diperlukan.

**Strategi C — Dockerfile.** Gunakan bila butuh build asset, kompilasi, ekstensi native, atau ukuran/startup produksi. Compose memakai `build: {context: ., dockerfile: Dockerfile}`. **`build:` hanya boleh untuk app Git/Compose milik user — bukan template** (lihat kontrak).

Resep Dockerfile: [`references/dockerfile-recipes.md`](references/dockerfile-recipes.md) dan aset di [`assets/`](assets/).

## Langkah 4 — Tulis compose sesuai kontrak Rames

Aturan ringkas (detail + alasan: [`references/rames-compose-contract.md`](references/rames-compose-contract.md)):

**WAJIB**
- `services:` tidak kosong; setiap service punya `image:` **atau** `build:` (build hanya mode Git).
- Tepat **satu service web publik** yang mendeklarasikan port container; service database/worker tidak perlu `ports:`.
- Port ditulis sebagai **port container saja**, mis. `- "3000"`; Rames mengalokasikan host port dari `PORT_RANGE_*` dan menulis override port.
- Gunakan **named volume** untuk semua state (`volumes: { data: {} }` + `data:/var/lib/...`).
- Tambahkan `restart: unless-stopped`, `healthcheck`, dan `depends_on: {db: {condition: service_healthy}}` bila ada DB.
- Batasi log: `logging: {driver: json-file, options: {max-size: "10m", max-file: "3"}}`.
- Gunakan `${VAR}` untuk konfigurasi; sertakan `.env.example` tanpa nilai rahasia.
- Pin tag image; pastikan image bisa di-pull dari server agent.

**DILARANG**
- `container_name:` — Rames memberi prefix nama container per app.
- `name:` di level atas — nama project compose = nama app (dipakai untuk reuse volume).
- `deploy.replicas` > 1 atau `scale` > 1 — tidak kompatibel dengan nama container otomatis.
- Host port **80/443** — sudah dipakai Nginx host Rames.
- `network_mode: host`, `pid: host`, `privileged: true`, `cap_add` tanpa alasan kuat — melewati isolasi/proxy Rames dan menambah risiko.
- Mount socket Docker (`/var/run/docker.sock`) untuk app biasa — berbahaya; hanya jika fitur memang memerlukan dan sudah disetujui.
- Bind ke path absolut host (`/srv/...`, `/home/...`) — tidak portabel antar server; Rames hanya menyiapkan path di dalam direktori app.
- Secret literal di compose, `.env.example`, atau repo.
- Snapshot `latest` untuk produksi.

**Catatan Rames**
- Rames menulis override: port, nama container, network eksternal, env, limits. Jangan mendeklarasikan kunci yang dikelola itu.
- Environment yang diset di UI Rames di-inject ke **setiap** service sebagai `environment:` literal (override terakhir). Jangan mengandalkan isolasi env per service untuk rahasia.
- Bind mount relatif `./data` boleh; direktori dibuat otomatis, tetapi **berkas** (mis. `nginx.conf`) tidak — berkas harus ada di repo.
- App tanpa `ports:` tetap bisa dibuat (mis. database murni), tetapi tidak mendapat vhost/subdomain.

Aset siap salin:
- [`assets/compose-official-image.yml`](assets/compose-official-image.yml)
- [`assets/compose-with-db.yml`](assets/compose-with-db.yml)
- [`assets/compose-runtime-bind.yml`](assets/compose-runtime-bind.yml)
- [`assets/compose-build.yml`](assets/compose-build.yml)
- [`assets/env.example`](assets/env.example)

## Langkah 5 — Environment & rahasia

- Declaration di compose: `${DB_PASSWORD}`, `${APP_KEY}`, `${APP_URL}`.
- **Sumber daftar var = hasil [Langkah 1](#langkah-1--audit-environment-variable-dari-codebase), bukan `.env.example`.** Setiap var yang dibaca kode wajib punya pasangan `${VAR}` di compose; sebaliknya var mati tidak boleh ikut.
- `.env.example` hanya berisi **nama** variabel + komentar/contoh non-rahasia; isinya harus sinkron dengan compose (tidak ada var yatim di kedua arah).
- Nilai asli dimasukkan lewat tab **Environment** Rames (tersimpan di `database/env/<app>.env`, 0600) — jangan menulis `.env` nyata ke repo.
- Jangan memakai `env_file:` untuk rahasia; Rames sudah menyuntikkan env. Jika `env_file` tetap dipakai untuk nilai non-rahasia, pastikan berkasnya ada di repo.
- Jangan pernah menaruh token, password, private key, atau kredensial cloud di `ARG`, `ENV`, atau layer image.

## Langkah 6 — Bila perlu Dockerfile

Ikuti aturan ini:

- Base image resmi + tag spesifik.
- **Multi-stage** untuk bahasa terkompilasi / build asset; stage runtime hanya berisi artefak + dependency produksi.
- `WORKDIR`, `COPY` selektif, dan `.dockerignore` (lihat [`assets/dockerignore`](assets/dockerignore)).
- Jalankan sebagai **non-root** bila memungkinkan; pastikan direktori volume dapat ditulis.
- `EXPOSE <port container>`; jangan `EXPOSE` 80/443 host.
- `HEALTHCHECK` opsional — compose healthcheck lebih mudah diubah.
- Jangan install tool debugging di image produksi.
- Entrypoint harus menangani `SIGTERM` (exec form `CMD ["..."]`, bukan shell form) agar stop/restart Rames rapi.
- Migrasi database: jalankan idempotent saat start **satu** service saja; jangan di setiap replica (Rames tidak memakai replica).

## Langkah 7 — Validasi

1. Jalankan validator:

   ```bash
   python3 .github/skills/rames-deployable-docker/scripts/validate-compose.py docker-compose.yml --mode git
   ```

   Mode: `git` (build boleh), `compose`/`template` (build ditolak).

2. Jika Docker tersedia, validasi sintaks Compose tanpa mencetak secret:

   ```bash
   docker compose -f docker-compose.yml config --quiet
   ```

3. Opsional: `docker compose up -d` lalu cek healthcheck dan port, kemudian `docker compose down -v` (jangan pernah menjalankan ini pada project Rames nyata).

4. Periksa daftar manual:
   - tidak ada `container_name`, `name:` atas, replica/scale;
   - port hanya container port, bukan 80/443;
   - semua state memakai named volume;
   - tidak ada secret literal;
   - service web + DB punya healthcheck/depends_on;
   - image dapat di-pull di arsitektur server target.

5. Ulangi audit env agar compose tetap sinkron dengan kode:

   ```bash
   python3 .github/skills/rames-deployable-docker/scripts/scan-env-usage.py . --strict
   ```

   Kategori A (dipakai kode tapi belum terdokumentasi) **harus kosong** sebelum dianggap selesai, dan kategori D (belum masuk `environment:` compose) harus sudah ditinjau.

## Output yang harus dilaporkan

Saat selesai, laporkan:

- **Strategi** yang dipilih (A/B/C) dan alasan image tersebut mencukupi (atau alasan perlu Dockerfile).
- **Primary service + port container** yang harus dipilih di wizard Rames.
- **Hasil audit env**: jumlah var yang dibaca kode, var yang ditambahkan, dan var mati yang dibuang (sertakan alasan).
- **Env wajib** yang harus diisi di tab Environment.
- **Volume/state** yang harus ikut backup.
- **File yang dibuat** dan hasil validator + `scan-env-usage.py --strict`.
- **Catatan kompatibilitas**: tag image, arsitektur, batasan (mis. butuh worker terpisah, asset build).

## Referensi

- Kontrak compose Rames lengkap: [`references/rames-compose-contract.md`](references/rames-compose-contract.md)
- Katalog image Docker Hub: [`references/image-catalog.md`](references/image-catalog.md)
- Resep Dockerfile: [`references/dockerfile-recipes.md`](references/dockerfile-recipes.md)
- Validator: [`scripts/validate-compose.py`](scripts/validate-compose.py)
- Scanner env: [`scripts/scan-env-usage.py`](scripts/scan-env-usage.py)

Dokumentasi produk Rames: `docs/SPECS.md` §7.2/§7.2b/§7.6; detail internal: `docs/ARCHITECTURE/05-01-siklus-hidup-app.md`.
