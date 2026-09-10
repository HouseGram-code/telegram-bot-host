# 🎮 Telegram-бот хостинга Minecraft PE 1.1.x (GenisysPro)

Полностью готовый комплект: **Telegram-бот сам скачивает бинарники PHP 7.0/7.1/7.2, настраивает сервер, запускает его и выдаёт рабочий IP-адрес с портом** для подключения с телефона (Android/iOS) и с ПК (Windows 10 Edition).

| Параметр | Значение |
|---|---|
| Игра | Minecraft **PE / Windows 10 Edition v1.1.0 – v1.1.5** (protocol 113) |
| Ядро | GenisysPro (API 3.0.1) — файл `server/GenisysPro.phar` уже внутри |
| PHP | 7.0 / 7.1 / **7.2 (по умолчанию, максимум)** с pthreads — скачивается автоматически |
| Бот | Python **3.13** + aiohttp (без тяжёлых фреймворков) |
| Контейнер | **Docker** + Docker Compose v2 (образ `python:3.13-slim-bookworm`) |
| Порт | **19132/UDP** (меняется в `.env` или командой `/port`) |

> ⚠️ Это **не** современный Bedrock Dedicated Server. Ядро рассчитано именно на старые клиенты 1.1.x — новые версии игры (1.2+) подключиться не смогут.

---

## 🚀 Быстрый старт

### 0. Получите токен и свой ID

