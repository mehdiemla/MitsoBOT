#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo ./install-service.sh"
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "Missing .env file. Create it from .env.example first."
  exit 1
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
pip install -r requirements.txt

cp telegram-order-bot.service /etc/systemd/system/telegram-order-bot.service
cp telegram-mini-app.service /etc/systemd/system/telegram-mini-app.service
systemctl daemon-reload
systemctl enable telegram-order-bot.service
systemctl enable telegram-mini-app.service

echo "Service installed."
echo "Start:   systemctl start telegram-order-bot"
echo "Status:  systemctl status telegram-order-bot"
echo "Logs:    journalctl -u telegram-order-bot -f"
echo "Stop:    systemctl stop telegram-order-bot"
echo "Mini App start:  systemctl start telegram-mini-app"
echo "Mini App status: systemctl status telegram-mini-app"
