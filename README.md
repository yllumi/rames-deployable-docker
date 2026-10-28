# Rames Deployable Docker

Skill untuk agen AI di VS Code yang menghasilkan `docker-compose.yml` — dan `Dockerfile` hanya bila benar-benar diperlukan — untuk project apa pun agar **langsung bisa dideploy** di dashboard Rames.

Pendekatannya **image-first**: cari image resmi/tepercaya di Docker Hub lebih dulu, lalu tulis compose yang patuh pada kontrak Rames (port, volume, env, keamanan). Dockerfile hanya dibuat jika image yang tersedia tidak bisa menjalankan project tanpa kustomisasi build.

---

## Masalah yang dicegah

Deploy di Rames sering gagal bukan karena aplikasinya rusak, tetapi karena compose melanggar hal-hal yang dikelola Rames sendiri:

| Gejala di dashboard | Penyebab umum |
|---|---|
| Container tidak bisa dibuat / nama bentrok | `container_name:` atau `name:` ditulis manual |
| Halaman app tidak bisa diakses | host port `80:80` / `443:443`, atau port ditulis sebagai `HOST:CONTAINER` |
| Data hilang setiap redeploy | state disimpan di filesystem container, bukan named volume |
| Validasi template gagal | `build:` dipakai pada mode template / Compose paste |
| App mati di server ARM | image tidak multi-arch (`amd64` + `arm64`) |
| Rahasia bocor ke repo | password/token literal di compose, `.env`, atau `ARG`/`ENV` Dockerfile |

Skill ini mengaudit keenam hal tersebut sebelum file diserahkan, lalu memverifikasinya dengan validator otomatis.

## Prinsip

1. **Image-first** — image resmi dulu, Dockerfile belakangan.
2. **Satu service web publik** yang mendeklarasikan port container; DB/worker cukup di jaringan internal.
3. **Port container saja** (`- "3000"`), tanpa host port dan tanpa bind IP.
4. **Semua state di named volume** agar aman saat redeploy dan mudah dibackup.
5. **Konfigurasi lewat `${VAR}`** + `.env.example` tanpa nilai rahasia.
6. **Validasi otomatis** sebelum diserahkan, bukan setelah deploy gagal.

---

## Struktur repository

```text
rames-deployable-docker/
├── SKILL.md                    # Definisi skill + alur kerja Langkah 0–6
├── README.md                   # Dokumentasi penggunaan (berkas ini)
├── assets/                     # Template siap salin
│   ├── compose-official-image.yml  # Strategi A: image siap pakai
│   ├── compose-with-db.yml         # Strategi A + database internal
│   ├── compose-runtime-bind.yml    # Strategi B: runtime resmi + source di-bind
│   ├── compose-build.yml           # Strategi C: build dari Dockerfile
│   ├── Dockerfile.node             # Resep Dockerfile per bahasa
│   ├── Dockerfile.php
│   ├── Dockerfile.python
│   ├── Dockerfile.go
│   ├── Dockerfile.java
│   ├── Dockerfile.static
│   ├── dockerignore                # Contoh .dockerignore
│   └── env.example                 # Contoh dokumentasi env (tanpa rahasia)
├── references/                 # Dokumentasi pendukung
│   ├── rames-compose-contract.md   # Kontrak compose Rames (aturan + alasan)
│   ├── image-catalog.md            # Katalog image Docker Hub yang aman dipakai
│   └── dockerfile-recipes.md       # Resep Dockerfile multi-stage per bahasa
└── scripts/                    # Alat validasi
    └── validate-compose.py         # Validator kompatibilitas compose Rames
```

| Berkas | Isi |
|---|---|
| [SKILL.md](./SKILL.md) | Instruksi utama: inventaris project, pemilihan image, strategi, penulisan compose, env, Dockerfile, validasi, format laporan |
| [references/rames-compose-contract.md](./references/rames-compose-contract.md) | Detail kontrak: mode deploy, kunci yang dikelola Rames, port, env, volume, network, healthcheck, keamanan |
| [references/image-catalog.md](./references/image-catalog.md) | Kandidat image per kategori + cara memverifikasi tag dan arsitektur |
| [references/dockerfile-recipes.md](./references/dockerfile-recipes.md) | Pola multi-stage untuk Node, PHP, Python, static, Go, Java |
| [scripts/validate-compose.py](./scripts/validate-compose.py) | Pemeriksa otomatis aturan wajib/dilarang |

