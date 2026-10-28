# Katalog Image Docker Hub untuk Rames

Katalog awal — **selalu verifikasi tag terbaru dan arsitektur** di Docker Hub sebelum memakai. Tag di bawah adalah contoh; pin versi yang benar-benar teruji.

## Cara memverifikasi

1. Buka halaman image di Docker Hub → tab **Tags**; pilih tag spesifik (hindari `latest` untuk produksi).
2. Cek **Supported architectures** (`linux/amd64`, `linux/arm64`).
3. Baca dokumentasi env, volume, dan port di halaman image.
4. Uji tarik di server target:
   ```bash
   docker pull <image>:<tag>
   docker manifest inspect <image>:<tag> | head
   ```
5. Jika image hanya tersedia untuk satu arsitektur, jangan dipakai pada server Rames dengan arsitektur berbeda.

## Aplikasi siap pakai (tanpa Dockerfile)

| Kebutuhan | Image contoh | Port container | Data persisten | Env penting | Catatan |
|---|---|---|---|---|---|
| WordPress | `wordpress:php8.3-apache` | `80` | `/var/www/html` | `WORDPRESS_DB_HOST`, `WORDPRESS_DB_NAME`, `WORDPRESS_DB_USER`, `WORDPRESS_DB_PASSWORD` | Pasangkan dengan `mysql:8.4`/`mariadb:11`; jangan publish port DB. |
| Ghost | `ghost:6-alpine` | `2368` | `/var/lib/ghost/content` | `url`, `database__client`, `database__connection__*` | Butuh MySQL 8; `url` harus sama dengan domain/subdomain Rames. |
| Drupal | `drupal:11-apache` | `80` | `/var/www/html/sites` | `DRUPAL_DB_*` | Butuh DB eksternal. |
| Joomla | `joomla:5-php8.3-apache` | `80` | `/var/www/html` | `JOOMLA_DB_*` | Butuh DB eksternal. |
| Gitea | `gitea/gitea:1` | `3000` | `/data` | `GITEA__database__*`, `GITEA__server__ROOT_URL` | Bisa memakai SQLite di `/data` atau DB eksternal. |
| n8n | `n8nio/n8n` | `5678` | `/home/node/.n8n` | `N8N_ENCRYPTION_KEY`, `N8N_HOST`, `WEBHOOK_URL` | Butuh volume agar workflow/credential persisten. |
| Uptime Kuma | `louislam/uptime-kuma:2` | `3001` | `/app/data` | — | Ringan; cukup satu volume. |
| Grafana | `grafana/grafana:11` | `3000` | `/var/lib/grafana` | `GF_SECURITY_ADMIN_PASSWORD` | Bisa memakai SQLite internal. |
| Prometheus | `prom/prometheus:v3` | `9090` | `/prometheus` | — | Perlu file config yang di-mount (harus ada di repo). |
| MinIO | `minio/minio` | `9000` (API), `9001` (console) | `/data` | `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Pin tag release, bukan `latest`. |
| Mailpit (SMTP uji) | `axllent/mailpit` | `8025` (UI), `1025` (SMTP) | `/data` | — | Hanya untuk pengujian, bukan produksi. |

## Database & cache

| Kebutuhan | Image contoh | Port internal | Data persisten | Env penting | Catatan |
|---|---|---|---|---|---|
| PostgreSQL | `postgres:17-alpine` | `5432` | `/var/lib/postgresql/data` | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Jangan publish port ke host. |
| MySQL | `mysql:8.4` | `3306` | `/var/lib/mysql` | `MYSQL_ROOT_PASSWORD`, `MYSQL_DATABASE` | Rames mendeteksi MySQL/MariaDB untuk Adminer & dump backup. |
| MariaDB | `mariadb:11` | `3306` | `/var/lib/mysql` | `MARIADB_ROOT_PASSWORD`, `MARIADB_DATABASE` | Idem. |
| MongoDB | `mongo:8` | `27017` | `/data/db` | `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD` | — |
| Redis | `redis:7-alpine` | `6379` | `/data` | `REDIS_PASSWORD` (bila diaktifkan) | Butuh `command` untuk password/AOF. |
| Valkey | `valkey/valkey:8-alpine` | `6379` | `/data` | — | Alternatif Redis berlisensi BSD. |
| ClickHouse | `clickhouse/clickhouse-server:24.8` | `8123` (HTTP), `9000` (native) | `/var/lib/clickhouse` | `CLICKHOUSE_PASSWORD` | Berat; pertimbangkan limit resource. |
| RabbitMQ | `rabbitmq:4-management-alpine` | `5672`, `15672` | `/var/lib/rabbitmq` | `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS` | Management UI hanya jika perlu. |
| Mosquitto | `eclipse-mosquitto:2` | `1883` | `/mosquitto/data` | — | Butuh config file (mount dari repo). |
| Meilisearch | `getmeili/meilisearch:v1.12` | `7700` | `/meili_data` | `MEILI_MASTER_KEY` | — |
| OpenSearch | `opensearchproject/opensearch:2` | `9200` | `/usr/share/opensearch/data` | `DISABLE_SECURITY_PLUGIN`, `OPENSEARCH_INITIAL_ADMIN_PASSWORD` | Berat; butuh memori besar. |

## Runtime bahasa (untuk strategi B: bind source / stage build)

| Runtime | Image contoh | Port umum | Catatan |
|---|---|---|---|
| Node.js | `node:22-alpine` | `3000` | Gunakan `working_dir` + bind source; `npm ci` di `command` atau Dockerfile. |
| PHP + Apache | `php:8.3-apache` | `80` | Bind source ke `/var/www/html`; ekstensi tambahan butuh Dockerfile. |
| PHP + FPM | `php:8.3-fpm-alpine` | `9000` | Butuh Nginx terpisah atau image gabungan seperti `serversideup/php`. |
| Python | `python:3.12-slim` | `8000` | `pip install` di `command` (lambat) atau Dockerfile. |
| Ruby | `ruby:3.3-alpine` | `3000` | Rails umumnya butuh Dockerfile (native gems). |
| Java | `eclipse-temurin:21-jre-alpine` | `8080` | Build JAR di stage Maven/Gradle (Dockerfile). |
| Go | `golang:1.23-alpine` | `8080` | Build binary di stage build (Dockerfile). |
| .NET | `mcr.microsoft.com/dotnet/aspnet:8.0` | `8080` | Registry Microsoft, bukan Docker Hub; build dengan `sdk:8.0`. |

## Web server / static

| Kebutuhan | Image contoh | Port | Catatan |
|---|---|---|---|
| Static site (hasil build) | `nginx:1.27-alpine` | `80` | Copy `dist/` ke `/usr/share/nginx/html` lewat Dockerfile, atau bind `./dist:/usr/share/nginx/html:ro`. |
| Static site (repositori HTML) | `httpd:2.4-alpine` | `80` | Bind direktori HTML ke `/usr/local/apache2/htdocs`. |
| Caddy (static/redirect) | `caddy:2-alpine` | `80` | Rames sudah menangani reverse proxy & TLS; gunakan hanya bila app memang butuh Caddy internal. |

## Yang perlu dihindari

- Image dengan tag `latest` untuk produksi.
- Image yang tidak menyediakan cara mengatur konfigurasi lewat env/volume.
- Image yang membutuhkan `privileged`/socket Docker untuk fungsi normal.
- Image yang menyimpan data di dalam layer container tanpa volume (data hilang saat recreate).
- Image yang hanya tersedia untuk arsitektur berbeda dari server target.
- Image komunitas tanpa maintainer jelas untuk data sensitif.

## Environment & volume: cek dokumentasi image

Selalu baca halaman image untuk nama env yang benar. Contoh yang sering salah:

- WordPress: `WORDPRESS_DB_*` (bukan `DB_*`).
- Ghost: `database__connection__*` (dua underscore).
- MySQL/MariaDB: password root wajib; jangan menambahkan user aplikasi jika Rames yang mengelola kredensial.
- Redis: tanpa `command` tambahan, password tidak aktif.
- Prometheus/Mosquitto: butuh file config yang di-mount; file harus ada di repo.

Kalau env/volume tidak terdokumentasi dengan jelas, **jangan menebak** — pilih image lain atau buat Dockerfile dengan konfigurasi eksplisit.
