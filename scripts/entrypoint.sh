#!/usr/bin/env bash
# Entrypoint контейнера: готовит папки, переносит собранный PHP в том runtime/,
# наполняет пустой том server/ и запускает бота.
set -euo pipefail

BASE="${MCPE_BASE_DIR:-/opt/mcpe}"
PHP_PREBUILT_DIR="${PHP_PREBUILT_DIR:-/opt/php7}"

echo "============================================================="
echo " Minecraft PE 1.1.x hosting bot (GenisysPro + PHP 7.2 ZTS)"
echo " Python: $(python --version 2>&1)"
echo " Base:   ${BASE}"
echo "============================================================="

mkdir -p "${BASE}/server/plugins" "${BASE}/server/worlds" "${BASE}/server/players" \
         "${BASE}/data/backups" "${BASE}/data/logs" "${BASE}/php_cache" "${BASE}/runtime"

# runtime/ часто смонтирован как том, поэтому PHP из образа переносим внутрь
if [ ! -x "${BASE}/runtime/php/bin/php" ] && [ -x "${PHP_PREBUILT_DIR}/bin/php" ]; then
  echo "[entrypoint] переношу собранный PHP из образа в runtime/php"
  rm -rf "${BASE}/runtime/php.tmp"
  cp -a "${PHP_PREBUILT_DIR}" "${BASE}/runtime/php.tmp"
  rm -rf "${BASE}/runtime/php"
  mv "${BASE}/runtime/php.tmp" "${BASE}/runtime/php"
fi

if [ -x "${BASE}/runtime/php/bin/php" ]; then
  php_line="$(LD_LIBRARY_PATH="${BASE}/runtime/php/lib" "${BASE}/runtime/php/bin/php" -v 2>&1 | head -n1 || true)"
  echo "[entrypoint] ${php_line}"
  if LD_LIBRARY_PATH="${BASE}/runtime/php/lib" "${BASE}/runtime/php/bin/php" -m 2>/dev/null | grep -qi pthreads; then
    echo "[entrypoint] pthreads: есть"
  else
    echo "[entrypoint] ВНИМАНИЕ: в сборке PHP нет pthreads"
  fi
else
  echo "[entrypoint] PHP пока не установлен — бот попробует собрать его сам"
fi

# Если том server/ смонтирован пустым — копируем ядро и конфиги из образа
if [ -d "${BASE}/defaults" ]; then
  for file in "${BASE}/defaults"/*; do
    [ -e "${file}" ] || continue
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
