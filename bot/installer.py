"""Автоматическая установка: бинарники PHP 7.0/7.1/7.2 + конфиг сервера.

Логика поиска PHP (по порядку, до первого успеха):
  1. уже установленный PHP в runtime/php (проверка версии и pthreads);
  2. PHP_BINARY_PATH - готовый бинарник, указанный вручную;
  3. локальные архивы в php_cache/*.tar.gz (работает без интернета);
  4. скачивание с зеркал PocketMine (PHP_BINARY_URL или встроенный список);
  5. сборка из исходников через pmmp/php-build-scripts (если ALLOW_PHP_BUILD=1).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, SUPPORTED_PHP
from .props import DEFAULT_POCKETMINE_YML, default_properties, read_properties, write_properties

log = logging.getLogger("installer")

USER_AGENT = "mcpe-telegram-host/1.0 (+auto-installer)"


def php_mirrors(version: str, arch: str) -> list[str]:
    """Zerkala gotovyh binarnikov PHP s pthreads dlya PocketMine/Genisys."""
    tag = "PHP-" + version + "-Linux-" + arch
    jenkins = "https://jenkins.pmmp.io/job/PHP-" + version + "-Aggregate"
    ci = "https://ci.pmmp.io/job/PHP-" + version + "-Aggregate"
    releases = "https://github.com/pmmp/PHP-Binaries/releases/download"
    return [
        jenkins + "/lastSuccessfulBuild/artifact/" + tag + ".tar.gz",
        jenkins + "/lastStableBuild/artifact/" + tag + ".tar.gz",
        ci + "/lastSuccessfulBuild/artifact/" + tag + ".tar.gz",
        releases + "/php-" + version + "-latest/" + tag + ".tar.gz",
        releases + "/pm3-php-" + version + "-latest/" + tag + ".tar.gz",
        releases + "/php-" + version + "-latest/" + tag + "-PM3.tar.gz",
    ]


BUILD_SCRIPT_REFS = ("php7.2", "php-7.2", "legacy/php7.2", "php7.1", "master")


@dataclass
class InstallReport:
    php_binary: Path | None = None
    php_version: str = ""
    php_ini: Path | None = None
    has_pthreads: bool = False
    steps: list[str] = field(default_factory=list)
    ok: bool = False

    def log(self, message: str) -> None:
        log.info(message)
        self.steps.append(message)

    def text(self, limit: int = 25) -> str:
        return "\n".join(self.steps[-limit:])


# --------------------------------------------------------------------- утилиты
def find_php_binary(root: Path) -> Path | None:
    candidates = [
        root / "bin" / "php7" / "bin" / "php",
        root / "php7" / "bin" / "php",
        root / "bin" / "php",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches = sorted(root.glob("**/bin/php"))
    for match in matches:
        if match.is_file():
            return match
    return None


def probe_php(binary: Path) -> tuple[str, bool]:
    """Возвращает (версия, есть_pthreads)."""
    env = dict(os.environ)
    lib_dir = binary.parent.parent / "lib"
    if lib_dir.is_dir():
        env["LD_LIBRARY_PATH"] = f"{lib_dir}:{env.get('LD_LIBRARY_PATH', '')}".rstrip(":")
    try:
        binary.chmod(0o755)
    except OSError:
        pass
    try:
        version_out = subprocess.run(
            [str(binary), "-v"], capture_output=True, text=True, timeout=30, env=env
        ).stdout
        modules_out = subprocess.run(
            [str(binary), "-m"], capture_output=True, text=True, timeout=30, env=env
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("PHP не запускается (%s): %s", binary, exc)
        return "", False
    match = re.search(r"PHP (\d+\.\d+\.\d+)", version_out)
    version = match.group(1) if match else ""
    has_pthreads = "pthreads" in modules_out.lower()
    return version, has_pthreads


def version_supported(version: str) -> bool:
    return bool(version) and version.rsplit(".", 1)[0] in SUPPORTED_PHP


def php_ini_for(binary: Path) -> Path | None:
    for candidate in (binary.parent / "php.ini", binary.parent.parent / "bin" / "php.ini"):
        if candidate.is_file():
            return candidate
    return None


def _download(url: str, destination: Path, report: InstallReport) -> bool:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=60) as resp, tmp.open("wb") as handle:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                block = resp.read(256 * 1024)
                if not block:
                    break
                handle.write(block)
                downloaded += len(block)
        if downloaded < 1_000_000:  # архив PHP всегда больше 1 МБ
            report.log(f"  ✗ слишком маленький файл ({downloaded} байт) - пропускаю")
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(destination)
        size_mb = destination.stat().st_size / 1024 / 1024
        report.log(f"  ✓ скачано {size_mb:.1f} МБ (из {total or size_mb:.0f})")
        return True
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        report.log(f"  ✗ не удалось: {type(exc).__name__}: {exc}")
        tmp.unlink(missing_ok=True)
        return False


def _extract(archive: Path, target: Path, report: InstallReport) -> bool:
    try:
        target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:*") as tar:
            try:
                tar.extractall(target, filter="tar")  # Python 3.12+
            except TypeError:
                tar.extractall(target)  # noqa: S202 - архив из доверенного источника
        return True
    except (tarfile.TarError, OSError) as exc:
        report.log(f"  ✗ архив не распакован: {exc}")
        return False


# ------------------------------------------------------------------ установка PHP
def install_php_sync(cfg: Config, report: InstallReport, force: bool = False) -> InstallReport:
    cfg.ensure_dirs()
    php_root = cfg.php_dir

    # 1. уже установлено
    if not force:
        existing = find_php_binary(php_root)
        if existing:
            version, pthreads = probe_php(existing)
            if version_supported(version):
                report.php_binary = existing
                report.php_version = version
                report.has_pthreads = pthreads
                report.php_ini = php_ini_for(existing)
                report.ok = True
                report.log(f"PHP {version} уже установлен (pthreads: {'да' if pthreads else 'нет'})")
                return report
            report.log(f"Найденный PHP не подходит (версия '{version or '?'}'), переустанавливаю")

    # 2. внешний бинарник
    if cfg.php_binary_path:
        candidate = Path(cfg.php_binary_path)
        if candidate.is_file():
            version, pthreads = probe_php(candidate)
            if version_supported(version):
                report.php_binary = candidate
                report.php_version = version
                report.has_pthreads = pthreads
                report.php_ini = php_ini_for(candidate)
                report.ok = True
                report.log(f"Использую указанный PHP_BINARY_PATH: PHP {version}")
                return report
            report.log(f"PHP_BINARY_PATH не подходит (версия '{version or '?'}')")

    # порядок версий: сначала желаемая, затем остальные совместимые
    versions = [cfg.php_version] + [v for v in SUPPORTED_PHP if v != cfg.php_version]

    # 3. локальные архивы (оффлайн-режим)
    local_archives = sorted(cfg.cache_dir.glob("*.tar.gz")) + sorted(cfg.cache_dir.glob("*.tgz"))
    for archive in local_archives:
        report.log(f"Найден локальный архив PHP: {archive.name}")
        staging = cfg.base_dir / "runtime" / "php_staging"
        shutil.rmtree(staging, ignore_errors=True)
        if not _extract(archive, staging, report):
            continue
        binary = find_php_binary(staging)
        if not binary:
            report.log("  ✗ в архиве нет bin/php")
            continue
        version, pthreads = probe_php(binary)
        if not version_supported(version):
            report.log(f"  ✗ версия {version or '?'} не поддерживается (нужно 7.0-7.2)")
            continue
        shutil.rmtree(php_root, ignore_errors=True)
        php_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(php_root))
        binary = find_php_binary(php_root)
        report.php_binary = binary
        report.php_version = version
        report.has_pthreads = pthreads
        report.php_ini = php_ini_for(binary) if binary else None
        report.ok = binary is not None
        report.log(f"  ✓ установлен PHP {version} из локального архива")
        return report

    # 4. скачивание
    urls: list[str] = []
    if cfg.php_binary_url:
        urls.append(cfg.php_binary_url)
    for version in versions:
        urls.extend(php_mirrors(version, cfg.arch))

    for url in urls:
        report.log(f"Скачиваю PHP: {url}")
        archive = cfg.cache_dir / "php-download.tar.gz"
        archive.unlink(missing_ok=True)
        if not _download(url, archive, report):
            continue
        staging = cfg.base_dir / "runtime" / "php_staging"
        shutil.rmtree(staging, ignore_errors=True)
        if not _extract(archive, staging, report):
            continue
        binary = find_php_binary(staging)
        if not binary:
            report.log("  ✗ в архиве нет bin/php")
            continue
        version, pthreads = probe_php(binary)
        if not version_supported(version):
            report.log(f"  ✗ версия {version or '?'} не подходит (нужно 7.0-7.2)")
            continue
        shutil.rmtree(php_root, ignore_errors=True)
        shutil.move(str(staging), str(php_root))
        binary = find_php_binary(php_root)
        # сохраняем архив в кеш, чтобы переустановка работала без интернета
        try:
            archive.replace(cfg.cache_dir / f"PHP-{version}-{cfg.arch}.tar.gz")
        except OSError:
            pass
        report.php_binary = binary
        report.php_version = version
        report.has_pthreads = pthreads
        report.php_ini = php_ini_for(binary) if binary else None
        report.ok = binary is not None
        report.log(f"  ✓ установлен PHP {version} (pthreads: {'да' if pthreads else 'нет'})")
        return report

    # 5. сборка из исходников
    if cfg.allow_php_build and shutil.which("git") and shutil.which("make"):
        report.log("Готовые бинарники недоступны - собираю PHP из исходников (до 40 минут)")
        if build_php_from_source(cfg, report):
            binary = find_php_binary(php_root)
            if binary:
                version, pthreads = probe_php(binary)
                report.php_binary = binary
                report.php_version = version
                report.has_pthreads = pthreads
                report.php_ini = php_ini_for(binary)
                report.ok = version_supported(version)
                report.log(f"  ✓ собран PHP {version}")
                return report

    report.ok = False
    report.log(
        "✗ PHP не установлен. Решение: положите архив PHP-7.2-Linux-x86_64.tar.gz "
        "в папку php_cache/ или укажите PHP_BINARY_URL в .env, затем /install"
    )
    return report


def build_php_from_source(cfg: Config, report: InstallReport) -> bool:
    work = cfg.base_dir / "runtime" / "php-build"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    repo = "https://github.com/pmmp/php-build-scripts.git"
    cloned = False
    for ref in BUILD_SCRIPT_REFS:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, repo, str(work / "scripts")],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            report.log(f"  ✓ php-build-scripts ({ref})")
            cloned = True
            break
    if not cloned:
        report.log("  ✗ не удалось скачать php-build-scripts")
        return False

    script_dir = work / "scripts"
    compile_sh = script_dir / "compile.sh"
    if not compile_sh.is_file():
        report.log("  ✗ в репозитории нет compile.sh")
        return False
    compile_sh.chmod(0o755)
    jobs = str(max(1, (os.cpu_count() or 2)))
    result = subprocess.run(
        ["bash", str(compile_sh), "-t", "linux64", "-j", jobs, "-f"],
        cwd=script_dir,
        capture_output=True,
        text=True,
        timeout=7200,
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-500:]
        report.log(f"  ✗ сборка завершилась с ошибкой: {tail}")
        return False
    built = script_dir / "bin"
    if not built.is_dir():
        report.log("  ✗ сборка не создала папку bin/")
        return False
    shutil.rmtree(cfg.php_dir, ignore_errors=True)
    cfg.php_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(built, cfg.php_dir / "bin", dirs_exist_ok=True)
    return True


# ----------------------------------------------------------- настройка сервера
def configure_server(cfg: Config, report: InstallReport, overwrite: bool = False) -> None:
    cfg.ensure_dirs()
    phar = cfg.phar_file
    if not phar.is_file():
        report.log(f"✗ Не найден {phar.name}: положите GenisysPro.phar в папку server/")
    else:
        head = phar.open("rb").read(120)
        if b"<?php" not in head:
            report.log("⚠ Файл ядра не похож на phar - сервер может не запуститься")
        else:
            size_mb = phar.stat().st_size / 1024 / 1024
            report.log(f"Ядро: {phar.name} ({size_mb:.1f} МБ, MCPE 1.1.0-1.1.5, protocol 113)")

    props_path = cfg.properties_file
    if overwrite or not props_path.exists():
        write_properties(
            props_path,
            default_properties(
                motd=cfg.motd,
                port=cfg.server_port,
                server_ip=cfg.server_ip,
                max_players=cfg.max_players,
                gamemode=cfg.gamemode,
                difficulty=cfg.difficulty,
                level_name=cfg.level_name,
                level_seed=cfg.level_seed,
                level_type=cfg.level_type,
                whitelist=cfg.whitelist,
                pvp=cfg.pvp,
                view_distance=cfg.view_distance,
                language=cfg.language,
            ),
        )
        report.log(f"server.properties создан (порт {cfg.server_port}, игроков {cfg.max_players})")
    else:
        current = read_properties(props_path)
        report.log(f"server.properties уже настроен (порт {current.get('server-port', '?')})")

    yml_path = cfg.server_dir / "pocketmine.yml"
    if overwrite or not yml_path.exists():
        yml_path.write_text(DEFAULT_POCKETMINE_YML.format(language=cfg.language), "utf-8")
        report.log("pocketmine.yml создан (автообновления и телеметрия отключены)")

    for name in ("ops.txt", "white-list.txt", "banned-players.txt", "banned-ips.txt"):
        path = cfg.server_dir / name
        if not path.exists():
            path.write_text("", "utf-8")


async def full_install(cfg: Config, force_php: bool = False, overwrite_config: bool = False) -> InstallReport:
    report = InstallReport()
    report.log("── Автоустановка ──")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, install_php_sync, cfg, report, force_php)
    await loop.run_in_executor(None, configure_server, cfg, report, overwrite_config)
    return report
