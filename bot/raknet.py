"""RakNet UNCONNECTED_PING - проверка, что сервер MCPE реально отвечает.

Используется для /status, /ip и healthcheck Docker: если пинг вернул
ответ, значит адрес и порт рабочие, а клиент 1.1.x увидит сервер.
"""

from __future__ import annotations

import asyncio
import socket
import struct
import time
from dataclasses import dataclass

MAGIC = bytes.fromhex("00ffff00fefefefefdfdfdfd12345678")
ID_UNCONNECTED_PING = 0x01
ID_UNCONNECTED_PONG = 0x1C


@dataclass(slots=True)
class PingResult:
    host: str
    port: int
    latency_ms: float
    motd: str = ""
    protocol: int = 0
    version: str = ""
    online: int = 0
    max_players: int = 0
    edition: str = ""
    raw: str = ""


def _parse_pong(payload: bytes, host: str, port: int, latency_ms: float) -> PingResult:
    result = PingResult(host=host, port=port, latency_ms=latency_ms)
    # 1 (id) + 8 (time) + 8 (server guid) + 16 (magic) + 2 (len) + data
    if len(payload) < 35:
        return result
    length = struct.unpack(">H", payload[33:35])[0]
    raw = payload[35:35 + length].decode("utf-8", errors="replace")
    result.raw = raw
    parts = raw.split(";")
    # MCPE;MOTD;protocol;version;online;max;serverId;sub-motd;gamemode
    if len(parts) >= 1:
        result.edition = parts[0]
    if len(parts) >= 2:
        result.motd = parts[1]
    if len(parts) >= 3 and parts[2].isdigit():
        result.protocol = int(parts[2])
    if len(parts) >= 4:
        result.version = parts[3]
    if len(parts) >= 5 and parts[4].isdigit():
        result.online = int(parts[4])
    if len(parts) >= 6 and parts[5].isdigit():
        result.max_players = int(parts[5])
    return result


def ping_sync(host: str = "127.0.0.1", port: int = 19132, timeout: float = 2.0) -> PingResult | None:
    packet = (
        bytes([ID_UNCONNECTED_PING])
        + struct.pack(">q", int(time.time() * 1000) & 0x7FFFFFFFFFFFFFFF)
        + MAGIC
        + struct.pack(">q", 0x1234567890ABCDEF - 0x1000000000000000)
    )
    started = time.perf_counter()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(packet, (host, port))
            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                data, _ = sock.recvfrom(4096)
                if data and data[0] == ID_UNCONNECTED_PONG:
                    latency = (time.perf_counter() - started) * 1000
                    return _parse_pong(data, host, port, latency)
    except (OSError, socket.timeout):
        return None
    return None


async def ping(host: str = "127.0.0.1", port: int = 19132, timeout: float = 2.0) -> PingResult | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, ping_sync, host, port, timeout)
