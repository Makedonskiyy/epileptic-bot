#!/usr/bin/env bash
# ==============================================================================
# Automated Epileptic Bot Setup Script for Ubuntu / Debian VPS
# ==============================================================================

set -e

echo "=== [1/5] Updating Ubuntu packages & installing prerequisites ==="
sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv git curl

TARGET_DIR="/opt/epileptic-bot"
CURRENT_DIR="$(pwd)"

echo "=== [2/5] Preparing bot directory ==="
if [ "$CURRENT_DIR" != "$TARGET_DIR" ]; then
    echo "Copying files from $CURRENT_DIR to $TARGET_DIR..."
    sudo mkdir -p "$TARGET_DIR"
    sudo cp -r "$CURRENT_DIR"/* "$TARGET_DIR"/
    sudo cp -r "$CURRENT_DIR"/.[!.]* "$TARGET_DIR"/ 2>/dev/null || true
    cd "$TARGET_DIR"
else
    echo "Already in target directory: $TARGET_DIR"
fi

echo "=== [3/5] Setting up Python virtual environment ==="
if [ ! -d "venv" ]; then
    sudo python3 -m venv venv
fi
sudo ./venv/bin/pip install --upgrade pip
sudo ./venv/bin/pip install -r requirements.txt

echo "=== [4/5] Checking environment configuration (.env) ==="
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        sudo cp .env.example .env
        echo "Created .env from .env.example."
        echo "⚠️ Please set your DISCORD_TOKEN:"
        echo "sudo nano $TARGET_DIR/.env"
    fi
fi

echo "=== [5/5] Installing & starting systemd service ==="
sudo cp deploy/epileptic.service /etc/systemd/system/epileptic.service
sudo systemctl daemon-reload
sudo systemctl enable epileptic.service
sudo systemctl restart epileptic.service

echo ""
echo "=================================================================="
echo "✅ Deployment completed successfully!"
echo "• Check bot service status: sudo systemctl status epileptic.service"
echo "• View real-time logs:      sudo journalctl -u epileptic.service -f"
echo "• Pull future git updates:  cd /opt/epileptic-bot && git pull && sudo systemctl restart epileptic.service"
echo "• Web dashboard live at:    http://YOUR_SERVER_IP:8080"
echo "=================================================================="
