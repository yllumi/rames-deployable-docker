# Resep Dockerfile untuk Rames

Dockerfile hanya dipakai bila image Docker Hub tidak mencukupi. Sebelum menulis, pastikan alasan strategi C jelas (build asset, kompilasi, ekstensi native, atau runtime tidak tersedia).

## Checklist umum

- [ ] Base image resmi + tag spesifik (mis. `node:22-alpine`, `php:8.3-apache`).
- [ ] Multi-stage bila ada langkah build; stage runtime hanya berisi artefak + dependency produksi.
- [ ] `WORKDIR` eksplisit.
- [ ] `COPY` selektif (manifest dulu, lalu source) agar cache efektif.
- [ ] `.dockerignore` mencegah `.git`, `node_modules`, `vendor`, `dist`, `.env`, log, dan data runtime ikut ke build context (contoh: [`assets/dockerignore`](../assets/dockerignore) — salin menjadi `.dockerignore`).
- [ ] Jalankan sebagai non-root bila memungkinkan; pastikan volume dapat ditulis.
- [ ] `EXPOSE` port container (bukan 80/443 host).
- [ ] `CMD`/`ENTRYPOINT` bentuk exec (`["..."]`) agar sinyal berhenti diteruskan.
- [ ] Tidak ada secret di `ARG`/`ENV`/layer.
- [ ] `composer install --no-dev`, `npm ci --omit=dev`, atau ekuivalen untuk dependency produksi.
- [ ] Entrypoint migrasi idempotent dan hanya dijalankan satu service.

## Node.js / TypeScript

Aset: [`assets/Dockerfile.node`](../assets/Dockerfile.node)

Pola:

1. Stage `build`: `npm ci`, copy source, `npm run build`.
2. Stage runtime: `npm ci --omit=dev`, copy `dist`, `public`, dan berkas runtime lain.
3. `USER node` (image Node sudah menyediakan user `node`).
4. `CMD ["node", "dist/server.js"]`.

Catatan:

- Jangan copy `node_modules` dari host.
- Framework yang butuh `next start`/`nuxt start`: copy `.next`/`.output` dan jalankan perintah yang sesuai.
- Aplikasi yang menulis upload ke disk: arahkan ke path named volume (mis. `/app/uploads`).

## PHP

Aset: [`assets/Dockerfile.php`](../assets/Dockerfile.php)

Pola Apache:

1. `FROM php:8.3-apache`.
2. `docker-php-ext-install pdo pdo_mysql` (tambahkan ekstensi lain sesuai kebutuhan).
3. `a2enmod rewrite`.
4. Install Composer dari `composer:2`.
5. `composer install --no-dev --optimize-autoloader`.
6. Set `DocumentRoot` ke `public/` bila framework memakai public root.
7. `EXPOSE 80`.

Pola FPM: gunakan `php:8.3-fpm-alpine` + image Nginx terpisah, atau image gabungan tepercaya seperti `serversideup/php:8.4-fpm-nginx`. Jika memakai image gabungan, jangan menambahkan `init: true` bila image memakai s6/init sendiri.

Catatan:

- Ekstensi native (`gd`, `intl`, `zip`, `bcmath`) harus di-install eksplisit.
- Jangan menyimpan `.env` di image; env datang dari Rames.
- Writable path (`storage/`, `bootstrap/cache`) harus dimiliki user web atau volume yang sesuai.

## Python

Aset: [`assets/Dockerfile.python`](../assets/Dockerfile.python)

Pola:

1. `FROM python:3.12-slim`.
2. `ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1`.
3. Copy `requirements.txt`/`pyproject.toml`, install dependency produksi.
4. Copy source.
5. Buat user non-root dan `chown` direktori app.
6. `CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:app"]` (sesuaikan modul).

Catatan:

