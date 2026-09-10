"""Конфигурация бота и путей проекта.

Все значения читаются из переменных окружения (.env), для всего есть
разумные значения по умолчанию, поэтому бот работает "из коробки".
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from pathlib import Path

TRUE_VALUES = {"1", "true", "yes", "on", "y", "да", "вкл", "enable", "enabled"}

# Версии PHP, которые совместимы с GenisysPro (API 3.0.1, MCPE 1.1.x)
SUPPORTED_PHP = ("7.2", "7.1", "7.0")


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return default if value == "" else value


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, "1" if default else "0").lower() in TRUE_VALUES


def env_list(name: str) -> list[str]:
    raw = env(name)
    if not raw:
        return []
    parts = raw.replace(";", ",").replace(" ", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def detect_base_dir() -> Path:
    """Корень данных: /opt/mcpe в Docker, папка проекта при локальном запуске."""
    explicit = env("MCPE_BASE_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if Path("/opt/mcpe/server").exists() or Path("/.dockerenv").exists():
        return Path("/opt/mcpe")
    return Path(__file__).resolve().parent.parent


def detect_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    if machine in {"aarch64", "arm64"}:
        return "aarch64"
    if machine.startswith("armv7") or machine == "armv7l":
        return "armv7"
    return machine or "x86_64"


@dataclass(slots=True)
class Config:
    # --- Telegram ---
    bot_token: str = ""
    admin_ids: list[int] = field(default_factory=list)
    open_claim: bool = True  # первый, кто напишет /start, становится владельцем

    # --- пути ---
    base_dir: Path = field(default_factory=detect_base_dir)

    # --- PHP ---
    php_version: str = "7.2"
    php_binary_url: str = ""
    php_binary_path: str = ""
    allow_php_build: bool = True
    arch: str = field(default_factory=detect_arch)

    # --- сервер Minecraft PE ---
    server_ip: str = "0.0.0.0"
    server_port: int = 19132
    motd: str = "GenisysPro 1.1.5 | Telegram Host"
    max_players: int = 20
    gamemode: int = 0
    difficulty: int = 2
    level_name: str = "world"
    level_seed: str = ""
    level_type: str = "DEFAULT"
    whitelist: bool = False
    pvp: bool = True
    view_distance: int = 8
    language: str = "rus"
    memory_limit: str = "-1"

    # --- поведение ---
    auto_install: bool = True
    auto_start: bool = True
    console_stream: bool = False
    log_lines: int = 400
    backup_max_mb: int = 45

    # --- сеть / публичный адрес ---
    public_host: str = ""
    show_public_ip: bool = True
    enable_tunnel: bool = False
    playit_secret: str = ""

    @classmethod
    def load(cls) -> "Config":
        cfg = cls(
            bot_token=env("BOT_TOKEN") or env("TELEGRAM_BOT_TOKEN"),
            admin_ids=[int(x) for x in env_list("ADMIN_IDS") if x.lstrip("-").isdigit()],
            open_claim=env_bool("OPEN_CLAIM", True),
            php_version=env("PHP_TARGET_VERSION", "7.2"),
            php_binary_url=env("PHP_BINARY_URL"),
            php_binary_path=env("PHP_BINARY_PATH"),
            allow_php_build=env_bool("ALLOW_PHP_BUILD", True),
            server_ip=env("SERVER_IP", "0.0.0.0"),
            server_port=env_int("SERVER_PORT", 19132),
            motd=env("SERVER_MOTD", "GenisysPro 1.1.5 | Telegram Host"),
            max_players=env_int("MAX_PLAYERS", 20),
            gamemode=env_int("GAMEMODE", 0),
            difficulty=env_int("DIFFICULTY", 2),
            level_name=env("LEVEL_NAME", "world"),
            level_seed=env("LEVEL_SEED"),
            level_type=env("LEVEL_TYPE", "DEFAULT"),
            whitelist=env_bool("WHITELIST", False),
            pvp=env_bool("PVP", True),
            view_distance=env_int("VIEW_DISTANCE", 8),
            language=env("SERVER_LANGUAGE", "rus"),
            memory_limit=env("PHP_MEMORY_LIMIT", "-1"),
            auto_install=env_bool("AUTO_INSTALL", True),
            auto_start=env_bool("AUTO_START", True),
            console_stream=env_bool("CONSOLE_STREAM", False),
            log_lines=env_int("LOG_LINES", 400),
            backup_max_mb=env_int("BACKUP_MAX_MB", 45),
            public_host=env("PUBLIC_HOST"),
            show_public_ip=env_bool("SHOW_PUBLIC_IP", True),
            enable_tunnel=env_bool("ENABLE_TUNNEL", False),
            playit_secret=env("PLAYIT_SECRET"),
        )
        if cfg.php_version not in SUPPORTED_PHP:
            cfg.php_version = "7.2"
        return cfg

    # ------------------------------------------------------------------ пути
    @property
    def server_dir(self) -> Path:
        return self.base_dir / "server"

    @property
    def php_dir(self) -> Path:
        return self.base_dir / "runtime" / "php"

    @property
    def cache_dir(self) -> Path:
        return self.base_dir / "php_cache"

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def properties_file(self) -> Path:
        return self.server_dir / "server.properties"

    @property
    def phar_file(self) -> Path:
        custom = env("PHAR_FILE")
        if custom:
            return Path(custom)
        return self.server_dir / "GenisysPro.phar"

    def ensure_dirs(self) -> None:
        for path in (
            self.server_dir,
            self.server_dir / "plugins",
            self.server_dir / "worlds",
            self.server_dir / "players",
            self.php_dir,
            self.cache_dir,
            self.data_dir,
            self.backup_dir,
            self.log_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
