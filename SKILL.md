---
name: rames-deployable-docker
description: Membuat docker-compose.yml (dan Dockerfile hanya bila benar-benar perlu) untuk project apa pun agar kompatibel dideploy di dashboard Rames. Prioritaskan image resmi Docker Hub tanpa membuat Dockerfile. Gunakan ketika user meminta "buatkan compose untuk Rames", "dockerize project ini", "pilih image Docker Hub", atau "Dockerfile + docker-compose untuk Rames".
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
5. **Env wajib** — nama variabel + contoh nilai (jangan nilai rahasia nyata).
6. **Proses latar** — worker/cron. Compose dapat memuat beberapa service; jangan menaruh worker di dalam container web jika image resmi tidak mendukung.
7. **Arsitektur target** — server Rames bisa `x86_64` atau `aarch64`; pastikan image multi-arch.

Jika project sudah punya `Dockerfile`/compose, **audit dulu** terhadap kontrak di bawah; jangan langsung menulis ulang.

## Langkah 1 — Cari image Docker Hub yang mencukupi

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

## Langkah 2 — Pilih strategi

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

## Langkah 3 — Tulis compose sesuai kontrak Rames

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

## Langkah 4 — Environment & rahasia

- Declaration di compose: `${DB_PASSWORD}`, `${APP_KEY}`, `${APP_URL}`.
- `.env.example` hanya berisi **nama** variabel + komentar/contoh non-rahasia.
- Nilai asli dimasukkan lewat tab **Environment** Rames (tersimpan di `database/env/<app>.env`, 0600) — jangan menulis `.env` nyata ke repo.
- Jangan memakai `env_file:` untuk rahasia; Rames sudah menyuntikkan env. Jika `env_file` tetap dipakai untuk nilai non-rahasia, pastikan berkasnya ada di repo.
- Jangan pernah menaruh token, password, private key, atau kredensial cloud di `ARG`, `ENV`, atau layer image.

## Langkah 5 — Bila perlu Dockerfile

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

## Langkah 6 — Validasi

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

## Output yang harus dilaporkan

Saat selesai, laporkan:

- **Strategi** yang dipilih (A/B/C) dan alasan image tersebut mencukupi (atau alasan perlu Dockerfile).
- **Primary service + port container** yang harus dipilih di wizard Rames.
- **Env wajib** yang harus diisi di tab Environment.
- **Volume/state** yang harus ikut backup.
- **File yang dibuat** dan hasil validator.
- **Catatan kompatibilitas**: tag image, arsitektur, batasan (mis. butuh worker terpisah, asset build).

## Referensi

- Kontrak compose Rames lengkap: [`references/rames-compose-contract.md`](references/rames-compose-contract.md)
- Katalog image Docker Hub: [`references/image-catalog.md`](references/image-catalog.md)
- Resep Dockerfile: [`references/dockerfile-recipes.md`](references/dockerfile-recipes.md)
- Validator: [`scripts/validate-compose.py`](scripts/validate-compose.py)

Dokumentasi produk Rames: `docs/SPECS.md` §7.2/§7.2b/§7.6; detail internal: `docs/ARCHITECTURE/05-01-siklus-hidup-app.md`.