- Untuk Django: jalankan `collectstatic` saat build (tanpa secret), migrasi saat start satu service, dan arahkan `STATIC_ROOT`/`MEDIA_ROOT` ke volume bila perlu.
- Untuk FastAPI: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- Dependency yang butuh compiler: install `build-essential` di stage build, lalu copy wheel/venv ke stage runtime.

## Static site (SPA/SSG)

Aset: [`assets/Dockerfile.static`](../assets/Dockerfile.static)

Pola:

1. Stage build Node: `npm ci` + `npm run build`.
2. Stage runtime `nginx:1.27-alpine`.
3. Copy hasil build (`dist/`, `build/`, `out/`) ke `/usr/share/nginx/html`.
4. `EXPOSE 80`.

Catatan:

- Jangan bind `node_modules` ke Nginx.
- Untuk SPA dengan client-side routing, tambahkan konfigurasi `try_files $uri /index.html;` — letakkan config di repo dan mount read-only, atau buat image turunan Nginx.
- Rames tetap yang menangani domain/SSL; Nginx internal hanya menyajikan berkas.

## Go

Aset: [`assets/Dockerfile.go`](../assets/Dockerfile.go)

Pola:

1. Stage build `golang:1.23-alpine`.
2. `go mod download` lalu `go build -o /out/app ./cmd/app` dengan `CGO_ENABLED=0`.
3. Stage runtime `gcr.io/distroless/static-debian12:nonroot` (atau `alpine` bila butuh shell/cert).
4. Copy binary, `USER nonroot`, `EXPOSE 8080`.

Catatan:

- Jika butuh CA certificate untuk HTTPS keluar, gunakan image yang menyertakan `ca-certificates` atau copy dari stage build.
- Jangan menjalankan `go build` di stage runtime.

## Java

Aset: [`assets/Dockerfile.java`](../assets/Dockerfile.java)

Pola:

1. Stage build `maven:3.9-eclipse-temurin-21` (atau Gradle).
2. Cache dependency (`dependency:go-offline`), copy source, `package -DskipTests`.
3. Stage runtime `eclipse-temurin:21-jre-alpine`.
4. Copy JAR, buat user non-root, `EXPOSE 8080`, `ENTRYPOINT ["java","-jar","/app/app.jar"]`.

Catatan:

- Untuk Spring Boot, hormati `SERVER_PORT`/`PORT` dari env.
- Jangan menyertakan Maven/Gradle di image runtime.

## Build args dan rahasia

- `ARG` hanya untuk nilai non-rahasia (versi, target platform).
- Jangan `ARG SECRET` / `ENV SECRET`; nilai akan tersimpan di history image.
- Untuk dependency privat, gunakan build secret BuildKit (`--mount=type=secret`) dan pastikan Rames/agent mendukung; jika tidak, gunakan registry token di level host, bukan di Dockerfile.
- Jangan copy `.env`, `id_rsa`, `*.pem`, atau kredensial ke image.

## Migrasi & startup

- Jalankan migrasi dari entrypoint hanya untuk satu service (mis. service `app`), dan buat idempotent.
- Jangan menjalankan migrasi di service worker yang bisa start bersamaan.
- Beri retry singkat saat menunggu DB; `depends_on: service_healthy` sudah membantu, tetapi aplikasi tetap perlu menangani DB yang belum siap.
- Untuk app yang butuh seed data, lakukan sekali di entrypoint dengan penanda (tabel/berkas) agar tidak mengulang.

## Integrasi dengan compose

Contoh minimal:

```yaml
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "3000"
    environment:
      APP_ENV: production
      APP_URL: ${APP_URL}
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

Aset lengkap: [`assets/compose-build.yml`](../assets/compose-build.yml).

## Uji sebelum menyerahkan

```bash
docker build -t project-uji .
docker run --rm -p 3000:3000 --env-file .env.example project-uji
```

- Pastikan container start tanpa error.
- Cek endpoint kesehatan.
- Pastikan data ditulis ke path yang akan dijadikan volume.
- Hentikan dan hapus container uji; jangan menyentuh project Rames nyata.
