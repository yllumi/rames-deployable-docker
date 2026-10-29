# Kontrak Compose untuk Rames

Dokumen ini menjelaskan apa yang Rames kelola sendiri, apa yang harus ditulis di compose, dan jebakan yang membuat deploy gagal.

## 1. Mode deploy dan aturan `build:`

| Mode Rames | Sumber | `image:` | `build:` |
|---|---|---|---|
| **Clone repo Git** | repo berisi `docker-compose.yml` | boleh | **boleh** — `docker compose up -d --build` |
| **Compose paste/upload** | user menempel/mengunggah YAML | **wajib** | **ditolak** (`ComposeSource::assertDeployable()`) |
| **Template** (`templates/<slug>/`) | katalog repo Rames | **wajib** | **ditolak** (`TemplateCatalog`) |

Konsekuensi: jika target deploy memakai mode Compose/template, **jangan** menghasilkan Dockerfile — pilih image prebuilt. Jika project memerlukan build dan user memakai mode Compose, arahkan ke mode **Clone repo Git**.

## 2. Kunci yang dikelola Rames — jangan ditulis

Rames menulis override generated di direktori app:

- **Nama project** = nama app. Jangan menulis `name:` di level atas.
- **Nama container** = `<prefix app>-<service>`. Jangan menulis `container_name:`.
- **Host port** = dialokasikan dari `PORT_RANGE_START..PORT_RANGE_END`. Jangan menulis `80:80`/`443:443`.
- **Network eksternal**, **env**, dan **limits** ditulis ke override terpisah.

Urutan file compose yang dipakai Rames:

```
base → docker-compose.override.yml → .override.ports.yml → .override.names.yml
     → .override.limits.yml → (network) → .override.env.yml (paling akhir)
```

Override env sengaja paling akhir agar nilai dari UI Rames menang atas env di repo.

## 3. Port

- Tulis **port container saja**:

  ```yaml
  ports:
    - "3000"
  ```

  Rames memilih host port bebas dan menulis `docker-compose.override.ports.yml` berisi `HOST:CONTAINER`.

- Jika port host harus tetap, tulis `"31000:3000"` dan pastikan berada di rentang port server. Rames tetap akan mengganti host port jika bentrok dengan app lain di server yang sama.
- Jangan menulis `"80:80"` atau `"443:443"`: Nginx native host Rames memakai port itu.
- Jangan memakai IP binding (`127.0.0.1:3000:3000`); override port Rames menulis mapping tanpa IP.
- Service database/worker tidak perlu `ports:` — cukup jaringan internal compose.
- App tanpa `ports:` tetap bisa dibuat (mis. database murni), tetapi tidak mendapat vhost/subdomain.
- Satu app hanya mem-proxy **satu** port utama (`primary_service`/`primary_port` dipilih saat create). Port lain tetap dipublikasikan tetapi diakses langsung.

## 4. Environment

- **Daftar variabel diturunkan dari pemakaian di kode**, bukan dari menyalin `.env.example` (berkas contoh sering basi). Jalankan `python3 scripts/scan-env-usage.py . --strict` dan tindak lanjuti hasilnya sebelum menulis `environment:`; detail aturan di `SKILL.md` Langkah 1.
- Tulis referensi `${VAR}` di compose; nilai asli diisi lewat tab **Environment** Rames.
- Path yang dibaca aplikasi harus **path di dalam container** (mis. `/app/public`), bukan path host yang biasa tertulis di `.env.example` developer.
- Host/port service internal yang selalu ada di compose (DB, Redis) di-hardcode ke nama service; var yang sudah di-hardcode jangan dibiarkan sebagai `${VAR}` yang bisa salah diisi.
- Rames menyimpan env di `database/env/<app>.env` (0600) dan menyuntikkan `environment:` literal ke **setiap** service melalui override terakhir.
- Jangan mengandalkan isolasi env per service untuk rahasia — semua service menerima env yang sama.
- `.env.example` hanya dokumentasi nama variabel; **jangan** menaruh nilai rahasia, dan isinya harus sinkron dengan compose.
- Hindari `env_file:` untuk rahasia; Rames sudah menangani env. Jika tetap dipakai, berkas harus ada di repo dan tidak berisi secret.
- Jangan menaruh secret di `ARG`/`ENV` Dockerfile — nilai itu tersimpan di layer image.

## 5. Volume & bind mount

- Gunakan **named volume** untuk state:

  ```yaml
  services:
    app:
      volumes:
        - app-data:/var/lib/app
  volumes:
    app-data:
  ```

  Named volume otomatis di-scope per app (nama project = nama app), jadi aman dipakai banyak app.

