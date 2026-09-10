"""Простое персистентное состояние бота (data/state.json)."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("state")


class State:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, Any] = {
            "owners": [],
            "console_stream": {},
            "tunnel_address": "",
            "last_port": 0,
            "installed_php": "",
        }
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text("utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Не удалось прочитать state.json: %s", exc)

    def save(self) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
                tmp.replace(self.path)
            except OSError as exc:
                log.warning("Не удалось сохранить state.json: %s", exc)

    # --------------------------------------------------------------- владельцы
    @property
    def owners(self) -> list[int]:
        return [int(x) for x in self.data.get("owners", [])]

    def add_owner(self, user_id: int) -> None:
        owners = self.owners
        if user_id not in owners:
            owners.append(user_id)
            self.data["owners"] = owners
            self.save()

    # ------------------------------------------------------- трансляция консоли
    def stream_enabled(self, chat_id: int) -> bool:
        return bool(self.data.get("console_stream", {}).get(str(chat_id)))

    def set_stream(self, chat_id: int, enabled: bool) -> None:
        streams = dict(self.data.get("console_stream", {}))
        if enabled:
            streams[str(chat_id)] = True
        else:
            streams.pop(str(chat_id), None)
        self.data["console_stream"] = streams
        self.save()

    def stream_chats(self) -> list[int]:
        return [int(key) for key in self.data.get("console_stream", {})]

    # ------------------------------------------------------------------- прочее
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()
