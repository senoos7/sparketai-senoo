#!/usr/bin/env bash
# =============================================================================
# bootstrap_vps.sh — Fresh Ubuntu VPS bootstrap for Sparket mining
#
# Run this ONCE on a clean Ubuntu 22.04 or 24.04 VPS before the mainnet setup.
# It installs all system-level dependencies:
#   - System packages (build tools, git, curl)
#   - Python 3.10+ via uv
#   - Docker (for Postgres container)
#   - Node.js + PM2 (for process management)
#   - btcli (bittensor CLI) in a dedicated venv
#   - UFW firewall rules
#
# Usage (as a sudo-capable user, NOT root):
#   bash scripts/bootstrap_vps.sh
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

step() { echo -e "\n${GREEN}${BOLD}[STEP]${NC} $*"; }
info() { echo -e "       $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Step 0: Sanity checks ────────────────────────────────────────────────────
if [[ $EUID -eq 0 ]]; then
  err "Do NOT run as root. Run as a regular user with sudo access."
fi

if ! sudo -n true 2>/dev/null; then
  warn "You will be prompted for your sudo password during installation."
fi

step "Detected Ubuntu version:"
lsb_release -a 2>/dev/null || cat /etc/os-release | head -5

# ── Step 1: System packages ──────────────────────────────────────────────────
step "Installing system packages"
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  git curl wget ca-certificates gnupg \
  net-tools lsof ufw \
  python3 python3-pip python3-venv python3-dev \
  libpq-dev \
  htop jq \
  nginx-common

info "System packages installed"

# ── Step 2: Docker (for Postgres) ───────────────────────────────────────────
step "Installing Docker"
if command -v docker >/dev/null 2>&1; then
  info "Docker already installed: $(docker --version)"
else
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  info "Docker installed. You'll need to log out/in (or run 'newgrp docker') to use it without sudo."
fi

# ── Step 3: Node.js + PM2 ────────────────────────────────────────────────────
step "Installing Node.js (for PM2 process manager)"
if command -v node >/dev/null 2>&1; then
  info "Node already installed: $(node --version)"
else
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

if command -v pm2 >/dev/null 2>&1; then
  info "PM2 already installed: $(pm2 --version)"
else
  sudo npm install -g pm2
fi

# ── Step 4: uv (fast Python package manager) ────────────────────────────────
step "Installing uv (Python toolchain)"
if command -v uv >/dev/null 2>&1; then
  info "uv already installed: $(uv --version)"
else
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  # Add to shell profile for persistence
  if ! grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
  fi
fi

# ── Step 5: bittensor CLI in dedicated venv ─────────────────────────────────
step "Installing bittensor CLI in ~/bittensor-env"
BT_VENV="$HOME/bittensor-env"
if [[ ! -f "$BT_VENV/bin/btcli" ]]; then
  python3 -m venv "$BT_VENV"
  "$BT_VENV/bin/pip" install --upgrade pip
  "$BT_VENV/bin/pip" install bittensor bittensor-cli
  info "btcli installed at: $BT_VENV/bin/btcli"
else
  info "bittensor-env already exists — skipping"
fi

# ── Step 6: UFW firewall ─────────────────────────────────────────────────────
step "Configuring UFW firewall"
sudo ufw allow OpenSSH || true
sudo ufw allow 8094/tcp || true   # miner axon
sudo ufw --force enable
sudo ufw status

# ── Step 7: System tuning for a 16-core / 16GB VPS ──────────────────────────
step "Applying system tuning"
# Increase file descriptor limit (bittensor + asyncpg pools can open many)
if ! grep -q "sparket-miner" /etc/security/limits.conf 2>/dev/null; then
  echo "# sparket-miner" | sudo tee -a /etc/security/limits.conf >/dev/null
  echo "* soft nofile 65536" | sudo tee -a /etc/security/limits.conf >/dev/null
  echo "* hard nofile 65536" | sudo tee -a /etc/security/limits.conf >/dev/null
fi

# Enable NTP time sync (critical — validator tokens are time-based)
sudo timedatectl set-ntp true
info "NTP sync: $(timedatectl show -p NTPSynchronized --value)"

# ── Done ─────────────────────────────────────────────────────────────────────
step "Bootstrap complete"
cat <<EOF

Next steps:

  1. Log out and log back in (or run 'newgrp docker') so Docker works without sudo.

  2. Clone the repo (if you haven't):
       git clone https://github.com/sparketlabs/sparket-subnet.git ~/sparket-ai
       cd ~/sparket-ai

  3. Run the Sparket mainnet setup:
       bash scripts/setup_miner_mainnet.sh

  4. Verify your public IP matches what you set in .env.mainnet:
       curl -s https://ifconfig.me

EOF
echo -e "${GREEN}${BOLD}Ready to proceed.${NC}"
