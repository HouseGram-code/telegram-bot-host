#!/usr/bin/env bash
# Готовит Debian 10 (buster) к сборке PHP 7.2:
#  - buster уехал в архив Debian, поэтому переключаем apt на archive.debian.org;
#  - ставим тулчейн и dev-пакеты (здесь есть OpenSSL 1.1, нужный PHP 7.2).
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

cat > /etc/apt/sources.list <<'SOURCES'
deb http://archive.debian.org/debian buster main contrib
deb http://archive.debian.org/debian-security buster/updates main contrib
SOURCES

cat > /etc/apt/apt.conf.d/99archive <<'CONF'
Acquire::Check-Valid-Until "false";
Acquire::Retries "3";
CONF

apt-get update
apt-get install -y --no-install-recommends \
  build-essential autoconf automake libtool libtool-bin m4 \
  bison re2c pkg-config make file xz-utils \
  curl ca-certificates \
  libssl-dev libcurl4-openssl-dev libyaml-dev libgmp-dev \
  zlib1g-dev libxml2-dev libedit-dev

apt-get clean
rm -rf /var/lib/apt/lists/*
echo "[deps] тулчейн готов: $(gcc --version | head -n1), openssl $(openssl version 2>/dev/null || echo '?')"
