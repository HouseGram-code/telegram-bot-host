# ============================================================
#  Автоустановщик для Windows (PowerShell 7 / встроенный 5.1)
#  Запуск:  powershell -ExecutionPolicy Bypass -File install.ps1
# ============================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Ok($m)   { Write-Host "[v] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[!] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[x] $m" -ForegroundColor Red }

Write-Host "============================================================"
Write-Host "  Minecraft PE / Windows 10 Edition 1.1.x - хостинг-бот"
Write-Host "  GenisysPro + PHP 7.0-7.2 (скачается автоматически)"
Write-Host "============================================================"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker не найден. Установите Docker Desktop."
    exit 1
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "Docker не запущен. Откройте Docker Desktop и повторите."
    exit 1
}
Ok "Docker работает"

if (-not (Test-Path "server/GenisysPro.phar")) {
    Fail "Нет файла server/GenisysPro.phar"
    exit 1
}
Ok "Ядро сервера найдено"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    $token = Read-Host "  Токен бота от @BotFather"
    $admin = Read-Host "  Ваш Telegram ID (узнать у @userinfobot)"
    $port  = Read-Host "  Порт сервера (Enter = 19132)"
    if ([string]::IsNullOrWhiteSpace($port)) { $port = "19132" }

    $content = Get-Content ".env" -Encoding UTF8
    if ($token) { $content = $content -replace '^BOT_TOKEN=.*', ("BOT_TOKEN=" + $token) }
    if ($admin) { $content = $content -replace '^ADMIN_IDS=.*', ("ADMIN_IDS=" + $admin) }
    $content = $content -replace '^SERVER_PORT=.*', ("SERVER_PORT=" + $port)
    $content = $content -replace '^SERVER_PORT_ALT=.*', ("SERVER_PORT_ALT=" + ([int]$port + 1))
    Set-Content ".env" $content -Encoding UTF8
    Ok "Файл .env заполнен"
} else {
    Ok "Файл .env уже есть"
}

foreach ($dir in @("data/backups", "data/logs", "php_cache", "server/plugins", "server/worlds")) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Write-Host ""
Write-Host "Сборка и запуск (первый раз - пара минут)..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    Fail "Ошибка запуска. Смотрите: docker compose logs -f"
    exit 1
}

Write-Host ""
Ok "Готово! Бот запущен."
Write-Host "  В Telegram:  /start    адрес для игры:  /ip    статус:  /status"
Write-Host "  Логи:  docker compose logs -f"
Write-Host ""
Warn "Windows 10 Edition: если игра не видит сервер на 127.0.0.1, выполните в PowerShell от админа:"
Write-Host '  CheckNetIsolation LoopbackExempt -a -n="Microsoft.MinecraftUWP_8wekyb3d8bbwe"'
