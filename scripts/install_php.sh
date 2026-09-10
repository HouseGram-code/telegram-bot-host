#!/usr/bin/env bash
# Ручная/резервная установка PHP 7.x (ZTS + pthreads) для GenisysPro.
#
# В 2026 готовые сборки PocketMine больше не раздаются: pmmp/PHP-Binaries
# заархивирован (только PHP 8.x), jenkins.pmmp.io и ci.pmmp.io отключены.
# Поэтому порядок: локальный архив → PHP_BINARY_URL → сборка из исходников.
#
# Использование:
#   ./scripts/install_php.sh                 # автоматически
#   PHP_BINARY_URL=https://... ./scripts/install_php.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${ROOT}/runtime/php"
CACHE="${ROOT}/php_cache"
PHP_VERSION="${PHP_VERSION:-7.2.34}"

mkdir -p "${ROOT}/runtime" "${CACHE}"

try_archive() {
  local archive="$1"
  local staging
  staging="$(mktemp -d)"
  tar -xzf "${archive}" -C "${staging}" 2>/dev/null || return 1
  local binary
  binary="$(find "${staging}" -type f -path '*/bin/php' | head -n1)"
  [ -n "${binary}" ] || return 1
  chmod +x "${binary}"
  local libdir
  libdir="$(dirname "$(dirname "${binary}")")/lib"
  local version
  version="$(LD_LIBRARY_PATH="${libdir}" "${binary}" -r 'echo PHP_VERSION;' 2>/dev/null || true)"
  case "${version}" in
    7.0*|7.1*|7.2*) ;;
    *) echo "  ✗ версия '${version:-?}' не подходит (нужно 7.0-7.2)"; return 1 ;;
  esac
  if ! LD_LIBRARY_PATH="${libdir}" "${binary}" -m | grep -qi pthreads; then
    echo "  ⚠ в сборке нет pthreads — сервер не запустится"
    return 1
  fi
  rm -rf "${TARGET}"
  mv "${staging}" "${TARGET}"
  echo "  ✓ установлен PHP ${version} → ${TARGET}"
  return 0
}

# 1) PHP из образа (если запуск внутри контейнера)
PREBUILT="${PHP_PREBUILT_DIR:-/opt/php7}"
if [ ! -x "${TARGET}/bin/php" ] && [ -x "${PREBUILT}/bin/php" ]; then
  echo "Копирую готовый PHP из ${PREBUILT}"
  rm -rf "${TARGET}"
  cp -a "${PREBUILT}" "${TARGET}"
  LD_LIBRARY_PATH="${TARGET}/lib" "${TARGET}/bin/php" -v | head -n1
  exit 0
fi

# 2) локальные архивы (работает без интернета)
shopt -s nullglob
for archive in "${CACHE}"/*.tar.gz "${CACHE}"/*.tgz; do
  echo "Пробую локальный архив: $(basename "${archive}")"
  if try_archive "${archive}"; then exit 0; fi
done
shopt -u nullglob

# 3) своя ссылка из .env
if [ -n "${PHP_BINARY_URL:-}" ]; then
  echo "Скачиваю: ${PHP_BINARY_URL}"
  tmp="${CACHE}/php-download.tar.gz"
  if curl -fL --connect-timeout 15 --retry 2 -o "${tmp}" "${PHP_BINARY_URL}" && try_archive "${tmp}"; then
    exit 0
  fi
  rm -f "${tmp}"
  echo "  ✗ по ссылке не получилось"
fi

# 4) сборка из исходников
OPENSSL_MAJOR="$(openssl version 2>/dev/null | awk '{print $2}' | cut -d. -f1)"
if [ "${OPENSSL_MAJOR:-3}" = "1" ] && command -v gcc >/dev/null && command -v make >/dev/null; then
  echo "Собираю PHP ${PHP_VERSION} из исходников напрямую..."
  PREFIX="${TARGET}" PHP_VERSION="${PHP_VERSION}" JOBS="$(nproc 2>/dev/null || echo 2)" \
    bash "${ROOT}/scripts/build_php72.sh" && exit 0
fi

if command -v docker >/dev/null 2>&1; then
  echo "Собираю PHP в контейнере debian:buster (на свежих системах с OpenSSL 3)"
  PHP_VERSION="${PHP_VERSION}" bash "${ROOT}/scripts/build_php_docker.sh" && exit 0
fi

cat <<'EOF'
✗ Не удалось установить PHP.

Почему: в 2026 готовых бинарников PHP 7 больше нет (pmmp/PHP-Binaries
заархивирован, jenkins.pmmp.io и ci.pmmp.io отключены).

Что делать:
  1. Установите Docker и запустите:  bash scripts/build_php_docker.sh
  2. Или положите готовый архив PHP 7.2 (linux x86_64, с pthreads)
     в папку php_cache/ и запустите этот скрипт снова.
  3. Или укажите ссылку в .env:  PHP_BINARY_URL=https://...
EOF
exit 1
