#!/usr/bin/env bash
# =============================================================================
#  Сборка PHP 7.x (ZTS) + pthreads + yaml из исходников для GenisysPro.
#  Ревизия: 2026.09.10-2
#
#  Зачем: в 2026 готовых бинарников PHP 7 в интернете больше нет:
#  pmmp/PHP-Binaries заархивирован (в релизах только PHP 8.x),
#  jenkins.pmmp.io отдаёт HTML-заглушку, ci.pmmp.io больше не резолвится.
#
#  Скрипт сам определяет версию OpenSSL: если в системе OpenSSL 3.x
#  (Debian 12, Ubuntu 22.04+), то сначала собирается OpenSSL 1.1.1w рядом,
#  потому что PHP 7.2 с OpenSSL 3 не собирается.
#
#  Переменные:
#    PREFIX=/opt/php7          куда установить
#    PHP_VERSION=7.2.34        версия PHP (7.2.34 / 7.1.33 / 7.0.33)
#    PTHREADS_VERSION=3.2.0    версия pthreads (3.2.0 для 7.2, 3.1.6 для 7.0-7.1)
#    YAML_VERSION=2.2.2        версия ext-yaml
#    OPENSSL_VERSION=1.1.1w    версия OpenSSL для собственной сборки
#    JOBS=4                    потоки make
# =============================================================================
set -euo pipefail

BUILD_REVISION="2026.09.10-2"
PREFIX="${PREFIX:-/opt/php7}"
PHP_VERSION="${PHP_VERSION:-7.2.34}"
PTHREADS_VERSION="${PTHREADS_VERSION:-3.2.0}"
YAML_VERSION="${YAML_VERSION:-2.2.2}"
OPENSSL_VERSION="${OPENSSL_VERSION:-1.1.1w}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 2)}"
WORK="${WORK:-/tmp/mcpe-php-build}"
SSL_PREFIX="${PREFIX}/openssl"

say() { echo "[build-php] $*"; }
say "ревизия скрипта ${BUILD_REVISION}, цель: PHP ${PHP_VERSION} → ${PREFIX}"

need() { command -v "$1" >/dev/null 2>&1 || { say "НЕТ утилиты: $1 (установите build-essential/curl)"; exit 2; }; }
need curl; need make; need tar; need awk
command -v gcc >/dev/null 2>&1 || need cc

download() {
  local out="$1"; shift
  local url
  for url in "$@"; do
    say "качаю: ${url}"
    if curl -fL --connect-timeout 20 --retry 3 --retry-delay 3 -o "${out}" "${url}"; then
      return 0
    fi
    say "  недоступно, пробую следующий источник"
  done
  say "не удалось скачать ${out}"
  return 1
}

rm -rf "${WORK}"
mkdir -p "${WORK}"
cd "${WORK}"

# ------------------------------------------------------------------- OpenSSL
# PHP 7.2 умеет собираться только с OpenSSL 1.0/1.1.
SSL_ARG="--with-openssl"
SYS_SSL="$(openssl version 2>/dev/null | awk '{print $2}' || true)"
BUILD_SSL=1
case "${SYS_SSL}" in
  1.0.*|1.1.*)
    if printf '#include <openssl/ssl.h>\nint main(void){return 0;}\n' > ssl-probe.c \
       && { gcc -c ssl-probe.c -o ssl-probe.o >/dev/null 2>&1 || cc -c ssl-probe.c -o ssl-probe.o >/dev/null 2>&1; }; then
      BUILD_SSL=0
      say "системный OpenSSL ${SYS_SSL} подходит"
    fi
    ;;
esac

if [ "${BUILD_SSL}" = "1" ]; then
  say "системный OpenSSL не подходит (версия: ${SYS_SSL:-нет}) — собираю OpenSSL ${OPENSSL_VERSION}"
  download openssl.tar.gz \
    "https://www.openssl.org/source/openssl-${OPENSSL_VERSION}.tar.gz" \
    "https://www.openssl.org/source/old/1.1.1/openssl-${OPENSSL_VERSION}.tar.gz" \
    "https://github.com/openssl/openssl/releases/download/OpenSSL_${OPENSSL_VERSION//./_}/openssl-${OPENSSL_VERSION}.tar.gz"
  mkdir -p openssl-src
  tar -xzf openssl.tar.gz -C openssl-src --strip-components=1
  ( cd openssl-src \
    && ./config --prefix="${SSL_PREFIX}" --openssldir="${SSL_PREFIX}/ssl" shared \
    && make -j"${JOBS}" \
    && make install_sw )
  export PKG_CONFIG_PATH="${SSL_PREFIX}/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
  export LD_LIBRARY_PATH="${SSL_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
  SSL_ARG="--with-openssl=${SSL_PREFIX}"
  say "OpenSSL готов: ${SSL_PREFIX}"
fi

# --------------------------------------------------------------- исходники PHP
cd "${WORK}"
download php.tar.gz \
  "https://www.php.net/distributions/php-${PHP_VERSION}.tar.gz" \
  "https://museum.php.net/php7/php-${PHP_VERSION}.tar.gz" \
  "https://github.com/php/php-src/archive/refs/tags/php-${PHP_VERSION}.tar.gz"
mkdir -p php-src
tar -xzf php.tar.gz -C php-src --strip-components=1
cd php-src
[ -f configure ] || ./buildconf --force

# на Debian/Ubuntu библиотеки лежат в /usr/lib/<multiarch>
MULTIARCH="$(gcc -print-multiarch 2>/dev/null || true)"
LIBDIR_ARG=""
if [ -n "${MULTIARCH}" ] && [ -d "/usr/lib/${MULTIARCH}" ]; then
  LIBDIR_ARG="--with-libdir=lib/${MULTIARCH}"
