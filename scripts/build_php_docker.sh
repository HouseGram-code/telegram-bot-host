#!/usr/bin/env bash
# Сборка PHP 7.2 (ZTS) + pthreads внутри контейнера debian:buster.
# Нужна на современных системах (Ubuntu 22.04+/Debian 12+, OpenSSL 3),
# где PHP 7.2 напрямую не собирается.
#
# Результат: runtime/php/bin/php + runtime/php/lib (работает на любом хосте).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHP_VERSION="${PHP_VERSION:-7.2.34}"
PTHREADS_VERSION="${PTHREADS_VERSION:-3.2.0}"

command -v docker >/dev/null 2>&1 || { echo "Нужен Docker: https://get.docker.com"; exit 1; }

mkdir -p "${ROOT}/runtime"
rm -rf "${ROOT}/runtime/php"

echo "Собираю PHP ${PHP_VERSION} в debian:buster (10-40 минут)..."
docker run --rm \
  -v "${ROOT}/scripts:/scripts:ro" \
  -v "${ROOT}/runtime:/out" \
  -e PHP_VERSION="${PHP_VERSION}" \
  -e PTHREADS_VERSION="${PTHREADS_VERSION}" \
  -e PREFIX=/out/php \
  -e JOBS="$(nproc 2>/dev/null || echo 2)" \
  debian:buster \
  bash -c 'bash /scripts/php_buster_deps.sh && bash /scripts/build_php72.sh'

if [ -x "${ROOT}/runtime/php/bin/php" ]; then
  LD_LIBRARY_PATH="${ROOT}/runtime/php/lib" "${ROOT}/runtime/php/bin/php" -v | head -n1
  echo "Готово: ${ROOT}/runtime/php/bin/php"
else
  echo "Сборка не удалась"
  exit 1
fi
