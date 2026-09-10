#!/usr/bin/env bash
# Обновление бота на VDS: полная пересборка образа с нуля.
# Запуск: bash scripts/update_vds.sh
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

COMPOSE="docker compose"
docker compose version >/dev/null 2>&1 || COMPOSE="docker-compose"

FILES="-f docker-compose.yml"
if [ -f docker-compose.host.yml ] && [ "${USE_HOST_NETWORK:-1}" = "1" ]; then
  FILES="${FILES} -f docker-compose.host.yml"
fi

echo "[update] проверка версии исходников"
# Проверяем наличие новой функции вместо старого URL
if ! grep -q 'def build_php_from_source' bot/installer.py 2>/dev/null; then
  echo "[update] ВНИМАНИЕ: в bot/installer.py устаревшая версия."
  echo "[update] Выполните git pull и повторите."
  exit 1
fi
grep -m1 'INSTALLER_REVISION' bot/installer.py || true

echo "[update] останавливаю контейнер"
${COMPOSE} ${FILES} down || true

echo "[update] сбрасываю том с PHP (чтобы взялась новая сборка)"
for v in $(docker volume ls -q | grep -E 'php-runtime$' || true); do
  docker volume rm "$v" || true
done

echo "[update] пересборка образа (10-40 минут: компилируется PHP 7.2)"
${COMPOSE} ${FILES} build --no-cache

echo "[update] запуск"
${COMPOSE} ${FILES} up -d
${COMPOSE} ${FILES} logs --tail 60
echo "[update] готово. Логи: ${COMPOSE} ${FILES} logs -f"
