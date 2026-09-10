#!/usr/bin/env bash
# ============================================================
#  Автоустановщик: Telegram-бот для сервера Minecraft PE 1.1.x
#  Запуск:  bash install.sh
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT}"

GREEN="\033[1;32m"; RED="\033[1;31m"; YEL="\033[1;33m"; NC="\033[0m"
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YEL}!${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; }

echo "============================================================"
echo "  Minecraft PE / Windows 10 Edition 1.1.x — хостинг-бот"
echo "  Ядро: GenisysPro (API 3.0.1, protocol 113) + PHP 7.0-7.2"
echo "============================================================"

# --- 1. Проверка Docker ---------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  fail "Docker не найден."
  echo "  Установите Docker Desktop (Windows/macOS) или:"
  echo "      curl -fsSL https://get.docker.com | sh"
  echo "  Либо запустите без Docker:  bash scripts/run_local.sh"
  exit 1
fi
ok "Docker: $(docker --version | cut -d, -f1)"

if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
  warn "Используется старый docker-compose. Лучше обновить Docker."
else
  fail "Не найден Docker Compose (plugin или docker-compose)."
  exit 1
fi
ok "Compose: $(${DC} version --short 2>/dev/null || echo v1)"

if ! docker info >/dev/null 2>&1; then
  fail "Docker установлен, но демон не запущен. Запустите Docker и повторите."
  exit 1
fi

# --- 2. Ядро сервера -----------------------------------------
if [ -f server/GenisysPro.phar ]; then
  ok "Ядро server/GenisysPro.phar на месте ($(du -h server/GenisysPro.phar | cut -f1))"
else
  fail "Нет файла server/GenisysPro.phar — положите ядро в папку server/"
  exit 1
fi

# --- 3. Файл .env ---------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "Настройка бота (Enter — оставить пустым):"
  read -r -p "  Токен бота от @BotFather: " TOKEN
  read -r -p "  Ваш Telegram ID (/id или @userinfobot): " ADMIN
  read -r -p "  Порт сервера [19132]: " PORT
  read -r -p "  Название сервера (MOTD) [Genisys 1.1.5 Server]: " MOTD
  PORT="${PORT:-19132}"
  MOTD="${MOTD:-Genisys 1.1.5 Server}"

  python3 - "$TOKEN" "$ADMIN" "$PORT" "$MOTD" <<'PYEOF' || true
import sys, pathlib
token, admin, port, motd = sys.argv[1:5]
p = pathlib.Path(".env")
lines = []
for line in p.read_text("utf-8").splitlines():
    if line.startswith("BOT_TOKEN=") and token:
        line = "BOT_TOKEN=" + token
    elif line.startswith("ADMIN_IDS=") and admin:
        line = "ADMIN_IDS=" + admin
    elif line.startswith("SERVER_PORT="):
        line = "SERVER_PORT=" + port
    elif line.startswith("SERVER_PORT_ALT="):
        line = "SERVER_PORT_ALT=" + str(int(port) + 1)
    elif line.startswith("SERVER_MOTD="):
        line = "SERVER_MOTD=" + motd
    lines.append(line)
p.write_text("\n".join(lines) + "\n", "utf-8")
print("✓ .env заполнен")
PYEOF
else
  ok "Файл .env уже есть — оставляю как есть"
fi

if ! grep -qE '^BOT_TOKEN=.+' .env; then
  fail "В .env не задан BOT_TOKEN. Откройте .env, впишите токен и запустите снова."
  exit 1
fi

mkdir -p server/plugins server/worlds data/backups data/logs php_cache

# --- 4. Сборка и старт ----------------------------------------
COMPOSE_FILES="-f docker-compose.yml"
if [ "$(uname -s)" = "Linux" ] && [ "${USE_HOST_NETWORK:-0}" = "1" ]; then
  COMPOSE_FILES="${COMPOSE_FILES} -f docker-compose.host.yml"
  ok "Режим host-сети (сервер будет виден в разделе 'Сеть' в игре)"
fi

echo
echo "Сборка образа (первый раз — пара минут)..."
${DC} ${COMPOSE_FILES} up -d --build

echo
ok "Готово! Бот запущен и сам скачивает PHP 7.x + запускает сервер."
echo
echo "  Напишите боту в Telegram:  /start"
echo "  Адрес для подключения:      /ip"
echo "  Статус и игроки:            /status"
echo
echo "  Логи:     ${DC} logs -f"
echo "  Стоп:     ${DC} down"
echo "  Обновить: ${DC} up -d --build"
