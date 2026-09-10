@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   Minecraft PE / Windows 10 Edition 1.1.x - хостинг-бот
echo   Ядро: GenisysPro + PHP 7.0-7.2 (скачается автоматически)
echo ============================================================
echo.

where docker >nul 2>nul
if errorlevel 1 (
  echo [x] Docker не найден.
  echo     Скачайте Docker Desktop: https://www.docker.com/products/docker-desktop/
  pause
  exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
  echo [x] Docker установлен, но не запущен. Откройте Docker Desktop и повторите.
  pause
  exit /b 1
)
echo [v] Docker работает

if not exist "server\GenisysPro.phar" (
  echo [x] Нет файла server\GenisysPro.phar
  pause
  exit /b 1
)
echo [v] Ядро сервера найдено

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo.
  set /p TOKEN="  Токен бота от @BotFather: "
  set /p ADMINID="  Ваш Telegram ID (узнать у @userinfobot): "
  set /p PORT="  Порт сервера [19132]: "
  if "!PORT!"=="" set PORT=19132
  powershell -NoProfile -Command "$t='!TOKEN!'; $a='!ADMINID!'; $p='!PORT!'; $c=Get-Content .env -Encoding UTF8; $c=$c -replace '^BOT_TOKEN=.*',(\"BOT_TOKEN=\"+$t); $c=$c -replace '^ADMIN_IDS=.*',(\"ADMIN_IDS=\"+$a); $c=$c -replace '^SERVER_PORT=.*',(\"SERVER_PORT=\"+$p); $c=$c -replace '^SERVER_PORT_ALT=.*',(\"SERVER_PORT_ALT=\"+([int]$p+1)); Set-Content .env $c -Encoding UTF8"
  echo [v] Файл .env заполнен
) else (
  echo [v] Файл .env уже есть
)

if not exist "data\backups" mkdir "data\backups"
if not exist "data\logs" mkdir "data\logs"
if not exist "php_cache" mkdir "php_cache"
if not exist "server\plugins" mkdir "server\plugins"

echo.
echo Сборка и запуск (первый раз - пара минут)...
docker compose up -d --build
if errorlevel 1 (
  echo [x] Ошибка запуска. Логи: docker compose logs -f
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Готово! Напишите боту в Telegram: /start
echo   Адрес для игры: /ip     Статус: /status
echo   Логи: docker compose logs -f
echo ============================================================
pause
