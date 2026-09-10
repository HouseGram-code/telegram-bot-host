"""Основная логика телеграм-бота: меню, команды, автозапуск сервера."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from pathlib import Path

import aiohttp

from .config import Config
from .installer import find_php_binary, full_install, probe_php
from .net import all_ipv4, docker_host_hint, lan_ip, pick_free_port, port_is_free, public_ip
from .props import read_properties, update_properties
from .raknet import ping
from .server import ServerManager
from .state import State
from .tgapi import TelegramAPI, TelegramError, html_escape, inline_keyboard, poll_updates
from .tunnel import Tunnel

log = logging.getLogger("bot")

BOT_COMMANDS = [
    ("start", "Главное меню"),
    ("status", "Статус сервера"),
    ("ip", "Адреса и порт для подключения"),
    ("go", "Запустить сервер"),
    ("stop", "Остановить сервер"),
    ("restart", "Перезапустить сервер"),
    ("players", "Кто онлайн"),
    ("logs", "Последние строки консоли"),
    ("console", "Отправить команду в консоль"),
    ("say", "Сообщение в чат сервера"),
    ("op", "Выдать оператора"),
    ("deop", "Забрать оператора"),
    ("kick", "Выгнать игрока"),
    ("port", "Сменить порт"),
    ("motd", "Сменить название сервера"),
    ("maxplayers", "Максимум игроков"),
    ("gamemode", "Режим игры 0-3"),
    ("difficulty", "Сложность 0-3"),
    ("whitelist", "Вкл/выкл вайтлист"),
    ("plugins", "Список плагинов"),
    ("backup", "Создать бэкап миров"),
    ("install", "Перепроверить установку PHP"),
    ("tunnel", "Временный публичный адрес"),
    ("stream", "Трансляция консоли в чат"),
    ("id", "Мой Telegram ID"),
    ("help", "Справка"),
]


def load_env_file(path: Path) -> None:
    """Простой загрузчик .env для запуска без Docker."""
    if not path.is_file():
        return
    for line in path.read_text("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class BotApp:
    def __init__(self, cfg: Config, api: TelegramAPI, session: aiohttp.ClientSession):
        self.cfg = cfg
        self.api = api
        self.session = session
        self.state = State(cfg.state_file)
        self.manager = ServerManager(cfg, on_line=self._on_server_line)
        self.tunnel = Tunnel(cfg.base_dir, cfg.arch, cfg.playit_secret)
        self.pending: dict[int, str] = {}
        self.stop_event = asyncio.Event()
        self._stream_buffer: list[str] = []
        self._stream_task: asyncio.Task | None = None

    # ------------------------------------------------------------ доступ
    def is_allowed(self, user_id: int) -> bool:
        if user_id in self.cfg.admin_ids:
            return True
        return user_id in self.state.owners

    def admin_chats(self) -> list[int]:
        return sorted(set(self.cfg.admin_ids) | set(self.state.owners))

    # --------------------------------------------------------------- меню
    def main_menu(self) -> dict:
        running = self.manager.is_running
        return inline_keyboard(
            [
                [
                    ("⏹ Остановить", "srv:stop") if running else ("▶️ Запустить", "srv:start"),
                    ("🔄 Рестарт", "srv:restart"),
                ],
                [("📊 Статус", "srv:status"), ("🌐 IP и порт", "srv:ip")],
                [("👥 Игроки", "srv:players"), ("📜 Логи", "srv:logs")],
                [("💾 Бэкап", "srv:backup"), ("🧩 Плагины", "srv:plugins")],
                [("⚙️ Настройки", "menu:settings"), ("🛠 Установка", "srv:install")],
            ]
        )

    def settings_menu(self) -> dict:
        props = read_properties(self.cfg.properties_file)
        whitelist_on = props.get("white-list", "off") == "on"
        return inline_keyboard(
            [
                [("🔌 Порт", "set:port"), ("📝 Название", "set:motd")],
                [("👤 Макс. игроков", "set:maxplayers"), ("🎮 Режим игры", "set:gamemode")],
                [("⚔️ Сложность", "set:difficulty"),
                 (f"📜 Вайтлист: {'вкл' if whitelist_on else 'выкл'}", "set:whitelist")],
                [("🖥 Команда в консоль", "set:console"), ("📡 Туннель", "set:tunnel")],
                [("♻️ Переустановить PHP", "set:reinstall")],
                [("⬅️ Назад", "menu:main")],
            ]
        )

    # ----------------------------------------------------------- запуск бота
    async def startup(self) -> None:
        self.cfg.ensure_dirs()
        report_text = ""
        if self.cfg.auto_install:
            report = await full_install(self.cfg)
            report_text = report.text()
            self.state.set("installed_php", report.php_version)

        # гарантируем рабочий свободный порт
        props = read_properties(self.cfg.properties_file)
        try:
            port = int(props.get("server-port", self.cfg.server_port))
        except ValueError:
            port = self.cfg.server_port
        if not port_is_free(port):
            new_port = pick_free_port(port)
            if new_port != port:
                update_properties(self.cfg.properties_file, {"server-port": new_port})
                log.warning("Порт %s занят, выбран %s", port, new_port)
                port = new_port
        self.state.set("last_port", port)

        start_text = ""
        if self.cfg.auto_start:
            ok, message = await self.manager.start()
            start_text = message
            if ok:
                (self.cfg.data_dir / "server-should-run").touch()
                await self._wait_ready(90)

        if self.cfg.enable_tunnel:
            await self.tunnel.start(self._broadcast_plain)

        addresses = await self.addresses_text()
        greeting = ["<b>🤖 Бот запущен</b>"]
        if report_text:
            greeting.append(f"<b>Установка:</b>\n<pre>{html_escape(report_text)}</pre>")
        if start_text:
            greeting.append(html_escape(start_text))
        greeting.append(addresses)
        for chat_id in self.admin_chats():
            with contextlib.suppress(TelegramError):
                await self.api.send_message(chat_id, "\n\n".join(greeting), reply_markup=self.main_menu())

    async def _wait_ready(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.manager.ready:
                return True
            if not self.manager.is_running:
                return False
            await asyncio.sleep(1.5)
        return self.manager.ready

    # ------------------------------------------------------ трансляция консоли
    async def _on_server_line(self, line: str) -> None:
        if line.startswith("__EXIT__"):
            code = line.split(" ", 1)[-1]
            marker = self.cfg.data_dir / "server-should-run"
            text = f"⚠️ Сервер остановился (код {html_escape(code)})."
            if marker.exists():
                tail = "\n".join(self.manager.tail(12))
                text += f"\n<pre>{html_escape(tail)}</pre>"
            await self._broadcast(text)
            return
        chats = self.state.stream_chats()
        if not chats:
            return
        self._stream_buffer.append(line)
        if self._stream_task is None or self._stream_task.done():
            self._stream_task = asyncio.create_task(self._flush_stream())

    async def _flush_stream(self) -> None:
        await asyncio.sleep(2.5)
        lines, self._stream_buffer = self._stream_buffer[-40:], []
        if not lines:
            return
        text = "<pre>" + html_escape("\n".join(lines)) + "</pre>"
        for chat_id in self.state.stream_chats():
            with contextlib.suppress(TelegramError):
                await self.api.send_message(chat_id, text, disable_notification=True)

    async def _broadcast(self, text: str) -> None:
        for chat_id in self.admin_chats():
            with contextlib.suppress(TelegramError):
                await self.api.send_message(chat_id, text)

    async def _broadcast_plain(self, text: str) -> None:
        await self._broadcast(html_escape(text))

    # ------------------------------------------------------------ тексты
    async def addresses_text(self) -> str:
        port = self.manager.port
        lan = lan_ip()
        lines = [
            "<b>🌐 Адреса для подключения</b> (Minecraft PE / Win10 Edition 1.1.x)",
            f"• На этом ПК: <code>127.0.0.1</code> : <code>{port}</code>",
            f"• Локальная сеть (телефон в том же Wi-Fi): <code>{lan}</code> : <code>{port}</code>",
        ]
        others = [ip for ip in all_ipv4() if ip != lan]
        if others:
            lines.append("• Другие интерфейсы: " + ", ".join(f"<code>{ip}</code>" for ip in others[:4]))
        host_hint = docker_host_hint()
        if host_hint:
            lines.append(f"• Шлюз Docker-хоста: <code>{host_hint}</code> : <code>{port}</code>")
        if self.cfg.public_host:
            lines.append(f"• Свой домен/DDNS: <code>{html_escape(self.cfg.public_host)}</code> : <code>{port}</code>")
        if self.cfg.show_public_ip:
            external = await public_ip(self.session)
            if external:
                lines.append(
                    f"• Внешний IP: <code>{external}</code> : <code>{port}</code> "
                    "(нужен проброс UDP-порта на роутере)"
                )
        if self.tunnel.address:
            lines.append(f"• Временный публичный адрес: <code>{html_escape(self.tunnel.address)}</code>")
        elif self.tunnel.claim_url:
            lines.append(f"• Активация туннеля: {html_escape(self.tunnel.claim_url)}")

        result = await ping("127.0.0.1", port, timeout=2.5)
        if result:
            lines.append(
                f"\n✅ Проверено живым пингом: «{html_escape(result.motd)}», "
                f"{result.online}/{result.max_players} игроков, protocol {result.protocol}, "
                f"отклик {result.latency_ms:.0f} мс"
            )
        else:
            lines.append("\n⚪ Сервер пока не отвечает на пинг (выключен или ещё грузится).")
        lines.append(
            "\n📱 Телефон: Minecraft PE 1.1.x → Играть → Серверы → Добавить сервер\n"
            "💻 Windows 10 Edition 1.1.x → то же меню; для 127.0.0.1 сначала выполните в PowerShell:\n"
            "<code>CheckNetIsolation LoopbackExempt -a -n=Microsoft.MinecraftUWP_8wekyb3d8bbwe</code>"
        )
        return "\n".join(lines)

    async def status_text(self) -> str:
        port = self.manager.port
        props = read_properties(self.cfg.properties_file)
        php_binary = find_php_binary(self.cfg.php_dir)
        php_version, pthreads = probe_php(php_binary) if php_binary else ("", False)
        result = await ping("127.0.0.1", port, timeout=2.0)
        icon = "🟢 работает" if self.manager.is_running else "🔴 остановлен"
        if self.manager.is_running and not self.manager.ready:
            icon = "🟡 загружается"
        lines = [
            "<b>📊 Статус сервера</b>",
            f"Состояние: {icon}",
            f"Ядро: GenisysPro (MCPE 1.1.0–1.1.5, protocol 113)",
            f"PHP: {php_version or 'не установлен'}" + (" + pthreads" if pthreads else " (без pthreads!)" if php_version else ""),
            f"Порт (UDP): <code>{port}</code>",
            f"Название: {html_escape(props.get('motd', '-'))}",
            f"Игроки: {result.online if result else len(self.manager.players)}/{props.get('max-players', '?')}",
            f"Аптайм: {self.manager.uptime}",
            f"Память сервера: {self.manager.memory_usage_mb():.0f} МБ",
            f"Диск: {self.manager.disk_usage()}",
            f"Мир: {html_escape(props.get('level-name', 'world'))}",
            f"Плагины: {len(self.manager.plugin_list())}",
        ]
        if self.manager.last_error:
            lines.append(f"\n⚠️ Последняя ошибка:\n<pre>{html_escape(self.manager.last_error[:400])}</pre>")
        return "\n".join(lines)

    def help_text(self) -> str:
        rows = "\n".join(f"/{name} — {desc}" for name, desc in BOT_COMMANDS)
        return (
            "<b>📖 Справка</b>\n"
            "Бот хостит сервер Minecraft PE / Windows 10 Edition 1.1.x на ядре GenisysPro.\n\n"
            f"{rows}\n\n"
            "Плагин: пришлите в чат файл .phar — бот положит его в plugins/ и предложит рестарт."
        )

    # ------------------------------------------------------------ роутинг
    async def handle_update(self, update: dict) -> None:
        if "message" in update:
            await self._handle_message(update["message"])
        elif "callback_query" in update:
            await self._handle_callback(update["callback_query"])

    async def _handle_message(self, message: dict) -> None:
        chat_id = message.get("chat", {}).get("id")
        user = message.get("from", {})
        user_id = user.get("id")
        if chat_id is None or user_id is None:
            return
        text = (message.get("text") or message.get("caption") or "").strip()

        # первый владелец
        if not self.is_allowed(user_id):
            if not self.admin_chats() and self.cfg.open_claim:
                self.state.add_owner(user_id)
                await self.api.send_message(
                    chat_id,
                    f"✅ Вы владелец бота (ID <code>{user_id}</code>).\n"
                    "Добавьте этот ID в ADMIN_IDS в файле .env, чтобы закрепить доступ навсегда.",
                )
            else:
                await self.api.send_message(
                    chat_id,
                    f"⛔ Доступ закрыт. Ваш ID: <code>{user_id}</code>\n"
                    "Добавьте его в ADMIN_IDS в .env и перезапустите бота.",
                )
                return

        if "document" in message:
            await self._handle_document(chat_id, message["document"])
            return

        # ожидание ввода из меню
        pending = self.pending.pop(chat_id, None)
        if pending and text and not text.startswith("/"):
            await self._apply_pending(chat_id, pending, text)
            return

        if not text:
            return
        if not text.startswith("/"):
            await self.api.send_message(chat_id, "Выберите действие:", reply_markup=self.main_menu())
            return

        command, _, argument = text.partition(" ")
        command = command[1:].split("@")[0].lower()
        argument = argument.strip()
        await self._run_command(chat_id, command, argument)

    async def _run_command(self, chat_id: int, command: str, argument: str) -> None:
        if command in {"start", "menu"}:
            await self.api.send_message(
                chat_id,
                "<b>🎮 Хостинг Minecraft PE 1.1.x (GenisysPro)</b>\n"
                "Управляйте сервером кнопками ниже или командой /help.",
                reply_markup=self.main_menu(),
            )
        elif command == "help":
            await self.api.send_message(chat_id, self.help_text(), reply_markup=self.main_menu())
        elif command == "id":
            await self.api.send_message(chat_id, f"Ваш Telegram ID: <code>{chat_id}</code>")
        elif command in {"go", "startserver", "run"}:
            await self._do_start(chat_id)
        elif command == "stop":
            await self._do_stop(chat_id)
        elif command == "restart":
            await self._do_restart(chat_id)
        elif command == "status":
            await self.api.send_message(chat_id, await self.status_text(), reply_markup=self.main_menu())
        elif command in {"ip", "address", "addr"}:
            await self.api.send_message(chat_id, await self.addresses_text(), reply_markup=self.main_menu())
        elif command == "players":
            await self._do_players(chat_id)
        elif command in {"logs", "log"}:
            count = int(argument) if argument.isdigit() else 30
            await self._do_logs(chat_id, count)
        elif command in {"console", "cmd"}:
            if not argument:
                self.pending[chat_id] = "console"
                await self.api.send_message(chat_id, "Введите команду сервера (без /), например <code>list</code>:")
            else:
                await self._do_console(chat_id, argument)
        elif command == "say":
            if argument:
                await self._do_console(chat_id, f"say {argument}")
            else:
                await self.api.send_message(chat_id, "Формат: <code>/say привет всем</code>")
        elif command in {"op", "deop", "kick"}:
            if argument:
                await self._do_console(chat_id, f"{command} {argument}")
            else:
                await self.api.send_message(chat_id, f"Формат: <code>/{command} Ник</code>")
        elif command == "port":
            if argument.isdigit():
                await self._set_port(chat_id, int(argument))
            else:
                self.pending[chat_id] = "port"
                await self.api.send_message(chat_id, "Введите новый порт (1024–65535), обычно 19132:")
        elif command == "motd":
            if argument:
                await self._set_props(chat_id, {"motd": argument, "server-name": argument}, f"Название: {argument}")
            else:
                self.pending[chat_id] = "motd"
                await self.api.send_message(chat_id, "Введите новое название сервера:")
        elif command == "maxplayers":
            if argument.isdigit():
                await self._set_props(chat_id, {"max-players": argument}, f"Максимум игроков: {argument}")
            else:
                self.pending[chat_id] = "maxplayers"
                await self.api.send_message(chat_id, "Введите максимальное число игроков:")
        elif command == "gamemode":
            if argument in {"0", "1", "2", "3"}:
                await self._set_props(chat_id, {"gamemode": argument}, f"Режим игры: {argument}")
            else:
                await self.api.send_message(chat_id, "Формат: <code>/gamemode 0</code> (0 выживание, 1 креатив, 2 приключение, 3 наблюдатель)")
        elif command == "difficulty":
            if argument in {"0", "1", "2", "3"}:
                await self._set_props(chat_id, {"difficulty": argument}, f"Сложность: {argument}")
            else:
                await self.api.send_message(chat_id, "Формат: <code>/difficulty 2</code>")
        elif command == "whitelist":
            props = read_properties(self.cfg.properties_file)
            new_value = "off" if props.get("white-list", "off") == "on" else "on"
            await self._set_props(chat_id, {"white-list": new_value}, f"Вайтлист: {new_value}")
        elif command == "setprop":
            key, _, value = argument.partition(" ")
            if key:
                await self._set_props(chat_id, {key: value.strip()}, f"{key} = {value.strip()}")
            else:
                await self.api.send_message(chat_id, "Формат: <code>/setprop pvp off</code>")
        elif command == "plugins":
            plugins = self.manager.plugin_list()
            body = "\n".join(f"• {html_escape(name)}" for name in plugins) or "Плагинов нет."
            await self.api.send_message(
                chat_id,
                f"<b>🧩 Плагины ({len(plugins)})</b>\n{body}\n\nПришлите .phar файлом, чтобы установить.",
            )
        elif command == "backup":
            await self._do_backup(chat_id)
        elif command in {"install", "reinstall"}:
            await self._do_install(chat_id, force=command == "reinstall")
        elif command == "tunnel":
            await self._do_tunnel(chat_id)
        elif command == "stream":
            enabled = not self.state.stream_enabled(chat_id)
            self.state.set_stream(chat_id, enabled)
            await self.api.send_message(
                chat_id, f"Трансляция консоли: {'включена' if enabled else 'выключена'}"
            )
        else:
            await self.api.send_message(chat_id, "Неизвестная команда. /help — список команд.")

    # -------------------------------------------------------------- действия
    async def _do_start(self, chat_id: int) -> None:
        if self.manager.is_running:
            await self.api.send_message(chat_id, "Сервер уже работает.", reply_markup=self.main_menu())
            return
        await self.api.send_message(chat_id, "⏳ Запускаю сервер...")
        ok, message = await self.manager.start()
        if not ok:
            await self.api.send_message(chat_id, f"❌ {html_escape(message)}", reply_markup=self.main_menu())
            return
        (self.cfg.data_dir / "server-should-run").touch()
        ready = await self._wait_ready(120)
        text = f"✅ {html_escape(message)}" if ready else f"⚠️ {html_escape(message)} Загрузка ещё идёт или есть ошибки."
        tail = "\n".join(self.manager.tail(8))
        if tail:
            text += f"\n<pre>{html_escape(tail)}</pre>"
        text += "\n\n" + await self.addresses_text()
        await self.api.send_message(chat_id, text, reply_markup=self.main_menu())

    async def _do_stop(self, chat_id: int) -> None:
        (self.cfg.data_dir / "server-should-run").unlink(missing_ok=True)
        ok, message = await self.manager.stop()
        await self.api.send_message(
            chat_id, f"{'✅' if ok else 'ℹ️'} {html_escape(message)}", reply_markup=self.main_menu()
        )

    async def _do_restart(self, chat_id: int) -> None:
        await self.api.send_message(chat_id, "🔄 Перезапускаю...")
        ok, message = await self.manager.restart()
        if ok:
            (self.cfg.data_dir / "server-should-run").touch()
            await self._wait_ready(120)
        await self.api.send_message(
            chat_id,
            f"{'✅' if ok else '❌'} {html_escape(message)}\n\n" + await self.addresses_text(),
            reply_markup=self.main_menu(),
        )

    async def _do_players(self, chat_id: int) -> None:
        if not self.manager.is_running:
            await self.api.send_message(chat_id, "Сервер выключен.", reply_markup=self.main_menu())
            return
        captured = await self.manager.command_with_output("list", wait=2.0)
        result = await ping("127.0.0.1", self.manager.port, timeout=2.0)
        parts = ["<b>👥 Игроки</b>"]
        if result:
            parts.append(f"Онлайн: {result.online}/{result.max_players}")
        if self.manager.players:
            parts.append("Отслеженные ники: " + ", ".join(sorted(self.manager.players)))
        if captured:
            parts.append("<pre>" + html_escape("\n".join(captured[-8:])) + "</pre>")
        await self.api.send_message(chat_id, "\n".join(parts), reply_markup=self.main_menu())

    async def _do_logs(self, chat_id: int, count: int) -> None:
        lines = self.manager.tail(max(5, min(count, 80)))
        if not lines:
            await self.api.send_message(chat_id, "Лог пуст (сервер не запускался в этой сессии).")
            return
        await self.api.send_message(chat_id, "<pre>" + html_escape("\n".join(lines)) + "</pre>")

    async def _do_console(self, chat_id: int, command: str) -> None:
        if not self.manager.is_running:
            await self.api.send_message(chat_id, "Сервер выключен — команда не отправлена.")
            return
        captured = await self.manager.command_with_output(command)
        body = html_escape("\n".join(captured[-15:]) or "(без ответа)")
        await self.api.send_message(
            chat_id, f"▶️ <code>{html_escape(command)}</code>\n<pre>{body}</pre>"
        )

    async def _do_backup(self, chat_id: int) -> None:
        await self.api.send_message(chat_id, "💾 Создаю бэкап...")
        archive = await self.manager.create_backup()
        size_mb = archive.stat().st_size / 1024 / 1024
        if size_mb <= self.cfg.backup_max_mb:
            try:
                await self.api.send_document(chat_id, archive, caption=f"Бэкап {size_mb:.1f} МБ")
                return
            except (TelegramError, OSError) as exc:
                log.warning("Не удалось отправить бэкап: %s", exc)
        await self.api.send_message(
            chat_id,
            f"Бэкап готов: <code>{html_escape(str(archive))}</code> ({size_mb:.1f} МБ).\n"
            "Файл слишком большой для Telegram — заберите его из папки data/backups.",
        )

    async def _do_install(self, chat_id: int, force: bool = False) -> None:
        await self.api.send_message(
            chat_id,
            "🛠 Проверяю и ставлю PHP 7.0–7.2 + конфиг сервера...\n"
            "При сборке из исходников это может занять до 40 минут.",
        )
        report = await full_install(self.cfg, force_php=force)
        self.state.set("installed_php", report.php_version)
        icon = "✅" if report.ok else "❌"
        text = f"{icon} <b>Установка завершена</b>\n<pre>{html_escape(report.text())}</pre>"
        await self.api.send_message(chat_id, text, reply_markup=self.main_menu())

    async def _do_tunnel(self, chat_id: int) -> None:
        if self.tunnel.is_running:
            info = self.tunnel.address or self.tunnel.claim_url or "адрес ещё не выдан"
            await self.api.send_message(chat_id, f"📡 Туннель активен: <code>{html_escape(info)}</code>")
            return
        await self.api.send_message(chat_id, "📡 Запускаю временный публичный адрес (playit.gg)...")
        ok, message = await self.tunnel.start(self._broadcast_plain)
        await self.api.send_message(chat_id, f"{'✅' if ok else '❌'} {html_escape(message)}")

    async def _set_props(self, chat_id: int, changes: dict, description: str) -> None:
        update_properties(self.cfg.properties_file, changes)
        note = " Перезапустите сервер, чтобы применить." if self.manager.is_running else ""
        await self.api.send_message(
            chat_id, f"✅ {html_escape(description)}.{note}", reply_markup=self.main_menu()
        )

    async def _set_port(self, chat_id: int, port: int) -> None:
        if not 1024 <= port <= 65535:
            await self.api.send_message(chat_id, "Порт должен быть от 1024 до 65535.")
            return
        if not port_is_free(port) and port != self.manager.port:
            await self.api.send_message(chat_id, f"Порт {port} занят другой программой.")
            return
        update_properties(self.cfg.properties_file, {"server-port": port})
        self.state.set("last_port", port)
        await self.api.send_message(
            chat_id,
            f"✅ Порт изменён на <code>{port}</code>.\n"
            "В Docker также обновите SERVER_PORT в .env и выполните <code>docker compose up -d</code>, "
            "чтобы проброс порта совпадал.",
            reply_markup=self.main_menu(),
        )

    async def _apply_pending(self, chat_id: int, action: str, value: str) -> None:
        if action == "console":
            await self._do_console(chat_id, value)
        elif action == "port":
            if value.isdigit():
                await self._set_port(chat_id, int(value))
            else:
                await self.api.send_message(chat_id, "Нужно число. Попробуйте снова: /port 19132")
        elif action == "motd":
            await self._set_props(chat_id, {"motd": value, "server-name": value}, f"Название: {value}")
        elif action == "maxplayers":
            if value.isdigit():
                await self._set_props(chat_id, {"max-players": value}, f"Максимум игроков: {value}")
            else:
                await self.api.send_message(chat_id, "Нужно число. Попробуйте: /maxplayers 20")

    async def _handle_document(self, chat_id: int, document: dict) -> None:
        name = document.get("file_name", "file")
        if not name.lower().endswith(".phar"):
            await self.api.send_message(chat_id, "Принимаю только файлы плагинов .phar")
            return
        destination = self.cfg.server_dir / "plugins" / Path(name).name
        await self.api.send_message(chat_id, f"⬇️ Скачиваю {html_escape(name)}...")
        try:
            await self.api.download_file(document["file_id"], destination)
        except (TelegramError, aiohttp.ClientError, OSError) as exc:
            await self.api.send_message(chat_id, f"❌ Не удалось скачать: {html_escape(str(exc))}")
            return
        await self.api.send_message(
            chat_id,
            f"✅ Плагин <code>{html_escape(name)}</code> установлен в plugins/.\n"
            "Нажмите Рестарт, чтобы плагин загрузился.",
            reply_markup=self.main_menu(),
        )

    # ------------------------------------------------------------- callback
    async def _handle_callback(self, query: dict) -> None:
        data = query.get("data", "")
        message = query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        user_id = query.get("from", {}).get("id")
        callback_id = query.get("id", "")
        if chat_id is None or user_id is None:
            return
        if not self.is_allowed(user_id):
            await self.api.answer_callback(callback_id, "Доступ закрыт", alert=True)
            return
        await self.api.answer_callback(callback_id)

        if data == "menu:main":
            await self.api.edit_message_text(
                chat_id, message["message_id"], "<b>🎮 Главное меню</b>", reply_markup=self.main_menu()
            )
        elif data == "menu:settings":
            await self.api.edit_message_text(
                chat_id,
                message["message_id"],
                "<b>⚙️ Настройки сервера</b>\nИзменения пишутся в server.properties.",
                reply_markup=self.settings_menu(),
            )
        elif data == "srv:start":
            await self._do_start(chat_id)
        elif data == "srv:stop":
            await self._do_stop(chat_id)
        elif data == "srv:restart":
            await self._do_restart(chat_id)
        elif data == "srv:status":
            await self.api.send_message(chat_id, await self.status_text(), reply_markup=self.main_menu())
        elif data == "srv:ip":
            await self.api.send_message(chat_id, await self.addresses_text(), reply_markup=self.main_menu())
        elif data == "srv:players":
            await self._do_players(chat_id)
        elif data == "srv:logs":
            await self._do_logs(chat_id, 30)
        elif data == "srv:backup":
            await self._do_backup(chat_id)
        elif data == "srv:plugins":
            await self._run_command(chat_id, "plugins", "")
        elif data == "srv:install":
            await self._do_install(chat_id)
        elif data == "set:reinstall":
            await self._do_install(chat_id, force=True)
        elif data == "set:whitelist":
            await self._run_command(chat_id, "whitelist", "")
        elif data == "set:tunnel":
            await self._do_tunnel(chat_id)
        elif data == "set:gamemode":
            await self.api.send_message(
                chat_id, "Выберите режим: <code>/gamemode 0</code> — выживание, 1 — креатив, 2 — приключение, 3 — наблюдатель"
            )
        elif data == "set:difficulty":
            await self.api.send_message(chat_id, "Сложность: <code>/difficulty 0..3</code>")
        elif data in {"set:port", "set:motd", "set:maxplayers", "set:console"}:
            action = data.split(":", 1)[1]
            self.pending[chat_id] = action
            prompts = {
                "port": "Введите новый порт (например 19132):",
                "motd": "Введите новое название сервера:",
                "maxplayers": "Введите максимальное число игроков:",
                "console": "Введите команду сервера (например list):",
            }
            await self.api.send_message(chat_id, prompts[action])

    # ---------------------------------------------------------------- выход
    async def shutdown(self) -> None:
        self.stop_event.set()
        with contextlib.suppress(Exception):
            await self.manager.stop()
        with contextlib.suppress(Exception):
            await self.tunnel.stop()


async def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    base = Path(os.environ.get("MCPE_BASE_DIR", Path(__file__).resolve().parent.parent))
    load_env_file(base / ".env")
    load_env_file(Path(__file__).resolve().parent.parent / ".env")

    cfg = Config.load()
    if not cfg.bot_token:
        log.error(
            "Не задан BOT_TOKEN. Создайте бота у @BotFather и укажите токен в файле .env"
        )
        return 2
    cfg.ensure_dirs()

    timeout = aiohttp.ClientTimeout(total=None)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        api = TelegramAPI(cfg.bot_token, session)
        await api.drop_webhook()
        try:
            me = await api.call("getMe")
            log.info("Бот @%s готов", me.get("username"))
        except TelegramError as exc:
            log.error("Неверный BOT_TOKEN: %s", exc)
            return 2
        await api.set_my_commands(BOT_COMMANDS)

        app = BotApp(cfg, api, session)
        await app.startup()
        try:
            await poll_updates(api, app.handle_update, app.stop_event)
        except (KeyboardInterrupt, asyncio.CancelledError):
            log.info("Завершение по сигналу")
        finally:
            await app.shutdown()
    return 0
