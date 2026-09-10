# syntax=docker/dockerfile:1.9
# =============================================================================
#  Этап 1 — собираем PHP 7.2 (ZTS) + pthreads + yaml на Debian 10 (buster).
#
#  В 2026 готовых бинарников PHP 7 больше нет: pmmp/PHP-Binaries
#  заархивирован (только PHP 8.x), jenkins.pmmp.io и ci.pmmp.io отключены.
#  Поэтому PHP собирается один раз при сборке образа и ложится в /opt/php7
#  вместе со своими библиотеками (LD_LIBRARY_PATH), так она работает
#  и в свежем рантайме с OpenSSL 3.
# =============================================================================
ARG PHP_VERSION=7.2.34
ARG PTHREADS_VERSION=3.2.0

FROM debian:buster AS php-build
ARG PHP_VERSION
ARG PTHREADS_VERSION
ARG DEBIAN_FRONTEND=noninteractive

COPY scripts/php_buster_deps.sh scripts/build_php72.sh /build/
RUN chmod +x /build/*.sh && /build/php_buster_deps.sh
RUN PREFIX=/opt/php7 \
    PHP_VERSION="${PHP_VERSION}" \
    PTHREADS_VERSION="${PTHREADS_VERSION}" \
    JOBS="$(nproc)" \
    /build/build_php72.sh

# =============================================================================
#  Этап 2 — рантайм: свежий Python 3.13 + Telegram-бот + ядро GenisysPro
# =============================================================================
FROM python:3.13-slim-bookworm

ARG WITH_BUILD_TOOLS=0
ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    IN_DOCKER=1 \
    MCPE_BASE_DIR=/opt/mcpe \
    PHP_PREBUILT_DIR=/opt/php7

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl wget tar gzip bzip2 xz-utils zip unzip \
        git procps iproute2 iputils-ping net-tools tzdata \
        libstdc++6 zlib1g libgcc-s1; \
    if [ "$WITH_BUILD_TOOLS" = "1" ]; then \
        apt-get install -y --no-install-recommends \
            build-essential autoconf automake libtool libtool-bin m4 \
            bison re2c pkg-config cmake make gettext; \
    fi; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# Готовый PHP 7.2 из первого этапа (entrypoint перенесёт его в runtime/php)
COPY --from=php-build /opt/php7 /opt/php7

WORKDIR /opt/mcpe

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY scripts ./scripts
# Копия ядра и дефолтных конфигов: если том server/ пустой, entrypoint его наполнит
COPY server ./defaults

RUN chmod +x scripts/*.sh \
    && mkdir -p /opt/mcpe/server /opt/mcpe/data /opt/mcpe/php_cache /opt/mcpe/runtime

EXPOSE 19132/udp 19132/tcp

HEALTHCHECK --interval=45s --timeout=15s --start-period=180s --retries=4 \
    CMD python -m bot.healthcheck || exit 1

ENTRYPOINT ["/opt/mcpe/scripts/entrypoint.sh"]
CMD ["python", "-m", "bot"]
