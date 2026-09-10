# syntax=docker/dockerfile:1.9
# Свежий Python 3.13 + автоустановка бинарников PHP 7.0-7.2 для GenisysPro
FROM python:3.13-slim-bookworm

ARG WITH_BUILD_TOOLS=1
ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    IN_DOCKER=1 \
    MCPE_BASE_DIR=/opt/mcpe

# Базовые утилиты + (опционально) тулчейн для сборки PHP из исходников
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

WORKDIR /opt/mcpe

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY scripts ./scripts
# Копия ядра и дефолтных конфигов: если том server/ пустой, entrypoint его наполнит
COPY server ./defaults

RUN chmod +x scripts/*.sh && mkdir -p /opt/mcpe/server /opt/mcpe/data /opt/mcpe/php_cache /opt/mcpe/runtime

EXPOSE 19132/udp 19132/tcp

HEALTHCHECK --interval=45s --timeout=15s --start-period=180s --retries=4 \
    CMD python -m bot.healthcheck || exit 1

ENTRYPOINT ["/opt/mcpe/scripts/entrypoint.sh"]
CMD ["python", "-m", "bot"]