1. В Telegram напишите [@BotFather](https://t.me/BotFather) → `/newbot` → скопируйте токен вида `1234567890:AA...`.
2. Свой числовой ID узнайте у [@userinfobot](https://t.me/userinfobot) (или оставьте `ADMIN_IDS` пустым — первый, кто нажмёт `/start`, станет владельцем).

### 1. Linux / macOS / WSL (рекомендуется)

```bash
unzip mcpe-telegram-host.zip
cd mcpe-telegram-host
bash install.sh
```

Скрипт проверит Docker, спросит токен, ID и порт, сам создаст `.env` и выполнит `docker compose up -d --build`.

### 2. Windows 10 / 11

1. Установите **Docker Desktop** и запустите его.
2. Распакуйте архив, зайдите в папку.
3. Двойной клик по **`install.bat`** (или `powershell -ExecutionPolicy Bypass -File install.ps1`).

### 3. Без Docker (только Linux/WSL, нужен Python 3.11+)

```bash
cp .env.example .env      # впишите BOT_TOKEN
bash scripts/run_local.sh
```

### 4. Готово

Откройте бота в Telegram → **`/start`** → нажмите **▶️ Старт** (если автозапуск не сработал) → **🌐 IP/Порт** и вводите адрес в игре.

---

## 🤖 Что бот делает сам при первом запуске

1. Создаёт папки `server/`, `data/`, `php_cache/`, `runtime/`.
2. **Ищет и ставит PHP 7.x** по цепочке (5 попыток, останавливается на первой удачной):
   1. уже установленный `runtime/php` внутри проекта;
   2. путь из `PHP_BINARY_PATH` (если у вас свой PHP 7.x с pthreads);
   3. локальные архивы `*.tar.gz` из папки `php_cache/` — **работает вообще без интернета**;
   4. загрузка готовых бинарников с зеркал (jenkins.pmmp.io, ci.pmmp.io, GitHub `pmmp/PHP-Binaries`) — сначала 7.2, затем 7.1, затем 7.0;
   5. сборка из исходников (`pmmp/php-build-scripts`) — долго (20–40 мин), включается `ALLOW_PHP_BUILD=1`.
3. Проверяет собранный PHP: версия должна быть **7.0–7.2**, обязателен модуль **pthreads**.
4. Генерирует `server/server.properties` и `server/pocketmine.yml` из `.env` (отключены телеметрия и автообновления, `xbox-auth=off`, `online-mode=false` — для клиентов 1.1.x).
5. Проверяет, свободен ли UDP-порт, при занятости берёт следующий свободный и прописывает его в конфиг.
6. Запускает `php GenisysPro.phar --no-wizard`, ждёт строку готовности и **пингует сервер по RakNet** — то есть адрес в `/ip` показывается только после реальной проверки отклика.
7. Пишет вам в чат статус, адрес и порт.

---

## 📋 Команды

| Команда | Что делает |
|---|---|
| `/start`, `/menu` | Главное меню с кнопками |
| `/help` | Справка по всем командам |
| `/status` | Онлайн, аптайм, память, диск, порт, проверка RakNet |
| `/ip` | **Все адреса подключения: localhost, локальный IP (Wi-Fi), Docker-хост, внешний IP, туннель** |
| `/startserver`, `/stop`, `/restart` | Управление сервером |
| `/players` | Список игроков онлайн |
| `/logs [n]` | Последние n строк консоли (по умолчанию 30) |
| `/console <команда>` | Любая команда ядра и её вывод |
| `/say <текст>` | Сообщение всем в чат игры |
| `/op`, `/deop`, `/kick`, `/whitelist` | Модерация |
| `/port <число>` | Смена порта + автоперезапуск |
| `/motd <текст>` | Название сервера в списке |
| `/maxplayers <n>`, `/gamemode <0-3>`, `/difficulty <0-3>` | Игровые настройки |
| `/setprop <ключ> <значение>` | Правка любого параметра `server.properties` |
| `/backup` | ZIP-бэкап миров/игроков/плагинов, файл приходит в чат |
| `/plugins` | Список установленных плагинов |
| `/install`, `/reinstall` | Повторная авто-установка PHP и конфигов |
| `/stream on\|off` | Трансляция консоли сервера прямо в чат |
| `/tunnel` | Временный публичный адрес через playit.gg (без проброса портов) |
| `/id` | Ваш Telegram ID |

**Плагины**: просто отправьте боту файл `.phar` — он положит его в `server/plugins/` и предложит перезапуск.

---

## 🌐 Как подключиться к серверу

Команда **`/ip`** присылает готовый список адресов. Что использовать:

| Откуда играете | Адрес | Порт |
|---|---|---|
| Тот же ПК (Windows 10 Edition) | `127.0.0.1` | `19132` |
| Телефон в той же Wi-Fi сети | локальный IP из `/ip`, например `192.168.1.50` | `19132` |
| Docker Desktop (Win/macOS) | `host.docker.internal` / IP хоста из `/ip` | `19132` |
| Друзья из интернета | внешний IP или домен + **проброс UDP-порта** на роутере | `19132` |
| Без настройки роутера | адрес из `/tunnel` (playit.gg) | указан в ответе |

### Телефон (Android / iOS), MCPE 1.1.5

Игра → **Играть** → вкладка **Серверы** → **Добавить сервер**:
- Название: любое
- Адрес: локальный IP из `/ip`
- Порт: `19132`

### Windows 10 Edition

Если сервер на том же ПК и `127.0.0.1` не подключается, UWP-приложению нужно разрешить loopback. PowerShell **от администратора**:

```powershell
CheckNetIsolation LoopbackExempt -a -n="Microsoft.MinecraftUWP_8wekyb3d8bbwe"
```

### Чтобы сервер появился в разделе «Сеть» (LAN) на Linux

```bash
docker compose -f docker-compose.yml -f docker-compose.host.yml up -d --build
```

(в режиме `network_mode: host` работает широковещательное обнаружение)

### Проброс порта для игры через интернет

В роутере: `Port Forwarding` → внешний порт **19132/UDP** → внутренний IP компьютера, порт **19132/UDP**. TCP пробрасывать не нужно (RakNet работает по UDP).

---

## ⚙️ Основные настройки `.env`

```env
BOT_TOKEN=            # токен @BotFather
ADMIN_IDS=            # ваш Telegram ID (можно несколько через запятую)
SERVER_PORT=19132     # UDP-порт сервера
SERVER_MOTD=Genisys 1.1.5 Server
MAX_PLAYERS=20
GAMEMODE=0            # 0 выживание, 1 креатив, 2 приключение, 3 наблюдатель
DIFFICULTY=2
SERVER_LANGUAGE=rus   # язык ядра Genisys
PHP_TARGET_VERSION=7.2  # 7.2 максимум, можно 7.1 или 7.0
PHP_BINARY_URL=       # своя ссылка на архив бинарников PHP
PHP_BINARY_PATH=      # путь к готовому php 7.x с pthreads
ALLOW_PHP_BUILD=1     # разрешить сборку из исходников как последний шанс
AUTO_INSTALL=1        # ставить PHP при старте бота
AUTO_START=1          # сразу запускать сервер
ENABLE_TUNNEL=0       # публичный адрес playit.gg
```

После правки `.env`: `docker compose up -d` (перезапустит контейнер с новыми значениями).

---

## 🛠 Если что-то не работает

| Проблема | Решение |
|---|---|
| «Не удалось скачать PHP» | Скачайте архив бинарников PocketMine PHP 7.2 (Linux x86_64) на любом ПК с интернетом, положите файл в папку `php_cache/`, затем `/install` в боте. Или укажите `PHP_BINARY_URL` в `.env`. |
| «pthreads не найден» | Нужна именно сборка PocketMine/pmmp (обычный системный PHP не подходит). Уберите `PHP_BINARY_PATH` и дайте боту скачать свою сборку: `/reinstall`. |
| Ошибки glibc при запуске php | Соберите PHP внутри контейнера: `ALLOW_PHP_BUILD=1`, затем `/reinstall` (в образе уже есть компилятор). |
| Порт занят | `/port 19140` — бот сменит порт и перезапустит сервер (в Docker пробросьте новый порт: `SERVER_PORT` в `.env` + `docker compose up -d`). |
| Сервер запускается и падает | `/logs 60` — покажет последние строки; частая причина — несовместимый плагин в `server/plugins/`. |
| Не видно из интернета | Проверьте `/ip`, проброс **UDP** на роутере и брандмауэр; быстрая альтернатива — `/tunnel`. |
| Игра 1.2+ не подключается | Так и должно быть: ядро 1.1.x (protocol 113). Нужен клиент версии 1.1.0–1.1.5. |
| Бот не отвечает | `docker compose logs -f` — проверьте `BOT_TOKEN`; при неверном токене бот пишет об этом в лог. |

Диагностика вручную: `bash scripts/install_php.sh` — та же цепочка установки PHP, но с подробным выводом в терминал.

---

## 📁 Структура проекта

```
mcpe-telegram-host/
├─ bot/                    # исходники бота (Python 3.13)
│  ├─ app.py               # команды, кнопки, меню, обработчики
│  ├─ installer.py         # авто-скачивание и проверка PHP 7.0-7.2
│  ├─ server.py            # запуск/остановка ядра, консоль, бэкапы
│  ├─ raknet.py            # реальная проверка сервера по протоколу MCPE
│  ├─ net.py               # локальный/внешний IP, свободные порты
│  ├─ props.py             # server.properties и pocketmine.yml
│  ├─ tunnel.py            # playit.gg (временный публичный адрес)
│  ├─ tgapi.py             # клиент Telegram Bot API
│  ├─ state.py, config.py, healthcheck.py
├─ server/GenisysPro.phar  # ядро MCPE 1.1.x
├─ server/plugins/         # сюда попадают отправленные боту .phar
├─ php_cache/              # архивы PHP (можно положить вручную, офлайн-режим)
├─ data/                   # состояние, логи, бэкапы
├─ Dockerfile, docker-compose.yml, docker-compose.host.yml
├─ install.sh / install.bat / install.ps1
└─ scripts/                # entrypoint, install_php.sh, run_local.sh
```

---

## 🔒 Безопасность

- Управлять ботом могут только ID из `ADMIN_IDS` (или владелец, захвативший бота первым `/start`).
- Токен хранится только в `.env` (файл в `.gitignore` и `.dockerignore`).
- `online-mode` и `xbox-auth` выключены — это требование клиентов 1.1.x, поэтому не открывайте сервер в интернет без нужды и используйте `/whitelist` для приватной игры.

---

## Почему PHP 7 больше не скачивается (и как это решено)

Если в логах было такое:

```
✗ не удалось: HTTPError: HTTP Error 404: Not Found
✗ слишком маленький файл (300955 байт) - пропускаю
✗ не удалось: URLError: <urlopen error [Errno -2] Name or service not known>
```

— это не ошибка бота, а состояние интернета в 2026 году:

| Источник | Статус |
| --- | --- |
| `github.com/pmmp/PHP-Binaries` | архив (read-only с августа 2026), в релизах остались только PHP 8.x (теги `pm5-*`, `pm4-*`) — все теги `php-7.x-latest` удалены → 404 |
| `jenkins.pmmp.io` | задания `PHP-7.x-Aggregate` удалены, сервер отдаёт HTML-страницу ~300 КБ вместо архива |
| `ci.pmmp.io` | домен больше не существует (NXDOMAIN) |
| `compile.sh` от pmmp | поддерживает только PM5 / PHP 8.x |

GenisysPro (API 3.0.1, MCPE 1.1.x) работает только на PHP 7.0-7.2 с `pthreads`,
поэтому единственный надёжный вариант — **собрать PHP самому**. Сейчас это
делается автоматически при `docker compose build`.

### Как это работает теперь

1. **Этап 1 образа** (`debian:buster`, apt из `archive.debian.org`) — там есть OpenSSL 1.1,
   bison 3.3 и gcc 8, на которых PHP 7.2 собирается без патчей.
   Скрипт `scripts/build_php72.sh` собирает:
   - PHP **7.2.34** с `--enable-maintainer-zts` (thread-safe — обязательно для pthreads);
   - **pthreads 3.2.0** (последняя версия, совместимая с PHP 7.2);
   - **ext-yaml**, а также curl, openssl, sockets, zip, mbstring, bcmath, gmp, zlib.
   Все нужные `.so` кладутся рядом (`/opt/php7/lib`), поэтому сборка запускается
   в современном рантайме с OpenSSL 3 через `LD_LIBRARY_PATH`.
2. **Этап 2** — Python 3.13 + бот; готовый PHP копируется в `/opt/php7`.
3. `entrypoint.sh` при старте переносит сборку в `runtime/php` (это том) и печатает
   версию PHP и наличие pthreads.
4. Установщик бота теперь ищет PHP в таком порядке:
   `runtime/php` → `/opt/php7` (сборка из образа) → `PHP_BINARY_PATH` → `php_cache/*.tar.gz`
   → `PHP_BINARY_URL` → сборка из исходников.

### Обновление на VDS

```bash
cd ~/telegram-bot-host          # или папка проекта
git pull                        # либо распакуйте свежий zip поверх
docker compose down
docker compose -f docker-compose.yml -f docker-compose.host.yml build --no-cache
docker compose -f docker-compose.yml -f docker-compose.host.yml up -d
docker compose logs -f
```

Первая сборка занимает **10-40 минут** и требует ~2 ГБ RAM (или swap)
и ~3 ГБ свободного места. Своп, если памяти мало:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
```

### Быстрый обход без сборки

Если где-то есть готовый архив PHP 7.x для Linux x86_64 с pthreads:

```bash
cp PHP-7.2-Linux-x86_64.tar.gz ~/telegram-bot-host/php_cache/
docker compose restart
# или в боте: /install
```

Архив должен содержать `bin/php7/bin/php` или `bin/php` и быть больше 5 МБ —
слишком маленькие файлы и ответы не в формате gzip теперь отбрасываются сразу.

### Сборка PHP отдельно (без пересборки всего образа)

```bash
bash scripts/build_php_docker.sh      # соберёт в debian:buster → runtime/php
```

На старых системах (Debian 10, Ubuntu 18.04/20.04, где OpenSSL 1.1) можно напрямую:

```bash
sudo bash scripts/php_buster_deps.sh   # только для Debian buster
PREFIX=$PWD/runtime/php bash scripts/build_php72.sh
```

Лог сборки из бота: `data/logs/php-build.log`.
