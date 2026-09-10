"""Определение реальных рабочих адресов сервера: локальный, LAN, публичный."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
import subprocess

import aiohttp

log = logging.getLogger("net")

PUBLIC_IP_ENDPOINTS = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://ipv4.icanhazip.com",
)


def lan_ip() -> str:
    """IP в локальной сети (тот, который вводят на телефоне в Wi-Fi)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1.0)
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        pass
    for candidate in all_ipv4():
        if candidate.startswith(("192.168.", "10.", "172.")):
            return candidate
    return "127.0.0.1"


def all_ipv4() -> list[str]:
    found: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if not value or value in found:
            return
        try:
            addr = ipaddress.ip_address(value)
        except ValueError:
            return
        if addr.version == 4 and not addr.is_loopback and not addr.is_link_local:
            found.append(value)

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass

    try:
        output = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            capture_output=True,
            text=True,
            timeout=4,
        ).stdout
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 4 and "/" in parts[3]:
                add(parts[3].split("/")[0])
    except (OSError, subprocess.SubprocessError):
        pass

    return found


def docker_host_hint() -> str:
    """Адрес хоста, если бот работает внутри контейнера."""
    if not (os.path.exists("/.dockerenv") or os.environ.get("IN_DOCKER")):
        return ""
    for host in ("host.docker.internal", "gateway.docker.internal"):
        try:
            return socket.gethostbyname(host)
        except OSError:
            continue
    try:
        output = subprocess.run(
            ["ip", "route", "show", "default"], capture_output=True, text=True, timeout=4
        ).stdout.split()
        if "via" in output:
            return output[output.index("via") + 1]
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return ""


async def public_ip(session: aiohttp.ClientSession | None = None, timeout: float = 6.0) -> str:
    own_session = session is None
    session = session or aiohttp.ClientSession()
    try:
        for url in PUBLIC_IP_ENDPOINTS:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status != 200:
                        continue
                    value = (await resp.text()).strip()
                    ipaddress.ip_address(value)
                    return value
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                continue
    finally:
        if own_session:
            await session.close()
    return ""


def port_is_free(port: int, proto: str = "udp") -> bool:
    family = socket.SOCK_DGRAM if proto == "udp" else socket.SOCK_STREAM
    try:
        with socket.socket(socket.AF_INET, family) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False


def pick_free_port(preferred: int, attempts: int = 20) -> int:
    """Возвращает свободный UDP-порт: сначала желаемый, потом соседние."""
    if port_is_free(preferred):
        return preferred
    for offset in range(1, attempts + 1):
        candidate = preferred + offset
        if candidate <= 65535 and port_is_free(candidate):
            return candidate
    return preferred
