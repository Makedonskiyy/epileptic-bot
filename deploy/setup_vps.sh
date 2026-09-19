#!/usr/bin/env bash
# ==============================================================================
# Скрипт автоматического развертывания Epileptic Bot на Ubuntu / Debian VPS
# ==============================================================================

set -e

echo "=== [1/5] Обновление системных пакетов Ubuntu ==="
sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv git curl

BOT_DIR="/opt/epileptic-bot"

echo "=== [2/5] Подготовка директории проекта ($BOT_DIR) ==="
sudo mkdir -p $BOT_DIR
# Если запускается из текущей папки проекта:
if [ -f "./bot.py" ]; then
    echo "Копирование текущих файлов в $BOT_DIR..."
    sudo cp -r ./* $BOT_DIR/
else
    echo "Внимание: запустите данный скрипт внутри папки с проектом бота или скопируйте файлы в $BOT_DIR вручную."
fi

cd $BOT_DIR

echo "=== [3/5] Создание виртуального окружения Python и установка зависимостей ==="
if [ ! -d "venv" ]; then
    sudo python3 -m venv venv
fi
sudo ./venv/bin/pip install --upgrade pip
sudo ./venv/bin/pip install -r requirements.txt

echo "=== [4/5] Проверка конфигурации .env ==="
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        sudo cp .env.example .env
        echo "Файл .env создан из .env.example. Обязательно укажите ваш DISCORD_TOKEN:"
        echo "nano $BOT_DIR/.env"
    fi
fi

echo "=== [5/5] Установка и запуск системного сервиса (systemd) ==="
sudo cp deploy/epileptic.service /etc/systemd/system/epileptic.service
sudo systemctl daemon-reload
sudo systemctl enable epileptic.service
sudo systemctl restart epileptic.service

echo ""
echo "=================================================================="
echo "✅ Установка завершена!"
echo "• Статус сервиса: sudo systemctl status epileptic.service"
echo "• Просмотр логов в реальном времени: sudo journalctl -u epileptic.service -f"
echo "• Веб-панель доступна по адресу: http://IP_ВАШЕГО_СЕРВЕРА:8080"
echo "=================================================================="
