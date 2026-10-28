#!/usr/bin/env python3
"""Validator docker-compose.yml untuk kompatibilitas deploy di dashboard Rames.

Pemakaian:
    python3 validate-compose.py docker-compose.yml --mode git
    python3 validate-compose.py docker-compose.yml --mode template --docker

Mode:
    git       build: boleh (app dari repo Git)
    compose   build: ditolak (mode Compose paste/upload)
    template  build: ditolak (templates/<slug>/)

Exit code: 0 = tidak ada error, 1 = ada error.
Warning tidak menggagalkan validasi kecuali --strict.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SECRET_KEY_RE = re.compile(
    r"(PASSWORD|PASSWD|SECRET|TOKEN|API[_-]?KEY|PRIVATE[_-]?KEY|ACCESS[_-]?KEY|SECRET[_-]?KEY)",
    re.IGNORECASE,
)
HOST_PORT_RE = re.compile(r"^\s*-\s*[\"']?(?:[^\"':]+:)?(80|443):", re.MULTILINE)
HOST_PUBLISHED_RE = re.compile(r"^\s*published:\s*[\"']?(80|443)[\"']?\s*$", re.MULTILINE)
IMAGE_RE = re.compile(r"^\s+image:\s*[\"']?([^\"'\s#]+)", re.MULTILINE)
ABS_BIND_RE = re.compile(r"^\s*-\s*[\"']?(/[^:\n]+):", re.MULTILINE)
SERVICE_BUILD_RE = re.compile(r"^\s{2,}build:\s*", re.MULTILINE)


def load_yaml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return None, "PyYAML tidak tersedia"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - pesan apa adanya untuk pengguna
        return None, f"YAML tidak valid: {exc}"
    if not isinstance(data, dict):
        return None, "Dokumen YAML bukan mapping"
    return data, None


def docker_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    docker = shutil.which("docker")
    if docker is None:
        return None, "docker tidak tersedia"
    resolved = path.resolve()
    try:
        proc = subprocess.run(
            [docker, "compose", "-f", str(resolved), "config", "--format", "json"],
            cwd=str(resolved.parent),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"docker compose gagal dijalankan: {exc}"
    if proc.returncode != 0:
        return None, "docker compose config gagal: " + (proc.stderr.strip() or proc.stdout.strip())
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return None, f"output docker compose bukan JSON: {exc}"
    return data if isinstance(data, dict) else None, None


def is_pos_int(value: Any) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def port_error(value: Any) -> tuple[str | None, bool]:
    """Kembalikan (pesan_error, ip_binding) untuk satu entri ports Compose."""
    if isinstance(value, int):
        return (None, False) if 1 <= value <= 65535 else (f"port container {value} tidak valid", False)

    if isinstance(value, dict):
        published = value.get("published")
        if published not in (None, ""):
            try:
                published_int = int(published)
            except (TypeError, ValueError):
                return (f"published port tidak valid: {published!r}", False)
            if published_int in (80, 443):
                return ("host port 80/443 dipakai Nginx host Rames", False)
            if not 1 <= published_int <= 65535:
                return (f"host port {published_int} tidak valid", False)
        return (None, bool(value.get("host_ip")))

    if isinstance(value, str):
        raw = value.split("/", 1)[0].strip()
        parts = raw.split(":")
        if len(parts) == 1:
            return (None, False) if parts[0].isdigit() else (f"port tidak valid: {value!r}", False)
        if len(parts) == 2:
            host, container = parts
            ip_binding = False
        elif len(parts) == 3:
            host, container = parts[1], parts[2]
            ip_binding = True
        else:
            return (f"port tidak valid: {value!r}", False)
        if not container.isdigit():
            return (f"port container tidak valid: {value!r}", False)
        if host.isdigit():
            host_int = int(host)
            if host_int in (80, 443):
                return ("host port 80/443 dipakai Nginx host Rames", False)
            if not 1 <= host_int <= 65535:
                return (f"host port {host_int} tidak valid", False)
        return (None, ip_binding)

    return (f"format port tidak dikenal: {value!r}", False)


def check_environment(service: str, env: Any, warnings: list[str]) -> None:
    pairs: list[tuple[str, Any]] = []
    if isinstance(env, dict):
        pairs = list(env.items())
    elif isinstance(env, list):
        for item in env:
            if isinstance(item, str) and "=" in item:
                key, value = item.split("=", 1)
                pairs.append((key, value))
    for key, value in pairs:
        if not isinstance(key, str) or not SECRET_KEY_RE.search(key):
            continue
        if value is None or value == "":
            continue
        if isinstance(value, str) and (value.startswith("${") or value.startswith("$")):
            continue
        warnings.append(
            f"service '{service}': environment '{key}' berisi nilai literal; "
            "isi lewat tab Environment Rames dan gunakan ${VAR}."
        )


def image_without_pin(image: str) -> bool:
    ref = image.split("@", 1)[0]
    last = ref.rsplit("/", 1)[-1]
    if ":" not in last:
        return True
    return last.rsplit(":", 1)[-1] == "latest"


def structural_checks(data: dict[str, Any], mode: str, allow_privileged: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if "name" in data:
        errors.append("'name:' di level atas dilarang — nama project compose = nama app Rames.")
    services = data.get("services")
    if not isinstance(services, dict) or not services:
        errors.append("'services:' wajib ada dan tidak boleh kosong.")
        return errors, warnings

    any_port = False
    for name, svc in services.items():
        service = str(name)
        if not isinstance(svc, dict):
            errors.append(f"service '{service}' bukan mapping.")
            continue

        if "container_name" in svc:
            errors.append(f"service '{service}': 'container_name' dilarang — Rames mengelola prefix nama container.")

        if svc.get("privileged") is True and not allow_privileged:
            errors.append(f"service '{service}': 'privileged: true' tidak aman untuk app Rames.")

        network_mode = str(svc.get("network_mode", "") or "")
        if network_mode == "host" or network_mode.startswith("container:"):
            errors.append(f"service '{service}': 'network_mode: {network_mode}' tidak kompatibel dengan proxy/isolasi Rames.")
        for key in ("pid", "ipc"):
            if str(svc.get(key, "") or "") == "host":
                errors.append(f"service '{service}': '{key}: host' tidak diizinkan.")

        deploy = svc.get("deploy") if isinstance(svc.get("deploy"), dict) else {}
        for key, value in (("deploy.replicas", deploy.get("replicas")), ("scale", svc.get("scale"))):
            if is_pos_int(value) and int(value) > 1:
                errors.append(f"service '{service}': '{key} > 1' tidak kompatibel dengan nama container otomatis.")

        build = svc.get("build")
        has_build = build not in (None, "", {})
        image = svc.get("image")
        if has_build and mode != "git":
            errors.append(
                f"service '{service}': 'build:' ditolak pada mode {mode}; "
                "gunakan image prebuilt atau deploy lewat mode Clone repo Git."
            )
        if not has_build and (not isinstance(image, str) or not image.strip()):
            errors.append(f"service '{service}': wajib punya 'image:' (atau 'build:' pada mode git).")
        if isinstance(image, str) and image.strip() and image_without_pin(image.strip()):
            warnings.append(f"service '{service}': image '{image.strip()}' tidak di-pin (tanpa tag atau ':latest').")

        ports = svc.get("ports")
        if isinstance(ports, list):
            any_port = any_port or bool(ports)
            for entry in ports:
                message, ip_binding = port_error(entry)
                if message:
                    errors.append(f"service '{service}': {message} (port {entry!r}).")
                if ip_binding:
                    warnings.append(f"service '{service}': IP binding pada port {entry!r}; Rames menulis mapping tanpa IP.")
        elif ports is not None:
            errors.append(f"service '{service}': 'ports' harus berupa list.")

        check_environment(service, svc.get("environment"), warnings)

        if "env_file" in svc:
            warnings.append(
                f"service '{service}': 'env_file' terdeteksi — Rames sudah menyuntikkan env; "
                "pastikan berkas ada dan tidak berisi rahasia."
            )

        volumes = svc.get("volumes")
        if isinstance(volumes, list):
            for entry in volumes:
                if isinstance(entry, str) and entry.startswith("/"):
                    warnings.append(f"service '{service}': bind absolut '{entry}' tidak portabel antar server Rames.")
                if isinstance(entry, dict) and str(entry.get("source", "")).startswith("/"):
                    warnings.append(
                        f"service '{service}': bind absolut '{entry.get('source')}' tidak portabel antar server Rames."
                    )

        if not svc.get("restart"):
            warnings.append(f"service '{service}': tidak ada 'restart:' (disarankan 'unless-stopped').")
        if not svc.get("logging"):
            warnings.append(f"service '{service}': tidak ada batas log ('logging.options.max-size').")
        if ports and not svc.get("healthcheck"):
            warnings.append(f"service '{service}': service publik tanpa 'healthcheck'.")

    if not any_port:
        warnings.append("Tidak ada service yang mem-publish port — app tidak akan mendapat vhost/subdomain.")

    top_volumes = data.get("volumes")
    if isinstance(top_volumes, dict):
        for vol_name, definition in top_volumes.items():
            if not isinstance(definition, dict):
                continue
            opts = definition.get("driver_opts")
            device = opts.get("device") if isinstance(opts, dict) else None
            if isinstance(device, str) and device.startswith("/"):
                warnings.append(
                    f"volume '{vol_name}': driver_opts.device '{device}' menunjuk path host absolut; "
                    "tidak portabel antar server."
                )

    return errors, warnings


def text_checks(text: str, mode: str, allow_privileged: bool) -> tuple[list[str], list[str]]:
    """Pemeriksaan cadangan saat YAML tidak bisa diparse."""
    errors: list[str] = []
    warnings: list[str] = []

    if re.search(r"^name\s*:", text, re.MULTILINE):
        errors.append("'name:' di level atas dilarang.")
    if re.search(r"^\s*container_name\s*:", text, re.MULTILINE):
        errors.append("'container_name' dilarang — Rames mengelola prefix nama container.")
    if not allow_privileged and re.search(r"^\s*privileged\s*:\s*true\s*$", text, re.MULTILINE):
        errors.append("'privileged: true' tidak aman untuk app Rames.")
    if re.search(r"^\s*network_mode\s*:\s*[\"']?host", text, re.MULTILINE):
        errors.append("'network_mode: host' tidak kompatibel dengan proxy/isolasi Rames.")
    if re.search(r"^\s*pid\s*:\s*[\"']?host", text, re.MULTILINE):
        errors.append("'pid: host' tidak diizinkan.")
    if HOST_PORT_RE.search(text) or HOST_PUBLISHED_RE.search(text):
        errors.append("host port 80/443 dipakai Nginx host Rames.")
    if mode != "git" and SERVICE_BUILD_RE.search(text):
        errors.append(f"'build:' ditolak pada mode {mode}.")
    if not re.search(r"^services\s*:", text, re.MULTILINE):
        errors.append("'services:' wajib ada.")
    for image in IMAGE_RE.findall(text):
        if image_without_pin(image):
            warnings.append(f"image '{image}' tidak di-pin (tanpa tag atau ':latest').")
    if ABS_BIND_RE.search(text):
        warnings.append("Terdapat bind mount path absolut host; tidak portabel antar server Rames.")
    if re.search(r"^\s*env_file\s*:", text, re.MULTILINE):
        warnings.append("'env_file' terdeteksi — pastikan berkas ada dan tidak berisi rahasia.")
    return errors, warnings


def run_docker_config(path: Path) -> tuple[str | None, str | None]:
    docker = shutil.which("docker")
    if docker is None:
        return None, "docker tidak tersedia; validasi sintaks compose dilewati."
    resolved = path.resolve()
    try:
        proc = subprocess.run(
            [docker, "compose", "-f", str(resolved), "config", "--quiet"],
            cwd=str(resolved.parent),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"docker compose config gagal dijalankan: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()[:3]
        return "docker compose config --quiet gagal: " + " | ".join(detail), None
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validasi compose untuk Rames.")
    parser.add_argument("file", nargs="?", default="docker-compose.yml", help="path docker-compose.yml")
    parser.add_argument(
        "--mode",
        choices=("git", "compose", "template"),
        default="git",
        help="mode deploy Rames (default: git)",
    )
    parser.add_argument("--docker", action="store_true", help="jalankan 'docker compose config --quiet'")
    parser.add_argument("--allow-privileged", action="store_true", help="izinkan privileged: true")
    parser.add_argument("--strict", action="store_true", help="warning dianggap error")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"FAIL: file tidak ditemukan: {path}")
        return 1
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        print(f"FAIL: file kosong: {path}")
        return 1

    data, yaml_error = load_yaml(path)
    if data is None and args.docker:
        data, docker_error = docker_json(path)
        yaml_error = yaml_error if data is None else None
        if data is None and docker_error:
            yaml_error = f"{yaml_error}; {docker_error}" if yaml_error else docker_error

    if data is not None:
        errors, warnings = structural_checks(data, args.mode, args.allow_privileged)
    else:
        errors, warnings = text_checks(text, args.mode, args.allow_privileged)
        warnings.insert(0, f"Pemeriksaan struktural terbatas: {yaml_error}. Pasang PyYAML atau pakai --docker.")

    docker_hint = None
    if args.docker:
        error, hint = run_docker_config(path)
        if error:
            errors.append(error)
        if hint:
            warnings.append(hint)

    print(f"Rames compose validation — {path} (mode: {args.mode})")
    if errors:
        print("\nERROR:")
        for item in errors:
            print(f"  - {item}")
    if warnings:
        print("\nWARNING:")
        for item in warnings:
            print(f"  - {item}")
    if not errors and not warnings:
        print("\nPASS: tidak ada masalah yang terdeteksi.")
    elif not errors:
        print("\nPASS dengan warning.")
    else:
        print("\nFAIL: perbaiki error di atas sebelum deploy.")

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
