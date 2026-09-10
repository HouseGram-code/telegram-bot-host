#!/usr/bin/env bash
# Запуск без Docker (Linux / macOS / WSL). Нужен Python 3.11+
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Создан файл .env — впишите в него BOT_TOKEN и запустите скрипт снова."
  exit 1
fi

PY="python3"
command -v python3 >/dev/null || PY="python"

if [ ! -d .venv ]; then
  echo "[1/3] Создаю виртуальное окружение..."
  "${PY}" -m venv .venv
fi

echo "[2/3] Устанавливаю зависимости..."
./.venv/bin/pip install --upgrade pip >/dev/null
./.venv/bin/pip install -r requirements.txt

echo "[3/3] Старт бота (Ctrl+C — выход)"
exec ./.venv/bin/python -m bot
