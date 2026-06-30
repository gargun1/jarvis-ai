#!/bin/bash
# Jarvis VPS Setup Script
# Run as root on a fresh Ubuntu 22.04 VPS
# Usage: bash setup.sh

set -e
echo "=== Jarvis VPS Setup ==="

# 1. System update
apt-get update && apt-get upgrade -y

# 2. Install Docker
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 3. Install nginx + certbot
apt-get install -y nginx certbot python3-certbot-nginx ufw

# 4. Firewall
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# 5. Create jarvis user (no root for app)
useradd -m -s /bin/bash jarvis || true
usermod -aG docker jarvis

# 6. Clone repo (edit this URL)
echo ""
echo "=== Manual steps remaining ==="
echo "1. Push your jarvis-ai repo to GitHub"
echo "2. Run: git clone https://github.com/YOUR_USERNAME/jarvis-ai.git /home/jarvis/jarvis-ai"
echo "3. Run: cp /home/jarvis/jarvis-ai/.env.example /home/jarvis/jarvis-ai/.env"
echo "4. Edit .env: nano /home/jarvis/jarvis-ai/.env"
echo "5. Copy nginx config:"
echo "   cp /home/jarvis/jarvis-ai/deploy/nginx.conf /etc/nginx/sites-available/jarvis"
echo "   ln -s /etc/nginx/sites-available/jarvis /etc/nginx/sites-enabled/"
echo "   nano /etc/nginx/sites-available/jarvis  # set your domain"
echo "   nginx -t && systemctl reload nginx"
echo "6. SSL (optional but recommended):"
echo "   certbot --nginx -d your-domain.com"
echo "7. Start Jarvis:"
echo "   cd /home/jarvis/jarvis-ai && docker compose up -d"
echo "8. Check logs:"
echo "   docker compose logs -f jarvis"
echo ""
echo "Jarvis will be available at http://YOUR_VPS_IP or https://your-domain.com"

# IBKR note
echo ""
echo "=== IBKR Note ==="
echo "IBKR TWS/Gateway must run on your local machine (or another server)."
echo "To connect from the VPS, set up an SSH tunnel:"
echo "  ssh -L 7497:127.0.0.1:7497 user@your-local-machine"
echo "Or run IB Gateway on the VPS itself (requires X11 or headless setup)."
