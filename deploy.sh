#!/bin/bash
# AIME Telegram Operator Console — Deploy Script
# Run this on the VPS after uploading the files

set -e

echo "🤖 Deploying AIME Telegram Operator Console..."

# Create directory
mkdir -p /opt/aime-telegram-bot
cp bot.py /opt/aime-telegram-bot/
cp requirements.txt /opt/aime-telegram-bot/
cp .env /opt/aime-telegram-bot/

# Create virtual environment
echo "📦 Setting up Python environment..."
cd /opt/aime-telegram-bot
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# Install service
echo "⚙️ Installing systemd service..."
cp /opt/aime-telegram-bot/aime-telegram.service /etc/systemd/system/ 2>/dev/null || \
  cp aime-telegram.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable aime-telegram
systemctl restart aime-telegram

echo ""
echo "✅ AIME Telegram Console deployed!"
echo ""
echo "Check status:  systemctl status aime-telegram"
echo "View logs:     journalctl -u aime-telegram -f"
echo ""
echo "⚠️  IMPORTANT: Make sure you edited .env with your Telegram user ID!"
echo "    File: /opt/aime-telegram-bot/.env"
echo "    Line: TELEGRAM_OWNER_ID=REPLACE_WITH_YOUR_TELEGRAM_USER_ID"
