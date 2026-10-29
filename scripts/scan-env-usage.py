#!/usr/bin/env python3
"""Inventaris environment variable untuk compose Rames.

Memindai codebase (bukan menebak dari .env.example) lalu membandingkan hasilnya
dengan berkas contoh env dan blok `environment:` di compose.

Pemakaian:
    python3 scan-env-usage.py .
    python3 scan-env-usage.py . --json
    python3 scan-env-usage.py . --strict      # exit 1 bila ada var dipakai tapi belum didokumentasikan

Output:
    A. VAR yang dibaca kode tapi TIDAK ada di berkas contoh env  -> wajib ditangani
    B. VAR di berkas contoh env tapi tidak ditemukan di kode     -> cek manual / hapus
    C. VAR yang hanya dipakai sebagai interpolasi ${...} di compose/Dockerfile/shell
    D. VAR yang dibaca kode tapi tidak ada di `environment:` compose -> tuangkan ke compose
Exit code: 0 normal, 1 bila --strict dan kategori A tidak kosong, 2 bila root tidak valid.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

# Direktori yang bukan kode aplikasi: dependency, artefak build, state runtime.
SKIP_DIRS = {
    ".git", ".hg", ".svn", ".github",
    ".idea", ".vscode",
    "node_modules", "bower_components", "jspm_packages",
    "vendor", "vendors", "site-packages",
    ".venv", "venv", "env", "virtualenv",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    ".next", ".nuxt", ".output", ".svelte-kit", ".turbo", ".parcel-cache",
    "dist", "build", "out", "target", "coverage", "htmlcov",
    "runtime", "cache", "logs", "tmp", "temp", ".cache",
    "public/pdfjs", "public/vendor",
    "bin", "obj", "packages",
}

# Berkas contoh env yang lazim; semua dibaca dan digabung.
ENV_EXAMPLE_NAMES = (
    ".env.example", ".env.sample", ".env.template", ".env.dist",
    ".env.defaults", "env.example", "example.env", "sample.env", "env.sample",
)

CODE_SUFFIXES = {
    ".php", ".phtml", ".inc",
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts", ".vue", ".svelte",
    ".py", ".pyi",
    ".go",
    ".rb", ".rake", ".gemspec",
    ".java", ".kt", ".kts", ".scala", ".groovy",
    ".cs", ".fs",
    ".rs",
    ".ex", ".exs",
    ".sh", ".bash", ".zsh",
    ".yml", ".yaml",
    ".html", ".htm", ".twig", ".blade.php",
}

# File uji tidak menentukan konfigurasi produksi.
TEST_HINT_RE = re.compile(r"(^|/)(tests?|__tests__|spec|fixtures)/|\.(test|spec)\.[a-z]+$", re.IGNORECASE)

# Variable milik OS/tooling — bukan konfigurasi aplikasi.
SYSTEM_VARS = {
    "PATH", "HOME", "PWD", "OLDPWD", "SHELL", "USER", "LOGNAME", "LANG", "LC_ALL",
    "TERM", "TERM_PROGRAM", "TERMINAL_EMULATOR", "COLORTERM", "NO_COLOR", "FORCE_COLOR",
    "COLUMNS", "LINES", "HOSTNAME", "HOSTTYPE", "OSTYPE", "MACHTYPE", "SHLVL", "TMPDIR",
    "TZ", "COMPOSER_ALLOW_SUPERUSER", "XDEBUG_MODE", "HTTP_PROXY", "HTTPS_PROXY",
    "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "CI", "GITHUB_ACTIONS", "GITHUB_WORKFLOW", "GITLAB_CI", "SHELL_VERBOSITY",
    "MSYSTEM", "PATHEXT", "HOMEDRIVE", "HOMEPATH", "SUDOMAIN_SUFFIX", "ANSICON",
    "DO_NOT_TRACK", "DO_NOT_SHOW_BANNER", "PHP_PATH", "PHP_BINARY", "PHP_PEAR_PHP_BIN",
    "SCRIPT_NAME", "SCRIPT_FILENAME", "SCRIPT_URI", "REQUEST_URI", "REMOTE_ADDR",
    "DOCUMENT_ROOT", "SERVER_ADDR", "SERVER_NAME", "SERVER_PORT", "CGI_MODE",
    "MONEY", "DEPLOYER_ROOT", "DEPLOYER_LOCAL_WORKER", "RECTOR_CACHE_DIR",
    "SYMFONY_PATCH_TYPE_DECLARATIONS", "SYMFONY_COMPLETION_DEBUG", "GUZZLE_CURL_SELECT_TIMEOUT",
    "AWS_LAMBDA_FUNCTION_NAME", "AWS_EXECUTION_ENV", "AWS_SDK_LOAD_NONDEFAULT_CONFIG",
    "AWS_SUPPRESS_PHP_DEPRECATION_WARNING", "DUMP_STRING_LENGTH", "DUMP_LIGHT_ARRAY",
    "DUMP_COMMA_SEPARATOR", "_X_AMZN_TRACE_ID", "PLUGIN_PATH", "PHINX_ENVIRONMENT",
    "HTTP_PC_REMOTE_ADDR", "HERD_HOME", "KONSOLE_VERSION", "APP_STAGE", "SSH_TTY",
    "SSH_CONNECTION", "SSH_CLIENT", "INVOCATION_ID", "JOURNAL_STREAM",
    # Diwarisi dari base image resmi (bukan konfigurasi aplikasi).
    "PHPIZE_DEPS", "PHP_INI_DIR", "PHP_VERSION", "PHP_URL", "PHP_SHA256",
    "PHP_CPPFLAGS", "PHP_LDFLAGS", "PHP_CFLAGS", "GPG_KEYS", "ALPINE_VERSION",
    "TARGETARCH", "TARGETPLATFORM", "BUILDPLATFORM", "BUILDARCH", "TARGETVARIANT",
    "NODE_OPTIONS", "NODE_PATH", "NODE_EXTRA_CA_CERTS", "NODE_VERSION",
}

# Prefix yang dipakai tooling build/vendor — bukan env runtime aplikasi.
VENDOR_PREFIXES = (
    # Hanya internal tooling build/vendor. JANGAN masukkan prefix yang lazim
    # dipakai aplikasi (NODE_, VITE_, NPM_, YARN_) — itu konfigurasi nyata.
    "COMPOSER_", "WEBPACK_", "ROLLUP_", "BABEL_", "TURBO_", "DOCKER_", "BUILDKIT_",
    "PIP_", "POETRY_", "UV_", "CARGO_", "GOFLAGS", "GOOS", "GOARCH", "RUSTUP_",
    "JAVA_HOME", "MAVEN_", "GRADLE_",
)

# Pola pembacaan env per ekosistem. Grup pertama = nama variabel.
ACCESSOR_PATTERNS = {
    "php": [
        re.compile(r"\bgetenv\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
        re.compile(r"\$_ENV\s*\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
        re.compile(r"\$_SERVER\s*\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
        # Laravel/Webman helper: env('KEY'), env('KEY', 'default')
        re.compile(r"(?<![\w>$])env\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
        re.compile(r"Env::(?:get|getOrFail)\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    ],
    "js": [
        re.compile(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"process\.env\s*\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
        re.compile(r"import\.meta\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"Deno\.env\.get\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
        re.compile(r"Bun\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
    ],
    "python": [
        re.compile(r"os\.environ\s*\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
        re.compile(r"os\.(?:getenv|environ\.get)\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
        re.compile(r"environ\.get\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
        re.compile(r"getenv\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    ],
    "go": [
        re.compile(r"os\.(?:Getenv|LookupEnv)\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    ],
    "ruby": [
        re.compile(r"ENV\s*\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
        re.compile(r"ENV\.(?:fetch|key\?)\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    ],
    "java": [
        re.compile(r"System\.getenv\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    ],
    "dotnet": [
        re.compile(r"GetEnvironmentVariable\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
        re.compile(r"Environment\.GetEnvironmentVariable\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    ],
    "rust": [
        re.compile(r"env::var\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
        re.compile(r"env::var_os\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    ],
    "elixir": [
        re.compile(r"System\.(?:get_env|fetch_env)!?\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    ],
    "shell": [
        re.compile(r"(?<![\w$])\$\{([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"(?<![\w${])\$([A-Za-z_][A-Za-z0-9_]{2,})(?![\w])"),
    ],
    "template": [
        re.compile(r"\{\{\s*env\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    ],
}

SUFFIX_TO_LANG = {
    ".php": ("php",), ".phtml": ("php",), ".inc": ("php",),
    ".js": ("js",), ".mjs": ("js",), ".cjs": ("js",), ".jsx": ("js",),
    ".ts": ("js",), ".tsx": ("js",), ".mts": ("js",), ".cts": ("js",),
    ".vue": ("js",), ".svelte": ("js",),
    ".py": ("python",), ".pyi": ("python",),
    ".go": ("go",),
    ".rb": ("ruby",), ".rake": ("ruby",), ".gemspec": ("ruby",),
    ".java": ("java",), ".kt": ("java",), ".kts": ("java",),
    ".scala": ("java",), ".groovy": ("java",),
    ".cs": ("dotnet",), ".fs": ("dotnet",),
    ".rs": ("rust",),
    ".ex": ("elixir",), ".exs": ("elixir",),
    ".sh": ("shell",), ".bash": ("shell",), ".zsh": ("shell",),
    ".yml": ("shell", "template"), ".yaml": ("shell", "template"),
    ".html": ("template",), ".htm": ("template",), ".twig": ("template",),
}

# Berkas di mana ${VAR} berarti interpolasi deploy, bukan pembacaan env aplikasi.
COMPOSE_HINT_RE = re.compile(r"(^|/)(docker-)?compose(\.[\w.-]+)?\.ya?ml$|(^|/)Dockerfile[^/]*$", re.IGNORECASE)

# Berkas compose yang menjadi acuan isi `environment:`.
COMPOSE_FILE_RE = re.compile(r"^(docker-)?compose(\.[\w.-]+)?\.ya?ml$", re.IGNORECASE)
ENV_KEY_LINE_RE = re.compile(r"^\s*(?:-\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*(?::|=|\s|$)")

ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")

# Berkas di mana komentar tidak boleh dianggap pemakaian variabel.
COMMENT_AWARE_SUFFIXES = {".yml", ".yaml", ".sh", ".bash", ".zsh"}


def mask_comments(text: str) -> str:
    """Blank-kan komentar sambil mempertahankan jumlah baris agar nomor baris akurat."""
    masked = []
    for line in text.splitlines(keepends=True):
        eol = line[len(line.rstrip("\r\n")):]
        content = line[: len(line) - len(eol)]
        if content.lstrip().startswith("#"):
            masked.append(" " * len(content) + eol)
            continue
        if "#" in content:
            index = content.index("#")
            masked.append(content[:index] + " " * (len(content) - index) + eol)
            continue
        masked.append(line)
    return "".join(masked)


def is_skipped(rel: Path) -> bool:
    parts = rel.parts
    for index, part in enumerate(parts[:-1]):
        if part in SKIP_DIRS:
            return True
        joined = "/".join(parts[: index + 2])
        if joined in SKIP_DIRS:
            return True
    return False


def read_env_example(path: Path) -> "OrderedDict[str, str]":
    """Ambil nama variabel + nilai contoh (bukan rahasia) dari berkas contoh env."""
    found: "OrderedDict[str, str]" = OrderedDict()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return found
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE_RE.match(line)
        if match:
            found.setdefault(match.group(1), match.group(2).strip())
    return found


def read_compose_env(path: Path) -> tuple["OrderedDict[str, list[str]]", bool]:
    """Ambil key dari blok `environment:` tiap service + ada/tidaknya `env_file:`.

    Parser sengaja sederhana (berbasis indentasi) agar tidak butuh PyYAML: cukup
    membaca bentuk mapping (`KEY: value`) maupun list (`- KEY=value`).
    """
    keys: "OrderedDict[str, list[str]]" = OrderedDict()
    has_env_file = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return keys, has_env_file

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("env_file:"):
            has_env_file = True
            continue
        if stripped.rstrip() != "environment:" and not stripped.startswith("environment: {"):
            continue

        if stripped.startswith("environment: {"):
            for key in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", stripped[len("environment: {"):]):
                keys.setdefault(key, []).append(f"{path.name}:{index + 1}")
            continue

        base_indent = len(line) - len(line.lstrip())
        for offset, child in enumerate(lines[index + 1:], start=index + 2):
            if not child.strip() or child.strip().startswith("#"):
                continue
            indent = len(child) - len(child.lstrip())
            if indent <= base_indent:
                break
            match = ENV_KEY_LINE_RE.match(child)
            if match:
                keys.setdefault(match.group(1), []).append(f"{path.name}:{offset}")
    return keys, has_env_file


def scan(root: Path) -> dict:
    code_hits: "OrderedDict[str, list[str]]" = OrderedDict()
    interpolated: "OrderedDict[str, list[str]]" = OrderedDict()
    env_files: "OrderedDict[str, OrderedDict[str, str]]" = OrderedDict()
    compose_env: "OrderedDict[str, list[str]]" = OrderedDict()
    compose_files: list[str] = []
    compose_has_env_file = False

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if is_skipped(rel):
            continue
        if path.name in ENV_EXAMPLE_NAMES:
            env_files[str(rel)] = read_env_example(path)
            continue
        if COMPOSE_FILE_RE.match(path.name) and len(rel.parts) == 1:
            compose_files.append(path.name)
            found, has_env_file = read_compose_env(path)
            compose_has_env_file = compose_has_env_file or has_env_file
            for key, sites in found.items():
                compose_env.setdefault(key, []).extend(sites)

        suffix = path.suffix.lower()
        name_lower = path.name.lower()
        is_dockerfile = name_lower == "dockerfile" or name_lower.startswith("dockerfile.")
        if is_dockerfile:
            langs: tuple[str, ...] = ("shell",)
        elif name_lower.endswith(".blade.php"):
            langs = ("php", "template")
        else:
            langs = SUFFIX_TO_LANG.get(suffix, ())
        if not langs:
            continue
        if not is_dockerfile and suffix not in CODE_SUFFIXES:
            continue
        if TEST_HINT_RE.search(str(rel)):
            continue

        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        is_interpolation_only = bool(COMPOSE_HINT_RE.search(str(rel)))
        bucket = interpolated if is_interpolation_only else code_hits

        if suffix in COMMENT_AWARE_SUFFIXES or name_lower.startswith("dockerfile"):
            text = mask_comments(text)

        for lang in langs:
            for pattern in ACCESSOR_PATTERNS.get(lang, ()):
                for match in pattern.finditer(text):
                    var = match.group(1)
                    line_no = text.count("\n", 0, match.start()) + 1
                    bucket.setdefault(var, [])
                    entry = f"{rel}:{line_no}"
                    if entry not in bucket[var] and len(bucket[var]) < 25:
                        bucket[var].append(entry)

    return {
        "code": code_hits,
        "interpolated": interpolated,
        "env_files": env_files,
        "compose_files": compose_files,
        "compose_env": compose_env,
        "compose_has_env_file": compose_has_env_file,
        "root": str(root),
    }


def is_noise(var: str) -> bool:
    if var in SYSTEM_VARS:
        return True
    if var.islower():
        return True  # path/locale seperti ${target}, ${HOME}
    return var.upper().startswith(VENDOR_PREFIXES)


def documented_vars(env_files: dict) -> "OrderedDict[str, list[str]]":
    documented: "OrderedDict[str, list[str]]" = OrderedDict()
    for file_name, pairs in env_files.items():
        for key in pairs:
            documented.setdefault(key, []).append(file_name)
    return documented


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventaris env variable dari codebase untuk compose Rames.")
    parser.add_argument("root", nargs="?", default=".", help="akar project (default: .)")
    parser.add_argument("--json", action="store_true", help="keluarkan JSON")
    parser.add_argument("--strict", action="store_true", help="exit 1 bila ada var dipakai tapi tidak didokumentasikan")
    parser.add_argument("--max-sites", type=int, default=3, help="jumlah lokasi pemakaian yang ditampilkan per var")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"akar project tidak valid: {root}", file=sys.stderr)
        return 2

    result = scan(root)
    documented = documented_vars(result["env_files"])

    used = OrderedDict()
    for var, sites in result["code"].items():
        if is_noise(var):
            continue
        used[var] = sites

    missing = OrderedDict((v, s) for v, s in used.items() if v not in documented)
    undocumented_unused = OrderedDict((v, files) for v, files in documented.items() if v not in used)
    interp_only = OrderedDict(
        (v, s) for v, s in result["interpolated"].items() if not is_noise(v) and v not in used
    )

    compose_env = result["compose_env"]
    not_in_compose = OrderedDict()
    if result["compose_files"] and not result["compose_has_env_file"]:
        not_in_compose = OrderedDict((v, s) for v, s in used.items() if v not in compose_env)

    if args.json:
        payload = {
            "root": result["root"],
            "env_examples": list(result["env_files"]),
            "compose_files": result["compose_files"],
            "used_in_code": {v: s for v, s in used.items()},
            "missing_from_env_examples": {v: s for v, s in missing.items()},
            "declared_but_unused": {v: f for v, f in undocumented_unused.items()},
            "interpolation_only": {v: s for v, s in interp_only.items()},
            "missing_from_compose_environment": {v: s for v, s in not_in_compose.items()},
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1 if (args.strict and missing) else 0

    print(f"Scan env variable — {root}")
    if result["env_files"]:
        print("Berkas contoh env: " + ", ".join(result["env_files"]))
    else:
        print("Berkas contoh env: (tidak ada — buat .env.example dari kategori A)")
    if result["compose_files"]:
        print("Berkas compose: " + ", ".join(result["compose_files"]))
    else:
        print("Berkas compose: (belum ada)")
    print()

    def dump(title: str, items: dict, note: str, limit: int) -> None:
        print(f"{title} ({len(items)})")
        if not items:
            print("  (kosong)")
        for var in list(items)[:200]:
            sites = items[var]
            shown = sites[:limit] if isinstance(sites, list) else sites
            print(f"  - {var}")
            if isinstance(sites, list):
                for site in shown:
                    print(f"      {site}")
                if len(sites) > len(shown):
                    print(f"      … {len(sites) - len(shown)} lokasi lain")
            else:
                print(f"      dideklarasikan di: {sites}")
        print(f"  → {note}")
        print()

    dump(
        "A. Dibaca kode, BELUM ada di contoh env",
        missing,
        "masukkan ke docker-compose.yml (${VAR}) dan ke .env.example; isi nilai asli di Environment Rames.",
        args.max_sites,
    )
    dump(
        "B. Ada di contoh env, tidak ditemukan di kode",
        undocumented_unused,
        "verifikasi manual: dipakai tooling/CLI atau sisa usang — hapus bila benar-benar mati.",
        args.max_sites,
    )
    dump(
        "C. Hanya interpolasi ${...} di compose/Dockerfile/shell",
        interp_only,
        "dipakai saat deploy (bukan dibaca kode); tetap harus disediakan lewat .env lokal atau Environment Rames.",
        args.max_sites,
    )
    dump(
        "D. Dibaca kode, tidak ada di 'environment:' compose",
        not_in_compose,
        "tuangkan ke environment: compose sebagai ${VAR} agar lokal & Rames konsisten "
        "(Rames tetap menyuntikkan env dari UI, jadi ini peringatan bukan kegagalan).",
        args.max_sites,
    )

    if missing:
        print("Contoh kerangka compose untuk kategori A:")
        print("    environment:")
        for var in missing:
            print(f"      {var}: ${{{var}:-}}")
        print()

    return 1 if (args.strict and missing) else 0


if __name__ == "__main__":
    sys.exit(main())
