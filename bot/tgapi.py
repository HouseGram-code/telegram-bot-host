"""Минимальный асинхронный клиент Telegram Bot API (только aiohttp).

Специально без тяжёлых фреймворков: ничего не ломается при обновлении
сторонних библиотек, работает на любом Python 3.11+.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Iterable

import aiohttp

log = logging.getLogger("tgapi")

API_ROOT = "https://api.telegram.org"
MAX_TEXT = 3800


class TelegramError(RuntimeError):
    def __init__(self, method: str, code: int, description: str):
        super().__init__(f"{method} -> {code}: {description}")
        self.method = method
        self.code = code
        self.description = description


def html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def chunk_text(text: str, limit: int = MAX_TEXT) -> list[str]:
    """Режет длинный текст по строкам, чтобы уложиться в лимит Telegram."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


def inline_keyboard(rows: Iterable[Iterable[tuple[str, str]]]) -> dict[str, Any]:
    """[[(текст, callback_data), ...], ...] -> reply_markup."""
    keyboard = []
    for row in rows:
        keyboard.append([{"text": text, "callback_data": data} for text, data in row])
    return {"inline_keyboard": keyboard}


class TelegramAPI:
    def __init__(self, token: str, session: aiohttp.ClientSession):
        self.token = token
        self.session = session
        self.base = f"{API_ROOT}/bot{token}"

    # --------------------------------------------------------------- базовое
    async def call(self, method: str, _http_timeout: int = 45, **params: Any) -> Any:
        payload = {}
        for key, value in params.items():
            if value is None:
                continue
            payload[key] = json.dumps(value) if isinstance(value, (dict, list)) else value
        url = f"{self.base}/{method}"
        client_timeout = aiohttp.ClientTimeout(total=_http_timeout)
        async with self.session.post(url, data=payload, timeout=client_timeout) as resp:
            data = await resp.json(content_type=None)
        if not data.get("ok"):
            raise TelegramError(method, data.get("error_code", resp.status), data.get("description", ""))
        return data.get("result")

    async def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        return await self.call(
            "getUpdates",
            _http_timeout=timeout + 20,
            offset=offset,
            limit=50,
            timeout=timeout,
            allowed_updates=["message", "callback_query"],
        )

    # ------------------------------------------------------------ сообщения
    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = "HTML",
        disable_notification: bool = False,
    ) -> dict[str, Any] | None:
        result = None
        parts = chunk_text(text)
        for index, part in enumerate(parts):
            is_last = index == len(parts) - 1
            try:
                result = await self.call(
                    "sendMessage",
                    chat_id=chat_id,
                    text=part,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup if is_last else None,
                    disable_notification=disable_notification,
                    link_preview_options={"is_disabled": True},
                )
            except TelegramError as exc:
                if parse_mode and "can't parse" in exc.description.lower():
                    result = await self.call(
                        "sendMessage",
                        chat_id=chat_id,
                        text=part,
                        reply_markup=reply_markup if is_last else None,
                        disable_notification=disable_notification,
                        link_preview_options={"is_disabled": True},
                    )
                else:
                    raise
        return result

    async def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = "HTML",
    ) -> None:
        try:
            await self.call(
                "editMessageText",
                chat_id=chat_id,
                message_id=message_id,
                text=text[:MAX_TEXT],
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                link_preview_options={"is_disabled": True},
            )
        except TelegramError as exc:
            if "not modified" in exc.description.lower():
                return
            await self.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

    async def answer_callback(self, callback_id: str, text: str = "", alert: bool = False) -> None:
        try:
            await self.call(
                "answerCallbackQuery",
                callback_query_id=callback_id,
                text=text[:190],
                show_alert=alert,
            )
        except TelegramError as exc:
            log.debug("answerCallbackQuery: %s", exc)

    async def send_document(
        self,
        chat_id: int | str,
        path: Path,
        caption: str = "",
    ) -> dict[str, Any]:
        form = aiohttp.FormData()
        form.add_field("chat_id", str(chat_id))
        if caption:
            form.add_field("caption", caption[:1000])
            form.add_field("parse_mode", "HTML")
        form.add_field(
            "document",
            path.open("rb"),
            filename=path.name,
            content_type="application/octet-stream",
        )
        url = f"{self.base}/sendDocument"
        timeout = aiohttp.ClientTimeout(total=600)
        async with self.session.post(url, data=form, timeout=timeout) as resp:
            data = await resp.json(content_type=None)
        if not data.get("ok"):
            raise TelegramError("sendDocument", data.get("error_code", resp.status), data.get("description", ""))
        return data["result"]

    async def download_file(self, file_id: str, destination: Path) -> Path:
        info = await self.call("getFile", file_id=file_id)
        file_path = info["file_path"]
        url = f"{API_ROOT}/file/bot{self.token}/{file_path}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        timeout = aiohttp.ClientTimeout(total=600)
        async with self.session.get(url, timeout=timeout) as resp:
            resp.raise_for_status()
            with destination.open("wb") as handle:
                async for block in resp.content.iter_chunked(64 * 1024):
                    handle.write(block)
        return destination

    async def set_my_commands(self, commands: list[tuple[str, str]]) -> None:
        try:
            await self.call(
                "setMyCommands",
                commands=[{"command": name, "description": desc} for name, desc in commands],
            )
        except TelegramError as exc:
            log.warning("Не удалось установить список команд: %s", exc)

    async def drop_webhook(self) -> None:
        try:
            await self.call("deleteWebhook", drop_pending_updates=False)
        except TelegramError as exc:
            log.debug("deleteWebhook: %s", exc)


async def poll_updates(api: TelegramAPI, handler, stop_event: asyncio.Event) -> None:
    """Long polling с автоматическим восстановлением после сетевых сбоев."""
    offset: int | None = None
    backoff = 1
    while not stop_event.is_set():
        try:
            updates = await api.get_updates(offset, timeout=25)
            backoff = 1
        except TelegramError as exc:
            if exc.code == 409:
                log.warning("Конфликт getUpdates (запущен второй экземпляр бота?): %s", exc)
                await api.drop_webhook()
            else:
                log.warning("Ошибка Telegram API: %s", exc)
            await asyncio.sleep(min(backoff, 30))
            backoff *= 2
            continue
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("Сетевая ошибка: %s", exc)
            await asyncio.sleep(min(backoff, 30))
            backoff *= 2
            continue
        for update in updates:
            offset = update["update_id"] + 1
            try:
                await handler(update)
            except Exception:  # noqa: BLE001 - бот не должен падать из-за одного апдейта
                log.exception("Ошибка обработки апдейта %s", update.get("update_id"))
