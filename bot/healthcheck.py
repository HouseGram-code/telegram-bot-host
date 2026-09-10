"""Healthcheck для Docker: проверяет, что сервер MCPE отвечает по RakNet.

Выход 0 - всё в порядке (сервер отвечает или намеренно остановлен),
выход 1 - сервер должен работать, но не отвечает.
"""

from __future__ import annotations

import sys

from .config import Config
from .props import read_properties
from .raknet import ping_sync


def main() -> int:
    cfg = Config.load()
    props = read_properties(cfg.properties_file)
    try:
        port = int(props.get("server-port", cfg.server_port))
    except ValueError:
        port = cfg.server_port

    marker = cfg.data_dir / "server-should-run"
    result = ping_sync("127.0.0.1", port, timeout=3.0)
    if result is not None:
        print(f"ok: {result.motd} {result.online}/{result.max_players} protocol={result.protocol}")
        return 0
    if not marker.exists():
        print("ok: сервер остановлен вручную")
        return 0
    print(f"fail: нет ответа на UDP {port}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
