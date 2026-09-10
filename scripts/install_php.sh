#!/usr/bin/env bash
# Ручная/резервная установка бинарников PHP 7.0-7.2 с pthreads для GenisysPro.
# Использование:
#   ./scripts/install_php.sh            # пробует 7.2, затем 7.1, затем 7.0
#   ./scripts/install_php.sh 7.1        # конкретная версия
#   PHP_BINARY_URL=https://... ./scripts/install_php.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${ROOT}/runtime/php"
CACHE="${ROOT}/php_cache"
ARCH="$(uname -m)"
case "${ARCH}" in
  x86_64|amd64) ARCH="x86_64" ;;
  aarch64|arm64) ARCH="aarch64" ;;
esac

VERSIONS=("${1:-7.2}" "7.2" "7.1" "7.0")
mkdir -p "${TARGET}" "${CACHE}"

try_archive() {
  local archive="$1"
  local staging
  staging="$(mktemp -d)"
  tar -xzf "${archive}" -C "${staging}" 2>/dev/null || return 1
  local binary
  binary="$(find "${staging}" -type f -path '*/bin/php' | head -n1)"
  [ -n "${binary}" ] || return 1
  chmod +x "${binary}"
  local libdir="$(dirname "$(dirname "${binary}")")/lib"
  local version
  version="$(LD_LIBRARY_PATH="${libdir}" "${binary}" -r 'echo PHP_VERSION;' 2>/dev/null || true)"
  case "${version}" in
    7.0*|7.1*|7.2*) ;;
    *) echo "  ✗ версия '${version:-?}' не подходит (нужно 7.0-7.2)"; return 1 ;;
  esac
  if ! LD_LIBRARY_PATH="${libdir}" "${binary}" -m | grep -qi pthreads; then
    echo "  ⚠ в сборке нет pthreads — сервер может не запуститься"
  fi
  rm -rf "${TARGET}"
  mkdir -p "$(dirname "${TARGET}")"
  mv "${staging}" "${TARGET}"
  echo "  ✓ установлен PHP ${version} → ${TARGET}"
  return 0
}

# 1) локальные архивы (работает без интернета)
shopt -s nullglob
for archive in "${CACHE}"/*.tar.gz "${CACHE}"/*.tgz; do
  echo "Пробую локальный архив: $(basename "${archive}")"
  if try_archive "${archive}"; then exit 0; fi
done
shopt -u nullglob

# 2) загрузка с зеркал
urls=()
[ -n "${PHP_BINARY_URL:-}" ] && urls+=("${PHP_BINARY_URL}")
for version in "${VERSIONS[@]}"; do
  tag="PHP-${version}-Linux-${ARCH}"
  urls+=(
    "https://jenkins.pmmp.io/job/PHP-${version}-Aggregate/lastSuccessfulBuild/artifact/${tag}.tar.gz"
    "https://jenkins.pmmp.io/job/PHP-${version}-Aggregate/lastStableBuild/artifact/${tag}.tar.gz"
    "https://ci.pmmp.io/job/PHP-${version}-Aggregate/lastSuccessfulBuild/artifact/${tag}.tar.gz"
    "https://github.com/pmmp/PHP-Binaries/releases/download/php-${version}-latest/${tag}.tar.gz"
    "https://github.com/pmmp/PHP-Binaries/releases/download/pm3-php-${version}-latest/${tag}.tar.gz"
  )
done

for url in "${urls[@]}"; do
  echo "Скачиваю: ${url}"
  tmp="${CACHE}/php-download.tar.gz"
  if curl -fL --connect-timeout 15 --retry 2 -o "${tmp}" "${url}"; then
    if try_archive "${tmp}"; then
      mv "${tmp}" "${CACHE}/$(basename "${url}")" 2>/dev/null || true
      exit 0
    fi
  else
    echo "  ✗ недоступно"
  fi
  rm -f "${tmp}"
done

# 3) сборка из исходников
if command -v git >/dev/null && command -v make >/dev/null; then
  echo "Готовые бинарники недоступны — собираю PHP из исходников (долго)..."
  work="${ROOT}/runtime/php-build"
  rm -rf "${work}"; mkdir -p "${work}"
  for ref in php7.2 php-7.2 legacy/php7.2 php7.1 master; do
    if git clone --depth 1 --branch "${ref}" https://github.com/pmmp/php-build-scripts.git "${work}/scripts"; then
      break
    fi
  done
  if [ -f "${work}/scripts/compile.sh" ]; then
    ( cd "${work}/scripts" && bash compile.sh -t linux64 -j "$(nproc)" -f )
    if [ -d "${work}/scripts/bin" ]; then
      rm -rf "${TARGET}"; mkdir -p "${TARGET}"
      cp -r "${work}/scripts/bin" "${TARGET}/bin"
      echo "  ✓ PHP собран из исходников"
      exit 0
    fi
  fi
fi

cat <<'EOF'
✗ Не удалось установить PHP автоматически.

Что делать:
  1. Скачайте архив PocketMine PHP 7.2 (linux x86_64) на любом ПК с интернетом.
  2. Положите файл в папку php_cache/ этого проекта.
  3. Запустите снова: ./scripts/install_php.sh   (или /install в боте)

Альтернатива: укажите прямую ссылку в .env → PHP_BINARY_URL=https://...
EOF
exit 1
