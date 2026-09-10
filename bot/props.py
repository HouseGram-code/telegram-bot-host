"""Чтение/запись server.properties (формат PocketMine/GenisysPro)."""

from __future__ import annotations

from pathlib import Path


def read_properties(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def write_properties(path: Path, values: dict[str, str], header: str = "#Properties Config file") -> None:
    lines = [header]
    for key, value in values.items():
        lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", "utf-8")


def update_properties(path: Path, changes: dict[str, str | int | bool]) -> dict[str, str]:
    """Обновляет отдельные ключи, сохраняя остальные значения и порядок."""
    current = read_properties(path)
    for key, value in changes.items():
        if isinstance(value, bool):
            current[key] = "on" if value else "off"
        else:
            current[key] = str(value)
    write_properties(path, current)
    return current


def default_properties(
    *,
    motd: str,
    port: int,
    server_ip: str,
    max_players: int,
    gamemode: int,
    difficulty: int,
    level_name: str,
    level_seed: str,
    level_type: str,
    whitelist: bool,
    pvp: bool,
    view_distance: int,
    language: str,
) -> dict[str, str]:
    """Готовый набор свойств для MCPE 1.1.x (без xbox-auth, с открытым query)."""
    return {
        "motd": motd,
        "server-name": motd,
        "sub-motd": "powered by Telegram bot",
        "server-ip": server_ip,
        "server-port": str(port),
        "white-list": "on" if whitelist else "off",
        "announce-player-achievements": "on",
        "spawn-protection": "16",
        "max-players": str(max_players),
        "allow-flight": "off",
        "spawn-animals": "on",
        "spawn-mobs": "on",
        "gamemode": str(gamemode),
        "force-gamemode": "off",
        "hardcore": "off",
        "pvp": "on" if pvp else "off",
        "difficulty": str(difficulty),
        "generator-settings": "",
        "level-name": level_name,
        "level-seed": level_seed,
        "level-type": level_type,
        "enable-query": "on",
        "enable-rcon": "off",
        "rcon.password": "",
        "auto-save": "on",
        "view-distance": str(view_distance),
        "xbox-auth": "off",
        "online-mode": "false",
        "language": language,
        "force-resources": "off",
        "hardcore-mode": "off",
        "time-update": "on",
        "async-chunk-request": "on",
    }


DEFAULT_POCKETMINE_YML = """# pocketmine.yml - сгенерировано телеграм-ботом для GenisysPro (MCPE 1.1.x)
settings:
  language: "{language}"
  force-language: false
  shutdown-message: "Сервер выключен"
  query-plugins: true
  deprecated-verbose: false
  enable-profiling: false
  profile-report-trigger: 20
  async-workers: "auto"
  upnp-forwarding: false
  send-usage: false
memory:
  global-limit: 0
  main-limit: 0
  main-hard-limit: 1024
  check-rate: 20
  continuous-trigger: true
  continuous-trigger-rate: 30
  garbage-collection:
    period: 36000
    collect-async-worker: true
    low-memory-trigger: true
  max-chunks:
    trigger-limit: 96
    low-memory-trigger: true
network:
  batch-threshold: 256
  compression-level: 6
  async-compression: false
  upnp-forwarding: false
  max-mtu-size: 1492
debug:
  level: 1
  commands: false
level-settings:
  default-format: mcregion
  convert-format: false
  auto-tick-rate: true
  auto-tick-rate-limit: 20
  base-tick-rate: 1
  always-tick-players: false
chunk-sending:
  per-tick: 4
  max-chunks: 192
  spawn-radius: 4
  cache-chunks: false
chunk-ticking:
  per-tick: 40
  tick-radius: 3
  light-updates: false
  clear-tick-list: true
chunk-generation:
  queue-size: 8
  population-queue-size: 8
ticks-per:
  animal-spawns: 400
  monster-spawns: 1
  autosave: 6000
  cache-cleanup: 900
spawn-limits:
  monsters: 70
  animals: 15
  water-animals: 5
  ambient: 15
auto-report:
  enabled: false
auto-updater:
  enabled: false
  on-update:
    warn-console: false
anonymous-statistics:
  enabled: false
players:
  save-player-data: true
aliases: {{}}
worlds: {{}}
plugins: {{}}
"""
