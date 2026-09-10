#!/usr/bin/env bash
# Entrypoint контейнера: готовит папки, наполняет пустой том server/ и запускает бота.
set -euo pipefail

BASE="${MCPE_BASE_DIR:-/opt/mcpe}"

echo "============================================================="
echo " Minecraft PE 1.1.x hosting bot (GenisysPro + PHP 7.0-7.2)"
echo " Python: $(python --version 2>&1)"
echo " Base:   ${BASE}"
echo "============================================================="

mkdir -p "${BASE}/server/plugins" "${BASE}/server/worlds" "${BASE}/server/players" \
         "${BASE}/data/backups" "${BASE}/data/logs" "${BASE}/php_cache" "${BASE}/runtime"

# Если том server/ смонтирован пустым — копируем ядро и дефолтные конфиги из образа
if [ -d "${BASE}/defaults" ]; then
  for file in "${BASE}/defaults"/*; do
    name="$(basename "${file}")"
    if [ ! -e "${BASE}/server/${name}" ]; then
      cp -r "${file}" "${BASE}/server/${name}"
      echo "[entrypoint] восстановлен ${name} из образа"
    fi
  done
fi

if [ ! -f "${BASE}/server/GenisysPro.phar" ]; then
  echo "[entrypoint] ВНИМАНИЕ: ${BASE}/server/GenisysPro.phar не найден."
  echo "[entrypoint] Положите ядро GenisysPro.phar в папку server/ на хосте."
fi

if [ -z "${BOT_TOKEN:-}" ]; then
  echo "[entrypoint] ОШИБКА: не задан BOT_TOKEN. Укажите токен в файле .env"
fi

exec "$@"
