#!/usr/bin/env bash
# =============================================================================
# setup_miner_mainnet.sh — One-shot Sparket miner MAINNET setup
#
# What this script does:
#   1. Activates bittensor-env and installs uv dependencies
#   2. Creates mainnet coldkey + hotkey (if missing)
#   3. Opens axon port 8094 in UFW
#   4. Starts production Postgres container (port 5432)
#   5. Runs database migrations
#   6. Passes the required mining interview
#   7. Installs model dependencies (lightgbm, scikit-learn)
#   8. Prints mainnet registration instructions
#
# Usage:
#   bash scripts/setup_miner_mainnet.sh
# =============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COLDKEY_NAME="sparket-mainnet-cold"
HOTKEY_NAME="sparket-miner"
AXON_PORT=8094
DB_PORT=5432
DB_NAME="sparket_miner"
DB_USER="sparket"
DB_PASSWORD="${SPARKET_DATABASE__PASSWORD:-changeme_strong_password}"
DB_CONTAINER="pg-sparket-miner"
DB_VOLUME="pg_sparket_miner_data"
BITTENSOR_VENV="$HOME/bittensor-env"
UV_VENV="$PROJECT_ROOT/.venv"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

step() { echo -e "\n${GREEN}${BOLD}[STEP]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
info() { echo -e "       $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Step 0: Sanity checks ────────────────────────────────────────────────────
step "Checking prerequisites"
cd "$PROJECT_ROOT"

if [[ -f "$BITTENSOR_VENV/bin/activate" ]]; then
  # shellcheck disable=SC1090
  source "$BITTENSOR_VENV/bin/activate"
  info "bittensor-env activated: $(which btcli)"
else
  warn "bittensor-env not found at $BITTENSOR_VENV — btcli may not be available"
fi

command -v docker >/dev/null 2>&1 || err "docker required: sudo apt install docker.io"
command -v uv     >/dev/null 2>&1 || err "uv required: curl -LsSf https://astral.sh/uv/install.sh | sh"

# ── Step 1: Install Python dependencies ─────────────────────────────────────
step "Installing Python dependencies via uv"
uv python install 3.10
uv sync --dev
info "venv ready at $UV_VENV"

# ── Step 2: Install competitive model dependencies ───────────────────────────
step "Installing competitive model dependencies (lightgbm, scikit-learn)"
"$UV_VENV/bin/pip" install --quiet lightgbm scikit-learn joblib
info "lightgbm + scikit-learn installed"

# ── Step 3: Create mainnet coldkey ───────────────────────────────────────────
step "Setting up mainnet wallet: coldkey='$COLDKEY_NAME' hotkey='$HOTKEY_NAME'"
echo ""
echo -e "${YELLOW}  ⚠  MAINNET coldkey — back up your mnemonic securely before continuing.${NC}"
echo ""

if btcli wallet overview --wallet.name "$COLDKEY_NAME" --subtensor.network finney \
     2>&1 | grep -q "$COLDKEY_NAME"; then
  warn "Coldkey '$COLDKEY_NAME' already exists — skipping creation"
else
  echo "Creating coldkey (you will be shown a mnemonic — WRITE IT DOWN):"
  btcli wallet new_coldkey --wallet.name "$COLDKEY_NAME"
fi

if btcli wallet overview --wallet.name "$COLDKEY_NAME" --wallet.hotkey "$HOTKEY_NAME" \
     --subtensor.network finney 2>&1 | grep -q "$HOTKEY_NAME"; then
  warn "Hotkey '$HOTKEY_NAME' already exists — skipping creation"
else
  btcli wallet new_hotkey \
    --wallet.name "$COLDKEY_NAME" \
    --wallet.hotkey "$HOTKEY_NAME" \
    --no_prompt
  info "Hotkey created."
fi

# ── Step 4: Open axon port ───────────────────────────────────────────────────
step "Opening axon port $AXON_PORT in UFW"
if command -v ufw >/dev/null 2>&1; then
  sudo ufw allow "${AXON_PORT}/tcp" || warn "UFW rule may already exist"
  sudo ufw --force enable
  sudo ufw status | grep "$AXON_PORT"
else
  warn "UFW not found — open port $AXON_PORT manually in your cloud security group"
fi

# ── Step 5: Start production Postgres ───────────────────────────────────────
step "Starting production Postgres on port $DB_PORT"
if docker ps --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
  warn "Container '$DB_CONTAINER' already running — skipping"
else
  docker rm -f "$DB_CONTAINER" 2>/dev/null || true
  docker run -d \
    --name "$DB_CONTAINER" \
    -e POSTGRES_USER="$DB_USER" \
    -e POSTGRES_PASSWORD="$DB_PASSWORD" \
    -e POSTGRES_DB="$DB_NAME" \
    -p "${DB_PORT}:5432" \
    -v "${DB_VOLUME}:/var/lib/postgresql/data" \
    --restart unless-stopped \
    postgres:18
  info "Waiting for Postgres to be ready..."
  for i in $(seq 1 30); do
    if docker exec "$DB_CONTAINER" pg_isready -U "$DB_USER" >/dev/null 2>&1; then
      info "Postgres ready (${i}s)"
      break
    fi
    sleep 1
  done
fi

# ── Step 6: Run database migrations ─────────────────────────────────────────
step "Running Alembic migrations"
export DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:${DB_PORT}/${DB_NAME}"
export SPARKET_ROLE=miner
export SPARKET_MINER_CONFIG_FILE="$PROJECT_ROOT/sparket/config/miner.mainnet.yaml"

"$UV_VENV/bin/sparket-alembic" upgrade head
info "Migrations complete."

# ── Step 7: Write mainnet YAML config ───────────────────────────────────────
step "Writing sparket/config/miner.mainnet.yaml"
cat > "$PROJECT_ROOT/sparket/config/miner.mainnet.yaml" <<YAML
role: miner

chain:
  netuid: 57   # verify at https://taostats.io — update if mainnet netuid differs

wallet:
  name: ${COLDKEY_NAME}
  hotkey: ${HOTKEY_NAME}

subtensor:
  network: finney

axon:
  host: 0.0.0.0
  port: ${AXON_PORT}
  # Uncomment and set if behind NAT:
  # external_ip: <your-vps-public-ip>

database:
  host: 127.0.0.1
  port: ${DB_PORT}
  user: ${DB_USER}
  name: ${DB_NAME}

miner:
  allow_connection_info_from_unpermitted_validators: false
YAML
info "Config written."

# ── Step 8: Mining interview ─────────────────────────────────────────────────
step "Running the Sparket mining interview (required)"
echo ""
echo -e "${YELLOW}Read docs/miner.md carefully before proceeding.${NC}"
echo "Press Enter to launch the interview, or Ctrl+C to skip and run later:"
read -r
"$UV_VENV/bin/python" -m sparket.tools.mining_interview

# ── Step 9: Print registration + launch instructions ─────────────────────────
step "Setup complete — mainnet next steps"
echo ""
echo -e "${BOLD}  1. Fund your coldkey on MAINNET${NC}"
echo "     Transfer TAO to:"
btcli wallet overview --wallet.name "$COLDKEY_NAME" --subtensor.network finney 2>/dev/null \
  | grep -A2 "Coldkey" || echo "     (run: btcli wallet overview --wallet.name $COLDKEY_NAME)"
echo ""
echo -e "${BOLD}  2. Confirm mainnet netuid at:${NC}"
echo "     https://taostats.io (search 'Sparket')"
echo "     Then update SPARKET_CHAIN__NETUID in .env.mainnet"
echo ""
echo -e "${BOLD}  3. Register hotkey on mainnet:${NC}"
echo ""
echo "     source $BITTENSOR_VENV/bin/activate"
echo "     btcli subnet register \\"
echo "       --wallet.name $COLDKEY_NAME \\"
echo "       --wallet.hotkey $HOTKEY_NAME \\"
echo "       --netuid <MAINNET_NETUID> \\"
echo "       --subtensor.network finney"
echo ""
echo -e "${BOLD}  4. Verify port $AXON_PORT is reachable (from another machine):${NC}"
echo "     nc -vz <your-vps-public-ip> $AXON_PORT"
echo ""
echo -e "${BOLD}  5. Start the competitive miner:${NC}"
echo "     cd $PROJECT_ROOT"
echo "     set -a && source .env.mainnet && set +a"
echo "     $UV_VENV/bin/python sparket/entrypoints/miner.py"
echo ""
echo -e "${BOLD}  6. Or with PM2 (recommended for production):${NC}"
echo "     pm2 start ecosystem.miner.config.js --env mainnet"
echo "     pm2 logs miner-local"
echo "     pm2 save && pm2 startup"
echo ""
echo -e "${BOLD}  7. Verify 5 milestones in logs (see docs/miner.md §First Run Verification)${NC}"
echo ""
echo -e "${BOLD}  8. Monitor weights:${NC}"
echo "     python scripts/check_weights.py --network finney --netuid <MAINNET_NETUID>"
echo ""
echo -e "${GREEN}${BOLD}Done.${NC}"