---

## Instalasi

Skill ini adalah folder skill standar (`SKILL.md` + aset pendukung). Pasang sesuai cakupan yang diinginkan:

**Per project** — agar ikut ter-versi bersama repo aplikasi:

```bash
mkdir -p .github/skills
git clone <url-repo-ini> .github/skills/rames-deployable-docker
```

**Per user** — agar tersedia di semua workspace: salin folder ini ke direktori skills milik profil VS Code Anda, lalu muat ulang window.

Setelah terpasang, skill akan terdeteksi dari `name` dan `description` pada frontmatter `SKILL.md`, sehingga agen memanggilnya otomatis saat permintaan cocok.

### Prasyarat validator

- Python 3.9+
- PyYAML (opsional, sangat disarankan)

```bash
python3 -m pip install pyyaml
```

Tanpa PyYAML, validator tetap berjalan memakai pemeriksaan berbasis teks, tetapi hasilnya kurang lengkap dan memunculkan warning. Docker hanya diperlukan bila memakai flag `--docker`.

---

## Cara pakai

Minta langsung ke agen, misalnya:

```text
Buatkan docker-compose untuk Rames untuk project Laravel ini.
```

```text
Dockerize project Next.js ini agar bisa dideploy di dashboard Rames,
pakai image resmi kalau memungkinkan.
```

```text
Pilih image Docker Hub yang cocok untuk n8n, lalu tulis compose Rames-nya.
```

```text
Audit docker-compose.yml yang sudah ada — apakah aman dideploy di Rames?
```

Agen akan menyusun laporan akhir berisi strategi yang dipilih, **primary service + port container** untuk wizard Rames, env wajib, volume yang harus ikut backup, daftar file yang dibuat, hasil validator, serta catatan kompatibilitas (tag, arsitektur, batasan).

### Alur kerja skill

| Langkah | Yang dilakukan |
|---|---|
| **0 — Inventaris** | Runtime & versi, entrypoint & port HTTP, state persisten, dependensi eksternal, env wajib, proses latar, arsitektur target |
| **1 — Cari image** | Official image → verified publisher → komunitas; cek tag spesifik, multi-arch, dukungan env/volume, port |
| **2 — Pilih strategi** | A (image siap pakai), B (runtime resmi + source di-bind), C (Dockerfile) |
| **3 — Tulis compose** | Ikuti kontrak Rames (lihat bagian berikut) |
| **4 — Env & rahasia** | `${VAR}` di compose, `.env.example` tanpa nilai rahasia, nilai asli lewat tab Environment |
| **5 — Dockerfile** | Hanya bila perlu: multi-stage, non-root, `exec` form `CMD`, `.dockerignore` |
| **6 — Validasi** | Jalankan validator, opsional `docker compose config`, lalu checklist manual |

### Strategi deploy

| Situasi | Strategi | Dockerfile? |
|---|---|---|
| Aplikasi siap pakai (CMS, automation, database, dashboard) | `image:` + env + named volume | Tidak |
| Kode aplikasi tanpa proses build, runtime resmi tersedia | `image:` runtime resmi + bind source + `command` | Tidak |
| Perlu build asset/kompilasi/ekstensi native, atau runtime tidak cocok | Multi-stage Dockerfile + `build:` | Ya |
| Template Rames (`templates/<slug>/`) | Image prebuilt saja | Tidak (mode template menolak `build:`) |

> `build:` hanya valid pada mode **Clone repo Git**. Untuk mode **Compose paste/upload** dan **Template**, compose wajib memakai `image:` prebuilt.

---

## Aturan compose Rames

**WAJIB**

- `services:` tidak kosong; setiap service punya `image:` atau `build:`.
- Tepat satu service web publik yang mendeklarasikan port container.
- Port ditulis sebagai port container saja: `- "3000"`.
- Named volume untuk semua state; bind relatif `./data` boleh, tetapi berkas yang di-mount harus ada di repo.
- `restart: unless-stopped`, `healthcheck`, dan `depends_on` dengan `condition: service_healthy` bila ada DB.
- Log dibatasi: `logging: {driver: json-file, options: {max-size: "10m", max-file: "3"}}`.
- `${VAR}` untuk konfigurasi; sertakan `.env.example`.
- Tag image dipin (minimal versi minor), bukan `latest`.