fi

say "конфигурирую PHP ${PHP_VERSION} (ZTS, thread-safe — нужно для pthreads)"
./configure \
  --prefix="${PREFIX}" \
  --with-config-file-path="${PREFIX}/bin" \
  --with-config-file-scan-dir="${PREFIX}/bin/conf.d" \
  ${LIBDIR_ARG} \
  --enable-maintainer-zts \
  --enable-cli --disable-cgi --disable-phpdbg --disable-fpm \
  --without-pear --disable-opcache \
  --enable-bcmath --enable-calendar --enable-ctype --enable-filter \
  --enable-fileinfo --enable-mbstring --enable-pcntl --enable-phar \
  --enable-posix --enable-sockets --enable-zip \
  --with-zlib --with-zlib-dir=/usr --with-curl --with-gmp ${SSL_ARG} \
  --without-sqlite3 --without-pdo-sqlite

say "компилирую (потоков: ${JOBS}) — от 10 до 40 минут"
make -j"${JOBS}"
make install
cd "${WORK}"

PHP_BIN="${PREFIX}/bin/php"
PHP_CONFIG="${PREFIX}/bin/php-config"
PHPIZE="${PREFIX}/bin/phpize"
EXT_DIR="$("${PHP_CONFIG}" --extension-dir)"
say "PHP установлен, extension_dir=${EXT_DIR}"

# ------------------------------------------------------------------- pthreads
download pthreads.tgz \
  "https://pecl.php.net/get/pthreads-${PTHREADS_VERSION}.tgz" \
  "https://github.com/krakjoe/pthreads/archive/refs/tags/v${PTHREADS_VERSION}.tar.gz"
mkdir -p pthreads
tar -xzf pthreads.tgz -C pthreads --strip-components=1
( cd pthreads \
  && "${PHPIZE}" \
  && ./configure --with-php-config="${PHP_CONFIG}" --enable-pthreads \
  && make -j"${JOBS}" \
  && make install )

# ----------------------------------------------------------------------- yaml
download yaml.tgz \
  "https://pecl.php.net/get/yaml-${YAML_VERSION}.tgz" \
  "https://pecl.php.net/get/yaml-2.0.4.tgz"
mkdir -p yaml
tar -xzf yaml.tgz -C yaml --strip-components=1
( cd yaml \
  && "${PHPIZE}" \
  && ./configure --with-php-config="${PHP_CONFIG}" --with-yaml \
  && make -j"${JOBS}" \
  && make install )

# ------------------------------------------------------------------- php.ini
mkdir -p "${PREFIX}/bin/conf.d" "${PREFIX}/lib"
CA_FILE="/etc/ssl/certs/ca-certificates.crt"
cat > "${PREFIX}/bin/php.ini" <<INI
; PHP ${PHP_VERSION} (ZTS) для GenisysPro / PocketMine API 3.x
; сборка ${BUILD_REVISION}
extension_dir="${EXT_DIR}"
extension=pthreads.so
extension=yaml.so
memory_limit=-1
date.timezone=UTC
phar.readonly=0
zend.assertions=-1
opcache.enable=0
opcache.enable_cli=0
openssl.cafile=${CA_FILE}
curl.cainfo=${CA_FILE}
error_reporting=E_ALL & ~E_DEPRECATED & ~E_NOTICE
display_errors=1
log_errors=1
INI

# ------------------------------------- складываем библиотеки рядом с PHP,
# чтобы сборка работала на любом современном дистрибутиве (LD_LIBRARY_PATH)
bundle_once() {
  local target="${PREFIX}/lib"
  mkdir -p "${target}"
  local files=("${PREFIX}/bin/php")
  shopt -s nullglob
  files+=("${EXT_DIR}"/*.so "${target}"/*.so*)
  shopt -u nullglob
  local file so base
  for file in "${files[@]}"; do
    [ -e "${file}" ] || continue
    while read -r so; do
      [ -f "${so}" ] || continue
      base="$(basename "${so}")"
      case "${base}" in
        libc.so.*|libm.so.*|libdl.so.*|librt.so.*|libpthread.so.*|ld-linux*|libnsl.so.*|libresolv.so.*|libutil.so.*|libcrypt.so.*) continue ;;
      esac
      [ -f "${target}/${base}" ] || cp -L "${so}" "${target}/${base}"
    done < <(ldd "${file}" 2>/dev/null | awk '/=> \//{print $3}')
  done
  return 0
}
for _pass in 1 2 3; do bundle_once; done
say "библиотек скопировано: $(ls -1 "${PREFIX}/lib" | wc -l)"

# -------------------------------------------------------------------- проверка
export LD_LIBRARY_PATH="${PREFIX}/lib"
VERSION="$("${PHP_BIN}" -c "${PREFIX}/bin/php.ini" -r 'echo PHP_VERSION;')"
MODULES="$("${PHP_BIN}" -c "${PREFIX}/bin/php.ini" -m)"
say "собран PHP ${VERSION}"
for ext in pthreads yaml curl sockets openssl zip mbstring bcmath phar zlib; do
  if echo "${MODULES}" | grep -qix "${ext}"; then
    say "  + ${ext}"
  else
    say "  ! нет расширения ${ext}"
  fi
done
if ! echo "${MODULES}" | grep -qix pthreads; then
  say "КРИТИЧНО: pthreads не собрался — GenisysPro не запустится"
  exit 3
fi

if [ "${KEEP_WORK:-0}" != "1" ]; then
  rm -rf "${WORK}"
fi
say "ГОТОВО: ${PREFIX}/bin/php  (php.ini: ${PREFIX}/bin/php.ini)"