- Bind relatif (`./data:/data`) diperbolehkan; Rames membuat **direktori** yang belum ada di dalam direktori app. **Berkas** (mis. `nginx.conf`, `.env`) tidak dibuat otomatis — harus ada di repo.
- Bind path absolut host (`/srv/data`, `/home/user/...`) tidak portabel antar server dan tidak disiapkan Rames. Hindari.
- Jangan memakai `driver_opts` yang menunjuk path absolut host.
- Untuk bind yang wajib gagal bila path salah, gunakan long syntax `bind: {create_host_path: false}`; Rames menghormati opsi itu.
- Pastikan direktori volume dapat ditulis oleh user container (terutama bila Dockerfile memakai non-root).
- Data yang perlu ikut backup Rames adalah named volume milik app.

## 6. Network

- Biarkan compose membuat network default; service saling terhubung lewat nama service (`db`, `redis`).
- Jangan memakai `network_mode: host` — melewati isolasi dan proxy Rames.
- Network eksternal lintas-app dikelola Rames lewat override; jangan menulis `external: true` kecuali memang fitur app membutuhkannya dan network sudah ada di server.
- Jangan set `hostname`/`container_name` untuk mengatur DNS internal; gunakan nama service.

## 7. Restart, healthcheck, logging

```yaml
services:
  web:
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

- `restart: unless-stopped` agar container hidup lagi setelah host/server restart.
- `init: true` untuk aplikasi yang bukan PID 1 yang baik — **kecuali** image yang memang memakai init/s6 sebagai entrypoint (mis. `yllumi/fpm8.4-nginx`); menambahkan `init` pada image seperti itu bisa membuat container gagal start.
- `depends_on` + `condition: service_healthy` untuk DB yang punya healthcheck.
- Batasi log agar disk host tidak penuh.

## 8. Multi-server

- Image harus bisa di-pull dari server agent (Docker Hub publik atau registry yang dapat diakses server itu).
- Hindari path host spesifik dan bind absolut — server agent punya filesystem sendiri.
- Pastikan image mendukung arsitektur server (`amd64`/`arm64`).
- Rahasia dan kredensial tetap diisi lewat Environment Rames; jangan mengirimnya di payload/compose.
- Jangan mengandalkan service yang hanya ada di host control plane (mis. socket Docker host).

## 9. Mode template Rames

Jika hasil akan dijadikan template di `templates/<slug>/`:

- `docker-compose.yml` wajib memakai `image:` untuk **setiap** service; `build:` ditolak.
- Jangan menulis `container_name`, `name:` atas, replica/scale > 1.
- Tambahkan `template.yml`:

  ```yaml
  title: Nama Aplikasi
  description: Ringkasan singkat.
  category: Web
  icon: "🚀"
  docs_url: https://…
  env:
    - key: APP_URL
      label: URL aplikasi
      help: Harus sama dengan domain/subdomain di Rames.
  primary:
    service: web
    port: 3000
  ```

- Tambahkan `guide.md` (katalog-only, tidak di-materialize ke app).
- Jika butuh berkas konfigurasi awal, letakkan di `files/`.

## 10. Keamanan

- Jangan mount `/var/run/docker.sock` ke app biasa.
- Jangan memakai `privileged: true`, `pid: host`, `ipc: host`, atau `cap_add` tanpa kebutuhan yang jelas dan disetujui.
- Jangan menaruh secret di compose, `.env.example`, Dockerfile, atau image.
- Jalankan container sebagai non-root bila memungkinkan.
- Gunakan image tepercaya; hindari tag `latest` untuk produksi.

## 11. Checklist validasi

- [ ] `services` tidak kosong; setiap service punya `image:` (atau `build:` hanya mode Git).
- [ ] Tidak ada `container_name`, `name:` atas, `deploy.replicas`/`scale` > 1.
- [ ] Port hanya port container; tidak ada host 80/443; tidak ada IP binding.
- [ ] Tepat satu service web publik; DB/worker tanpa `ports:`.
- [ ] State memakai named volume; tidak ada bind absolut host.
- [ ] Env memakai `${VAR}`; `.env.example` tanpa rahasia.
- [ ] Semua var yang dibaca kode sudah ada di compose (`scripts/scan-env-usage.py . --strict` lulus).
- [ ] Tidak ada var env mati yang diteruskan tanpa alasan.
- [ ] `restart`, `healthcheck`, `logging` ada.
- [ ] Image di-pin dan multi-arch.
- [ ] `python3 scripts/validate-compose.py docker-compose.yml --mode <git|compose|template>` lulus.
- [ ] `docker compose config --quiet` lulus (jika Docker tersedia).