**DILARANG**

- `container_name:` dan `name:` di level atas.
- `deploy.replicas` / `scale` > 1.
- Host port **80/443** (dipakai Nginx host Rames).
- `network_mode: host`, `pid: host`, `ipc: host`, `privileged: true`, `cap_add` tanpa alasan kuat.
- Mount `/var/run/docker.sock` untuk app biasa.
- Bind ke path absolut host (`/srv/...`, `/home/...`).
- Secret literal di compose, `.env.example`, `ARG`, atau `ENV` image.

Detail lengkap beserta alasannya ada di [references/rames-compose-contract.md](./references/rames-compose-contract.md).

---

## Validator

```bash
python3 scripts/validate-compose.py docker-compose.yml --mode git
```

Jika skill dipasang di dalam project, sesuaikan path-nya, misalnya:

```bash
python3 .github/skills/rames-deployable-docker/scripts/validate-compose.py docker-compose.yml --mode git
```

### Opsi

| Opsi | Default | Keterangan |
|---|---|---|
| `file` | `docker-compose.yml` | Path compose yang divalidasi |
| `--mode {git,compose,template}` | `git` | `git` mengizinkan `build:`; `compose`/`template` menolaknya |
| `--docker` | mati | Jalankan `docker compose config` untuk validasi sintaks nyata |
| `--allow-privileged` | mati | Lewati pemeriksaan `privileged: true` — hanya untuk kasus yang benar-benar memerlukan dan sudah disetujui |
| `--strict` | mati | Warning diperlakukan sebagai error |

### Exit code

- `0` — tidak ada error (boleh ada warning)
- `1` — ada error (atau ada warning saat `--strict`)

### Contoh keluaran

```console
$ python3 scripts/validate-compose.py assets/compose-with-db.yml --mode git
Rames compose validation — assets/compose-with-db.yml (mode: git)

PASS: tidak ada masalah yang terdeteksi.
```

```console
$ python3 scripts/validate-compose.py assets/compose-build.yml --mode compose
Rames compose validation — assets/compose-build.yml (mode: compose)

ERROR:
  - service 'app': 'build:' ditolak pada mode compose; gunakan image prebuilt atau deploy lewat mode Clone repo Git.

FAIL: perbaiki error di atas sebelum deploy.
```

Validasi sintaks Compose tanpa mencetak isi env:

```bash
docker compose -f docker-compose.yml config --quiet
```

> Jangan menjalankan `docker compose up` / `down -v` pada project Rames yang sedang berjalan.

---

## Aset siap salin

```bash
# Compose untuk aplikasi dengan database internal
cp assets/compose-with-db.yml docker-compose.yml

# Dokumentasi env (tanpa nilai rahasia)
cp assets/env.example .env.example

# .dockerignore bila membuat Dockerfile
cp assets/dockerignore .dockerignore
```

Setelah menyalin, ganti `image:`/`command:`/path volume sesuai aplikasi, lalu jalankan validator. Semua aset compose di folder `assets/` sudah lolos validator pada mode `git`.

---

## Referensi

- [Kontrak compose Rames](./references/rames-compose-contract.md) — aturan, override yang ditulis Rames, mode template
- [Katalog image Docker Hub](./references/image-catalog.md) — kandidat image dan hal yang perlu dihindari
- [Resep Dockerfile](./references/dockerfile-recipes.md) — pola multi-stage per bahasa dan integrasi dengan compose
- [Validator](./scripts/validate-compose.py) — implementasi pemeriksaan otomatis
- [SKILL.md](./SKILL.md) — instruksi lengkap yang dijalankan agen

---

## Kontribusi

Saat mengubah aturan kontrak, perbarui ketiganya secara konsisten: `SKILL.md`, `references/rames-compose-contract.md`, dan pemeriksaan di `scripts/validate-compose.py`. Lalu pastikan semua aset tetap lolos:

```bash
for f in assets/compose-*.yml; do
  python3 scripts/validate-compose.py "$f" --mode git || exit 1
done
```
