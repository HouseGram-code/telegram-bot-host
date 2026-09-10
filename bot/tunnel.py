"""Временный публичный адрес для UDP-порта сервера (playit.gg agent).

Нужен, когда нет возможности прокинуть порт на роутере: даёт временный
адрес вида xxx.playit.gg:12345, который работает с телефонов и ПК.
Функция опциональная: ENABLE_TUNNEL=1 в .env.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import stat
import urllib.error
import urllib.request
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger("tunnel")

AGENT_URLS = {
    "x86_64": "https://github.com/playit-cloud/playit-agent/releases/latest/download/playit-linux-amd64",
    "aarch64": "https://github.com/playit-cloud/playit-agent/releases/latest/download/playit-linux-aarch64",
    "armv7": "https://github.com/playit-cloud/playit-agent/releases/latest/download/playit-linux-armv7",
}

CLAIM_RE = re.compile(r"https://playit\.gg/[^\s\"']+")
ADDRESS_RE = re.compile(r"([a-z0-9\-]+\.(?:playit\.gg|joinmc\.link|craft\.ply\.gg|ply\.gg)(?::\d+)?)", re.IGNORECASE)


class Tunnel:
    def __init__(self, base_dir: Path, arch: str, secret: str = ""):
        self.base_dir = base_dir
        self.arch = arch
        self.secret = secret
        self.binary = base_dir / "runtime" / "playit"
        self.process: asyncio.subprocess.Process | None = None
        self.address: str = ""
        self.claim_url: str = ""
        self.lines: list[str] = []

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    def download_sync(self) -> bool:
        url = AGENT_URLS.get(self.arch)
        if not url:
            return False
        self.binary.parent.mkdir(parents=True, exist_ok=True)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "mcpe-telegram-host"})
            with urllib.request.urlopen(request, timeout=90) as resp, self.binary.open("wb") as handle:
                while True:
                    block = resp.read(256 * 1024)
                    if not block:
                        break
                    handle.write(block)
            self.binary.chmod(self.binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)
            return True
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            log.warning("Не удалось скачать playit-agent: %s", exc)
            return False

    async def start(self, on_event: Callable[[str], Awaitable[None]] | None = None) -> tuple[bool, str]:
        if self.is_running:
            return True, self.address or "Туннель уже запущен"
        if not self.binary.is_file():
            loop = asyncio.get_running_loop()
            if not await loop.run_in_executor(None, self.download_sync):
                return False, "Не удалось скачать playit-agent (нужен интернет)."
        env = dict(os.environ)
        args = [str(self.binary)]
        if self.secret:
            env["SECRET_KEY"] = self.secret
            args += ["--secret", self.secret]
        try:
            self.process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=str(self.base_dir / "runtime"),
            )
        except OSError as exc:
            return False, f"Туннель не запустился: {exc}"
        asyncio.create_task(self._read(on_event))
        return True, "Туннель запущен, ждём адрес..."

    async def _read(self, on_event: Callable[[str], Awaitable[None]] | None) -> None:
        assert self.process is not None and self.process.stdout is not None
        while True:
            raw = await self.process.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            self.lines.append(line)
            del self.lines[:-200]
            claim = CLAIM_RE.search(line)
            if claim and not self.claim_url:
                self.claim_url = claim.group(0)
                if on_event:
                    await on_event(
                        "Для активации временного публичного адреса откройте ссылку: "
                        f"{self.claim_url}"
                    )
            address = ADDRESS_RE.search(line)
            if address:
                found = address.group(1)
                if found != self.address:
                    self.address = found
                    if on_event:
                        await on_event(f"Временный публичный адрес готов: {found}")
        log.info("playit-agent завершён")

    async def stop(self) -> None:
        if self.process is not None and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=10)
            except asyncio.TimeoutError:
                self.process.kill()
        self.address = ""
