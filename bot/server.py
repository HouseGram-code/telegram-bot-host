"""Менеджер процесса сервера GenisysPro: старт/стоп/консоль/логи/игроки."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import time
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from .config import Config
from .installer import find_php_binary, php_ini_for, probe_php
from .props import read_properties

log = logging.getLogger("server")

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
JOIN_RE = re.compile(r"([A-Za-z0-9_\- ]{1,32})\[/[\d.:]+\] logged in", re.IGNORECASE)
JOIN_RE_RU = re.compile(r"([A-Za-z0-9_\- ]{1,32})\[/[\d.:]+\] вошел", re.IGNORECASE)
QUIT_RE = re.compile(r"([A-Za-z0-9_\- ]{1,32}) logged out", re.IGNORECASE)
QUIT_RE_RU = re.compile(r"([A-Za-z0-9_\- ]{1,32}) вышел", re.IGNORECASE)
DONE_RE = re.compile(r"Done \(|Загружено за|For help, type", re.IGNORECASE)


class ServerManager:
    def __init__(self, cfg: Config, on_line: Callable[[str], Awaitable[None]] | None = None):
        self.cfg = cfg
        self.on_line = on_line
        self.process: asyncio.subprocess.Process | None = None
        self.lines: deque[str] = deque(maxlen=cfg.log_lines)
        self.players: set[str] = set()
        self.started_at: float = 0.0
        self.ready: bool = False
        self.last_error: str = ""
        self._reader_task: asyncio.Task | None = None
        self._log_file: Path | None = None
        self._capture: list[str] | None = None

    # ----------------------------------------------------------------- статус
    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def uptime(self) -> str:
        if not self.is_running or not self.started_at:
            return "-"
        seconds = int(time.time() - self.started_at)
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}ч {minutes}м"
        if minutes:
            return f"{minutes}м {secs}с"
        return f"{secs}с"

    @property
    def port(self) -> int:
        props = read_properties(self.cfg.properties_file)
        try:
            return int(props.get("server-port", self.cfg.server_port))
        except ValueError:
            return self.cfg.server_port

    def memory_usage_mb(self) -> float:
        if not self.is_running or self.process is None:
            return 0.0
        try:
            status = Path(f"/proc/{self.process.pid}/status").read_text("utf-8")
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
        except (OSError, ValueError, IndexError):
            pass
        return 0.0

    # ------------------------------------------------------------------ запуск
    def php_command(self) -> tuple[list[str], dict[str, str]] | None:
        binary = None
        if self.cfg.php_binary_path and Path(self.cfg.php_binary_path).is_file():
            binary = Path(self.cfg.php_binary_path)
        if binary is None:
            binary = find_php_binary(self.cfg.php_dir)
        if binary is None:
            return None
        env = dict(os.environ)
        lib_dir = binary.parent.parent / "lib"
        if lib_dir.is_dir():
            env["LD_LIBRARY_PATH"] = f"{lib_dir}:{env.get('LD_LIBRARY_PATH', '')}".rstrip(":")
        env.setdefault("TERM", "dumb")
        cmd = [str(binary)]
        ini = php_ini_for(binary)
        if ini:
            cmd += ["-c", str(ini)]
        cmd += [
            "-d", f"memory_limit={self.cfg.memory_limit}",
            "-d", "error_reporting=E_ALL & ~E_DEPRECATED",
            str(self.cfg.phar_file),
            "--no-wizard",
            "--disable-ansi",
        ]
        return cmd, env

    async def start(self) -> tuple[bool, str]:
        if self.is_running:
            return False, "Сервер уже запущен."
        if not self.cfg.phar_file.is_file():
            return False, f"Не найден {self.cfg.phar_file.name} в папке server/."
        command = self.php_command()
        if command is None:
            return False, "PHP 7.0-7.2 не установлен. Запустите /install."
        cmd, env = command
        version, pthreads = probe_php(Path(cmd[0]))
        if not pthreads:
            log.warning("PHP %s без pthreads - сервер может не запуститься", version)

        self.cfg.ensure_dirs()
        self.lines.clear()
        self.players.clear()
        self.ready = False
        self.last_error = ""
        self._log_file = self.cfg.log_dir / f"server-{datetime.now():%Y%m%d}.log"

        log.info("Запуск: %s", " ".join(cmd))
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.cfg.server_dir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        self.started_at = time.time()
        self._reader_task = asyncio.create_task(self._read_output())
        return True, f"Сервер запущен (PHP {version or '?'}, PID {self.process.pid})."

    async def _read_output(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        stream = self.process.stdout
        while True:
            try:
                raw = await stream.readline()
            except (asyncio.LimitOverrunError, ValueError):
                continue
            if not raw:
                break
            line = ANSI_RE.sub("", raw.decode("utf-8", errors="replace")).rstrip("\r\n")
            if not line.strip():
                continue
            self.lines.append(line)
            if self._capture is not None:
                self._capture.append(line)
            self._track(line)
            if self._log_file is not None:
                with contextlib.suppress(OSError):
                    with self._log_file.open("a", encoding="utf-8") as handle:
                        handle.write(line + "\n")
            if self.on_line is not None:
                with contextlib.suppress(Exception):
                    await self.on_line(line)
        code = await self.process.wait() if self.process else -1
        log.info("Процесс сервера завершён, код %s", code)
        self.ready = False
        if self.on_line is not None:
            with contextlib.suppress(Exception):
                await self.on_line(f"__EXIT__ {code}")

    def _track(self, line: str) -> None:
        if DONE_RE.search(line):
            self.ready = True
        for pattern in (JOIN_RE, JOIN_RE_RU):
            match = pattern.search(line)
            if match:
                self.players.add(match.group(1).strip())
        for pattern in (QUIT_RE, QUIT_RE_RU):
            match = pattern.search(line)
            if match:
                self.players.discard(match.group(1).strip())
        lowered = line.lower()
        if "crash" in lowered or "fatal error" in lowered or "pthreads" in lowered and "not" in lowered:
            self.last_error = line

    # ------------------------------------------------------------------- стоп
    async def stop(self, timeout: float = 25.0) -> tuple[bool, str]:
        if not self.is_running or self.process is None:
            return False, "Сервер и так выключен."
        await self.send_command("stop")
        try:
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
            self.ready = False
            return True, "Сервер корректно остановлен (миры сохранены)."
        except asyncio.TimeoutError:
            pass
        with contextlib.suppress(ProcessLookupError):
            self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=10)
            return True, "Сервер остановлен (SIGTERM)."
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                self.process.kill()
            return True, "Сервер принудительно завершён (SIGKILL)."

    async def restart(self) -> tuple[bool, str]:
        if self.is_running:
            await self.stop()
            await asyncio.sleep(2)
        return await self.start()

    # ---------------------------------------------------------------- команды
    async def send_command(self, command: str) -> bool:
        if not self.is_running or self.process is None or self.process.stdin is None:
            return False
        try:
            self.process.stdin.write((command.strip() + "\n").encode("utf-8"))
            await self.process.stdin.drain()
            return True
        except (BrokenPipeError, ConnectionResetError, RuntimeError):
            return False

    async def command_with_output(self, command: str, wait: float = 1.8) -> list[str]:
        """Отправляет команду и собирает ответ консоли."""
        self._capture = []
        sent = await self.send_command(command)
        if not sent:
            self._capture = None
            return []
        await asyncio.sleep(wait)
        captured = self._capture or []
        self._capture = None
        return captured

    def tail(self, count: int = 30) -> list[str]:
        return list(self.lines)[-count:]

    # ----------------------------------------------------------------- бэкап
    def create_backup_sync(self) -> Path:
        self.cfg.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archive = self.cfg.backup_dir / f"backup-{stamp}.zip"
        targets: list[Path] = []
        for name in ("worlds", "players", "plugins"):
            path = self.cfg.server_dir / name
            if path.is_dir():
                targets.append(path)
        files = [
            self.cfg.server_dir / "server.properties",
            self.cfg.server_dir / "pocketmine.yml",
            self.cfg.server_dir / "ops.txt",
            self.cfg.server_dir / "white-list.txt",
        ]
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for directory in targets:
                for item in directory.rglob("*"):
                    if item.is_file():
                        zf.write(item, item.relative_to(self.cfg.server_dir))
            for item in files:
                if item.is_file():
                    zf.write(item, item.name)
        return archive

    async def create_backup(self) -> Path:
        if self.is_running:
            await self.send_command("save-all")
            await asyncio.sleep(2)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.create_backup_sync)

    def plugin_list(self) -> list[str]:
        plugins_dir = self.cfg.server_dir / "plugins"
        if not plugins_dir.is_dir():
            return []
        return sorted(p.name for p in plugins_dir.iterdir() if p.suffix in {".phar", ".zip"} or p.is_dir())

    def disk_usage(self) -> str:
        try:
            usage = shutil.disk_usage(self.cfg.base_dir)
            return f"{usage.used / 2**30:.1f}/{usage.total / 2**30:.1f} ГБ"
        except OSError:
            return "-"
